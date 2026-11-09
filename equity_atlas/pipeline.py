"""Raw source -> issuer and coherent facts -> model decisions -> static screener."""
import csv
from collections import Counter
from datetime import date, datetime, timezone, timedelta
import io
import json
import math
from pathlib import Path
import re
import time

from .annual_exhibit import ADP, enrich_exhibit, supported as exhibit_supported
from .capex import CAPEX_TAG, enrich_capex, supported as capex_supported
from .depreciation import (
    TAG as DEPRECIATION_TAG, enrich_depreciation, gap_reason as depreciation_gap, profile_fields as depreciation_fields,
    rule_key as depreciation_rule_key, separate_partial_da,
)
from .operating import enrich_operating, gap_reason, profile_for as operating_profile
from .catalog import CIKS, LEIS, SUCCESSIONS, cik_on, classify, esef_list, sec_meta
from .facts import ANNUAL, INTERIM, STOCK, balance_check, from_sec, from_esef, latest_filing, qualifies, sec_filing_index
from .edgar import (
    amendment_reviews, annual_from_instance, instance_url, issuer_instance_url,
    periods_from_instance, periods_from_issuer_instance,
)
from .filing_notes import TAG as NOTE_TAG, enrich_notes, notes_for
from .inline import inline_url, periods_from_inline
from .issuer_claims import add_claims, claim_copy
from .issuer_10q import ROUTE as QUARTER_PDF_ROUTE, periods_from_10q, quarter_copy_url
from .issuer_20f import BHP_CAPEX_TAG, COPY_SOURCES, MIRRORS, read_mirror
from .sec_workbook import CAPEX_TAG as WORKBOOK_CAPEX_TAG, DA_TAG as WORKBOOK_DA_TAG, ROUTE as WORKBOOK_ROUTE, SOURCE as WORKBOOK_SOURCE, read_workbook, workbook_url
from .rendered_10q import ROUTE as RENDERED_ROUTE, periods_from_rendered_10q, rendered_10q_url
from .fetch import Cache, ESEF, RANK, SEC, atomic, dump, fx_snapshot, parallel, ticker_map
from .models import VERSION, fit, prepare
from .market import load_taiwan

def universe(blob, count, floor=None):
    rows=list(csv.DictReader(io.StringIO(blob.decode("utf-8-sig"))))
    required={"Rank","Name","Symbol","marketcap","country"}
    if not rows or not required<=rows[0].keys():
        raise ValueError("ranking schema changed or file empty")
    parsed=[]
    seen=set()
    last=float("inf")
    for ix,row in enumerate(rows,1):
        if count and len(parsed)>=count:
            break
        cap=float(row["marketcap"])
        if int(row["Rank"])!=ix or not math.isfinite(cap) or cap>last:
            raise ValueError(f"ranking out of order at source row {ix}")
        last=cap
        if floor is not None and cap<floor:
            break
        if not row["Name"].strip() or not row["Symbol"].strip() or cap<=0:
            raise ValueError(f"invalid ranked issuer at row {ix}")
        key=row["Symbol"].strip().upper()
        if key in seen:
            continue
        seen.add(key)
        parsed.append({"rank":ix,"name":row["Name"],"symbol":key,"country":row["country"],"market_cap_usd":cap})
    if count is not None and len(parsed)<count:
        raise ValueError(f"requested {count} names but ranking has {len(parsed)} usable rows")
    return parsed

def interim_statements(cache, obj, meta, day, cik, filings, annual, interim, issues):
    results={}
    routes={}
    start=date.fromisoformat(annual["end"])+timedelta(days=1) if annual else None
    end=date.fromisoformat(interim["end"])
    # Q1 is also year to date, so its standalone statement is sufficient.
    kinds=["quarter"]
    if qualifies("cfo", start, end, "ytd"):
        kinds.append("ytd")
    for kind in kinds:
        periods=from_sec(obj,meta,day,cik,filings,kind)
        match=next((x for x in periods if x["filing"]==interim["accession"] and x["end"]==interim["end"]),None)
        if match:
            results[kind]=match
            routes[kind]="company_facts"
    missing=tuple(kind for kind in kinds if kind not in results)
    if missing:
        try:
            raw, receipt=cache.get(instance_url(interim),8760)
            parsed=periods_from_instance(raw,receipt,interim,cik,missing)
            for kind in missing:
                if parsed[kind]:
                    results[kind]=parsed[kind][-1]
                    routes[kind]="filing_instance"
        except (OSError,ValueError,KeyError,TypeError) as exc:
            issues.append(f"SEC interim archive for {interim['end']}: {exc}")
    for route, url, parse in (
        ("issuer_instance", issuer_instance_url(cik,interim), periods_from_issuer_instance),
        ("issuer_inline", inline_url(cik,interim), periods_from_inline),
        (QUARTER_PDF_ROUTE, quarter_copy_url(cik,interim), periods_from_10q),
    ):
        pending=tuple(kind for kind in missing if kind not in results)
        if not pending or not url:
            continue
        try:
            raw, receipt=cache.get(url,8760)
            parsed=parse(raw,receipt,interim,cik,pending)
            for kind in pending:
                if parsed[kind]:
                    results[kind]=parsed[kind][-1]
                    routes[kind]=route
        except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
            issues.append(f"Issuer filing copy for {interim['end']} ({route}): {exc}")
    pending = tuple(kind for kind in missing if kind not in results)
    if pending and rendered_10q_url(cik, interim):
        try:
            parsed = periods_from_rendered_10q(cache, interim, cik, pending)
            for kind, periods in parsed.items():
                results[kind] = periods[-1]
                routes[kind] = RENDERED_ROUTE
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            issues.append(f"SEC rendered interim tables for {interim['end']}: {exc}")
    for kind in missing:
        if kind not in results:
            routes[kind]="unavailable"
    return {**results,"interim_routes":routes}


def hold_unreconciled(statement, field):
    facts=statement["facts"].copy()
    if field in facts:
        facts[field+"_unreconciled"]=facts.pop(field)
    return {**statement,"facts":facts}


def source_history(cache, cik, lei, day, sec_ttl_hours=36, audit_edgar=False, annual_only=False):
    choices=[]
    issues=[]
    entity=None
    audit={}
    annual_receipt=None
    if cik:
        try:
            obj, meta=cache.json(SEC.format(cik),sec_ttl_hours)
            entity=obj["entityName"]
            filings={}
            if audit_edgar:
                try:
                    submissions, _ = cache.json(sec_meta(cik), sec_ttl_hours)
                    filings=sec_filing_index(submissions,cik,day)
                    audit["metadata"]="verified"
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    audit["metadata"]="unavailable"
                    issues.append(f"SEC submissions metadata: {exc}")
            history=from_sec(obj,meta,day,cik,filings)
            predecessor_annual=None
            succession=SUCCESSIONS.get(cik)
            if succession and day>=date.fromisoformat(succession["effective"]):
                effective=date.fromisoformat(succession["effective"])
                prior=source_history(cache,succession["predecessor_cik"],None,effective-timedelta(days=1),
                                     sec_ttl_hours,audit_edgar,annual_only=True)
                previous=prior["history"]
                first_current=history[0]["end"] if history else succession["effective"]
                if not history and previous:
                    annual_receipt=prior["receipt"]
                history=[x for x in previous if x["end"]<first_current]+history
                predecessor_annual=prior["edgar"].get("latest_annual")
                audit["succession"]=succession
                if not previous:
                    issues.append("Predecessor annual history unavailable.")
            if audit_edgar:
                annual=latest_filing(filings,ANNUAL)
                interim=latest_filing(filings,INTERIM)
                audit.update(latest_annual=annual or predecessor_annual,latest_interim=interim)
                if "succession" in audit and not (annual or predecessor_annual):
                    audit["metadata"]="unavailable"
                audit["annual_route"]="company_facts" if history else "unavailable"
                statement=history[-1] if history else None
                same_year=bool(annual and statement and annual["end"]==statement["end"])
                needs_amendment=bool(same_year and annual["form"].endswith("/A") and
                                     annual["accession"]!=statement["filing"])
                reviews=amendment_reviews(filings,statement,annual) if needs_amendment else []
                if reviews:
                    audit["amendment_reviews"]=reviews
                    audit["annual_route"]="company_facts_reviewed_amendment"
                if annual and (not statement or statement["end"] < annual["end"] or
                               (needs_amendment and not reviews)):
                    try:
                        raw, instance_meta=cache.get(instance_url(annual),8760)
                        extra=annual_from_instance(raw,instance_meta,annual,cik)
                        if (not extra or extra[-1]["end"] != annual["end"] or
                                (needs_amendment and not {"assets","liabilities","book"} <= extra[-1]["facts"].keys())):
                            raise ValueError("No consolidated annual statement for the expected period")
                        history=[x for x in history if x["end"] < extra[-1]["end"]]+extra
                        audit["annual_route"]="filing_instance"
                        annual_receipt=instance_meta
                    except (OSError, ValueError, KeyError, TypeError) as exc:
                        audit["annual_route"]="amendment_pending" if needs_amendment else "latest_filing_gap"
                        scope="Amended annual statement" if needs_amendment else "Annual statement"
                        issues.append(f"{scope} for {annual['end']} unavailable from SEC archive: {exc}")
                        mirror=MIRRORS.get((cik,annual["accession"]))
                        for url, parser in ((mirror[2] if mirror else None, read_mirror),
                                            (workbook_url(cik, annual), read_workbook)):
                            if not url:
                                continue
                            try:
                                raw, receipt=cache.get(url,8760)
                                recovered=parser(raw,receipt,annual,cik)
                                history=[x for x in history if x["end"] < recovered["end"]]+[recovered]
                                audit["annual_route"]=recovered["route"]
                                annual_receipt=receipt
                                break
                            except (OSError,ValueError,KeyError,TypeError) as recovery_exc:
                                issues.append(f"Public 20-F fallback for {annual['end']}: {recovery_exc}")
                selected=history[-1] if history else None
                selected_filing=filings.get(selected["filing"]) if selected else None
                claim_profile=claim_copy(cik,selected_filing) if selected_filing else None
                if claim_profile:
                    try:
                        blob, receipt=cache.get(claim_profile[3],8760)
                        history[-1]=add_claims(blob,receipt,selected_filing,cik,selected)
                    except (OSError,ValueError,KeyError,TypeError) as exc:
                        issues.append(f"Annual equity claims for {selected['end']}: {exc}")
                if selected_filing and capex_supported(cik, selected_filing):
                    try:
                        history[-1]=enrich_capex(cache,obj,meta,cik,selected_filing,history[-1])
                    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                        issues.append(f"Annual cash investment for {selected['end']}: {exc}")
                        history[-1]=hold_unreconciled(history[-1],"capex")
                income_rule=operating_profile(cik,selected_filing) if selected_filing else None
                if income_rule:
                    try:
                        history[-1]=enrich_operating(cache,cik,selected_filing,history[-1])
                    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                        issues.append(f"Annual income statement for {selected['end']}: {exc}")
                        if income_rule.revised_sales:
                            history[-1]=hold_unreconciled(history[-1],"sales")
                if selected_filing and depreciation_fields(cik, selected_filing):
                    try:
                        history[-1]=enrich_depreciation(cache,obj,meta,cik,selected_filing,history[-1])
                    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                        issues.append(f"Annual depreciation and amortization for {selected['end']}: {exc}")
                        history[-1]=separate_partial_da(history[-1],depreciation_rule_key(cik, selected_filing))
                if selected_filing and "da" not in history[-1]["facts"]:
                    reason=depreciation_gap(cik,selected_filing)
                    if reason:
                        history[-1]={**history[-1],"depreciation_gap":reason}
                if selected_filing and exhibit_supported(cik, selected_filing):
                    try:
                        history[-1]=enrich_exhibit(cache,cik,selected_filing,history[-1],submissions,obj,meta)
                    except (OSError,ValueError,KeyError,TypeError,IndexError) as exc:
                        issues.append(f"Annual earnings exhibit for {selected['end']}: {exc}")
                if selected_filing and notes_for(cik, selected_filing):
                    try:
                        history[-1] = enrich_notes(cache, obj, meta, cik, selected_filing, history[-1])
                    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                        issues.append(f"Annual filing notes for {selected['end']}: {exc}")
                if selected_filing and "ebit" not in history[-1]["facts"]:
                    reason=gap_reason(cik,selected_filing)
                    if reason:
                        history[-1]={**history[-1],"operating_profit_gap":reason}
                annual_anchor=annual or predecessor_annual
                if not annual_only and interim and (not annual_anchor or interim["end"] > annual_anchor["end"]):
                    audit.update(interim_statements(cache,obj,meta,day,cik,filings,annual_anchor,interim,issues))
            if history:
                route=(WORKBOOK_SOURCE if audit.get("annual_route")==WORKBOOK_ROUTE
                       else COPY_SOURCES.get(audit.get("annual_route"),"SEC"))
                choices.append((route,history,annual_receipt or meta))
            else:
                issues.append("SEC: no qualifying annual statement.")
        except (OSError,ValueError,KeyError,TypeError) as exc:
            issues.append(f"SEC: {exc}")
    if lei:
        try:
            idx, listing=cache.json(esef_list(lei),48)
            entries=[]
            seen=set()
            for row in idx["data"]:
                a=row["attributes"]
                if not a["json_url"] or not a["report_url"] or a.get("error_count") or a["period_end"] in seen:
                    continue
                seen.add(a["period_end"])
                try:
                    doc, meta=cache.json(ESEF+a["json_url"],8760)
                    entries.append((a,doc,meta))
                except (OSError,ValueError) as exc:
                    issues.append(f"ESEF annual {a['period_end']}: {exc}")
                if len(entries)==8:
                    break
            history=from_esef(entries,day,lei)
            if history:
                choices.append(("ESEF",history,listing))
            else:
                issues.append("ESEF: no qualifying consolidated annual statement.")
        except (OSError,ValueError,KeyError,TypeError) as exc:
            issues.append(f"ESEF: {exc}")
    source, history, receipt=max(choices,key=lambda x:(x[1][-1]["end"],len(x[1]),x[0])) if choices else (None,[],None)
    return {"entity_name":entity,"source":source,"history":history,"issues":issues,"receipt":receipt,"edgar":audit}

def curated_history(symbol, day, curated):
    rec=curated.get(symbol)
    if not rec or date.fromisoformat(rec["filed"])>day:
        return []
    if not rec["url"].startswith("https://") or rec["unit"]<=0:
        raise ValueError("Issuer fallback requires a primary URL and explicit unit")
    import hashlib
    key=hashlib.sha256(json.dumps(rec,sort_keys=True).encode()).hexdigest()
    result=[]
    for end,cols in sorted(rec["years"].items()):
        when=date.fromisoformat(end)
        if when>day or end>rec["filed"]:
            continue
        start=str(when.replace(year=when.year-1)+timedelta(days=1))
        fields={k:{"value":v*rec["unit"],"tag":"issuer:"+(rec.get("net_scope","parent")+":" if k=="net" else "")+k,
                   "filed":rec["filed"],"start":None if k in STOCK else start,"source":rec["url"],
                   "sha256":key,"url":rec["url"],"form":"Issuer report","locator":rec["locator"]}
                for k,v in cols.items()}
        result.append({"end":end,"start":start,"currency":rec["currency"],"filing":rec["url"],"facts":fields,"conflicts":[],
                       "accounting":rec.get("accounting","IFRS")})
    return result

def accounting(h):
    if h:
        return h[-1].get("accounting") or ("US GAAP" if h[-1]["facts"]["net"]["tag"].startswith("us-gaap:") else "IFRS")
    return None

def list_public(public_csv):
    rows=list(csv.DictReader(Path(public_csv).open()))
    return {r["symbol"]:r for r in rows}

def make_public(cache, csv_path, out, day, open_market=False):
    public=list_public(csv_path)
    ciks={cik_on(int(x["cik"]),day) for x in public.values()}
    # Probe the official route before attempting the entire list. One blocked
    # source should not generate hundreds of identical requests.
    probe=320193 if 320193 in ciks else min(ciks)
    try:
        doc,_=cache.json(SEC.format(probe),18)
        if int(doc["cik"])!=probe:
            raise ValueError("SEC preflight CIK mismatch")
    except (OSError,ValueError,KeyError,TypeError) as exc:
        raise RuntimeError(f"SEC Company Facts preflight failed: {exc}") from exc
    sources=parallel(sorted(ciks),lambda cik:source_history(cache,cik,None,day,18,audit_edgar=True))
    rows=[]
    market_sources=None
    taiwan={}
    if open_market:
        market_rows, market_sources=load_taiwan(cache,day)
        taiwan={r["code"]:r for r in market_rows}
    for symbol, entry in sorted(public.items()):
        cik=cik_on(int(entry["cik"]),day)
        payload,err=sources[cik]
        h=(payload or {}).get("history",[])
        selected_source=(payload or {}).get("source")
        if symbol=="TSM" and "2330" in taiwan:
            seeds=json.loads((Path(__file__).resolve().parent.parent/"issuer-annual.json").read_text())
            extra=curated_history(symbol,day,seeds)
            if extra and (not h or h[-1]["end"] < extra[-1]["end"]):
                h=[x for x in h if x["end"] < extra[0]["end"]]+extra
                selected_source="Issuer"
        s=h[-1] if h else None
        k,g,why=classify(symbol,int(entry.get("sic") or 0))
        row={"id":f"sec:{cik:010d}","name":entry["name"],
             "symbol":symbol,"country":entry.get("country",""),"kind":k,"peer_group":g,
             "classification":why,"source":selected_source if s else None,"statement":s,
             "balance_check":balance_check(s) if s else None,
             "history":[{"end":x["end"],"currency":x["currency"],"sales_basis":x.get("sales_basis"),
                         "facts":{m:{"value":x["facts"][m]["value"]} for m in ("sales","ebit") if m in x["facts"]}}
                        for x in h],
             "issues":(payload or {}).get("issues",[]) + ([err] if err else []),"accounting":accounting(h),
             "edgar":(payload or {}).get("edgar",{})}
        if symbol=="TSM" and "2330" in taiwan:
            market=taiwan.pop("2330")
            row["market"]=market
            row["country"]="Taiwan"
            fx=market_sources["fx"]
            if fx and s and s["currency"]=="TWD":
                # Spot market inputs are measured on the close date. Only statements
                # already published on that date may enter the modeled comparisons.
                quote_day=date.fromisoformat(market["date"])
                knowable=[x for x in h if all(f["filed"]<=market["date"] for f in x["facts"].values())]
                if knowable and knowable[-1]["end"]==s["end"]:
                    case=prepare({**row,"market_cap_usd":market["estimated_cap_usd"],"as_of":market["date"]},
                                 knowable,{"TWD":fx},quote_day)
                    row.update(models=fit(case,[case]),ratios=case["ratios"],cycle=case["cycle"])
        rows.append(row)
    sec_rows=list(rows)
    for quote in taiwan.values():
        rows.append({"id":f"xtai:{quote['code']}","symbol":quote["code"]+".TW","name":quote["name"],
                     "country":"Taiwan","kind":"unknown","peer_group":"TWSE issuer registry",
                     "classification":"Public exchange record","source":None,"statement":None,
                     "market":quote,"issues":["Normalized annual filings are pending for this Taiwan issuer."]})
    rows.sort(key=lambda r:r["symbol"])
    if not any(r["statement"] for r in sec_rows):
        raise RuntimeError("Public dataset has no qualifying filings; refusing to replace the deployed snapshot")
    def fresh(r):
        return bool(r["statement"] and 0 <= (day-date.fromisoformat(r["statement"]["end"])).days <= 465)
    verified=[r for r in sec_rows if r["edgar"].get("metadata")=="verified"]
    latest=[r for r in verified if r["edgar"].get("latest_annual")]
    expected_interims = [r for r in verified if (interim := r["edgar"].get("latest_interim")) and
                         interim["end"] > (r["edgar"].get("latest_annual") or {}).get("end", "")]
    coverage={
        "sec_issuers":len(sec_rows), "metadata_verified":len(verified),
        "latest_annual_expected":len(latest),
        "latest_annual_extracted":sum(bool(r["source"]=="SEC" and r["statement"] and
                                   r["statement"]["end"]==r["edgar"]["latest_annual"]["end"] and
                                   (r["statement"]["filing"]==r["edgar"]["latest_annual"]["accession"] or
                                    r["edgar"].get("amendment_reviews"))) for r in latest),
        "latest_annual_reviewed_amendments":sum(bool(r["edgar"].get("amendment_reviews")) for r in latest),
        "latest_annual_pending_amendments":sum(r["edgar"].get("annual_route")=="amendment_pending" for r in latest),
        "latest_annual_issuer_mirror":sum(bool(r["source"]=="Issuer 20-F" and r["statement"] and
                                     r["statement"]["filing"]==r["edgar"]["latest_annual"]["accession"]) for r in latest),
        "latest_annual_regulator_mirror":sum(bool(r["source"]=="FCA 20-F" and r["statement"] and
                                     r["statement"]["filing"]==r["edgar"]["latest_annual"]["accession"]) for r in latest),
        "latest_annual_sec_workbook":sum(r["source"]==WORKBOOK_SOURCE for r in latest),
        "annual_cash_investment_profiled":sum(
            (r["statement"] or {}).get("facts", {}).get("capex", {}).get("tag") in {CAPEX_TAG, WORKBOOK_CAPEX_TAG, BHP_CAPEX_TAG} for r in sec_rows
        ),
        "annual_exhibits_profiled":sum(bool((r["statement"] or {}).get("annual_earnings_exhibit")) for r in sec_rows),
        "annual_note_profiled":sum(any(f["tag"] == NOTE_TAG for f in (r["statement"] or {}).get("facts", {}).values())
                                   for r in sec_rows),
        "annual_income_profiled":sum(bool((r["statement"] or {}).get("income_profiled")) for r in sec_rows),
        "annual_operating_profit_reviewed_gaps":sum(bool((r["statement"] or {}).get("operating_profit_gap")) for r in sec_rows),
        "annual_depreciation_profiled":sum(any(f["tag"] in {DEPRECIATION_TAG,WORKBOOK_DA_TAG}
                                               for f in (r["statement"] or {}).get("facts",{}).values()) for r in sec_rows),
        "annual_depreciation_reviewed_gaps":sum(bool((r["statement"] or {}).get("depreciation_gap")) for r in sec_rows),
        "interim_expected":len(expected_interims),
        "interim_available":sum(bool(r["edgar"].get("quarter")) for r in expected_interims),
    }
    data={"mode":"public_market" if open_market else "public_fundamentals",
          "policy_version":VERSION,"as_of":str(day),"generated_at":datetime.now(timezone.utc).isoformat(),
          "source":"SEC EDGAR filings and official exchange inputs" if open_market else "SEC EDGAR filings",
          "stats":{"issuers":len(rows),"fresh":sum(fresh(r) for r in sec_rows),
                   "priced":sum(bool(r.get("market")) for r in rows), **coverage},
          "rows":rows}
    if open_market:
        data["market_sources"]=market_sources
    # Keep Pages payload compact; line-oriented audit data stays local.
    render(out,data)
    return data

def run(cache, out, *, count=100, floor=None, ranking=None, overrides=None):
    start=time.monotonic()
    if ranking:
        import hashlib
        path=Path(ranking)
        raw=path.read_bytes()
        rank_meta={"url":"user-supplied ranking CSV","retrieved_at":datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
                   "sha256":hashlib.sha256(raw).hexdigest()}
    else:
        raw,rank_meta=cache.get(RANK,12)
    day=date.fromisoformat(rank_meta["retrieved_at"][:10])
    ranked=universe(raw,count,floor)
    seed=Path(__file__).resolve().parent.parent/"issuer-annual.json"
    curated=json.loads(seed.read_text()) if seed.exists() else {}
    policy=seed.with_name("issuer-overrides.json")
    estimates=json.loads(policy.read_text()) if policy.exists() else {}
    estimates.update(overrides or {})
    idx,map_meta=ticker_map(cache)
    try:
        fx=fx_snapshot(cache,day)
        fx_error=None
    except (OSError,ValueError,KeyError) as exc:
        fx={"USD":{"rate":1.0,"date":str(day)}}
        fx_error=str(exc)
    map_issues=[]
    mapped={}
    for row in ranked:
        sym=row["symbol"]
        cik=cik_on(CIKS.get(sym,(None,None))[0] or idx.get(sym) or idx.get(sym.replace(".","-")),day)
        if cik and cik in mapped:
            raise ValueError(f"duplicate issuer CIK {cik}: {mapped[cik]} and {sym}; resolve share classes before valuing")
        if cik:
            mapped[cik]=sym
        row.update(cik=cik,lei=LEIS.get(sym))
    idx_from_csv={}
    if Path("public-issuers.csv").exists():
        idx_from_csv=list_public("public-issuers.csv")
    to_sic=sorted({r["cik"] for r in ranked if r["cik"] and r["symbol"] not in idx_from_csv
                   and classify(r["symbol"],0)[0]=="unknown"})
    sec_details=parallel(to_sic,lambda cik:cache.json(sec_meta(cik),168))
    work=[(r["cik"],r["lei"]) for r in ranked if r["cik"] or r["lei"]]
    harvested=parallel(work,lambda x:source_history(cache,*x,day,audit_edgar=True))
    cases=[]
    for r in ranked:
        sym=r["symbol"]
        cik,lei=r["cik"],r["lei"]
        outcome, err=harvested.get((cik,lei),(None,None))
        outcome=outcome or {"source":None,"history":[],"receipt":None,"entity_name":None,"issues":[]}
        if sym in CIKS and outcome["entity_name"] and CIKS[sym][1] not in outcome["entity_name"].upper():
            outcome={**outcome,"history":[],"source":None,"issues":[*outcome["issues"],"CIK override identity mismatch."]}
        h=outcome["history"]
        extra=curated_history(sym,day,curated)
        if extra and (not h or extra[-1]["end"]>h[-1]["end"]):
            # Do not combine facts across reports in a single period.
            first=extra[0]["end"]
            h=[x for x in h if x["end"]<first]+extra
            outcome={**outcome,"source":"Issuer","receipt":None}
        sic_payload,sic_err=sec_details.get(cik,(None,None))
        sic=0
        if sic_payload and int(sic_payload[0]["cik"])==cik:
            sic=int(sic_payload[0].get("sic") or 0)
        if sym in idx_from_csv and int(idx_from_csv[sym]["cik"])==cik:
            sic=int(idx_from_csv[sym].get("sic") or 0)
        kind,group,classification=classify(sym,sic)
        issues=outcome["issues"] + ([err] if err else []) + ([f"Industry lookup: {sic_err}"] if sic_err else [])
        if not cik and not lei:
            issues.append("Issuer report fallback requires a manual refresh." if extra else
                          "No validated SEC CIK or ESEF LEI; local filings adapter needed.")
        case=prepare({**r,"kind":kind,"peer_group":group,"classification":classification,
                      "id":f"sec:{cik:010d}" if cik else f"lei:{lei}" if lei else f"unresolved:{sym}",
                      "accounting":accounting(h),"source":outcome["source"],"entity_name":outcome["entity_name"],
                      "ev_exclusion":(
                          "Client-funds investments and financing need a separate enterprise-value bridge." if cik == ADP else
                          "Captive finance needs a separated operating/debt bridge." if sym in {"TM","F","GM","CAT"} else None
                      ),
                      "source_receipt":outcome["receipt"],"as_of":str(day),"issues":issues,
                      "edgar":outcome.get("edgar",{}),"balance_check":balance_check(h[-1]) if h else None},h,fx,day)
        cases.append(case)
    # Same-group peer index avoids an all-universe search for every valuation.
    buckets={}
    for c in cases:
        buckets.setdefault((c["kind"],c["peer_group"],c["accounting"]),[]).append(c)
    for c in cases:
        c["models"]=fit(c,buckets[(c["kind"],c["peer_group"],c["accounting"])],estimates.get(c["id"]))
    for c in cases:
        del c["latest"],c["net_tag"]
    counts=Counter(m["method"] for c in cases for m in c["models"]["decisions"] if m["status"]=="estimated")
    stats={"issuers":len(cases),"statements":sum(bool(c["statement"]) for c in cases),
           "fresh":sum(c["fresh"] for c in cases),
           "selected":sum(c["models"]["selected"] is not None for c in cases),
           "classified":sum(c["kind"]!="unknown" for c in cases),
           "normalized":sum("mid_margin" in c["cycle"] for c in cases),
           "with_observed_multiple":sum(bool(c["ratios"]) for c in cases),
           "sources":dict(Counter(c["source"] or "none" for c in cases)),
           "models":dict(counts)}
    run={"mode":"private_market","policy_version":VERSION,"as_of":str(day),"ranking":rank_meta,
         "ticker_index":map_meta,"fx_error":fx_error,"stats":stats,"rows":cases}
    render(out,run)
    dump(Path(out)/"receipt.json",{"stats":stats,"ranking":rank_meta,"as_of":str(day),
                                   "elapsed_seconds":round(time.monotonic()-start,3),
                                   "cache_hits":cache.hits,"downloads":cache.downloads})
    return run

def render(out, data):
    out=Path(out)
    web=Path(__file__).resolve().parent.parent/"site"
    for name in ("index.html","app.js","style.css"):
        atomic(out/name,(web/name).read_bytes())
    atomic(out/"snapshot.json",json.dumps(data,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode())
