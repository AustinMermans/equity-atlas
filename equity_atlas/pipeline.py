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

from .catalog import CIKS, LEIS, classify, esef_list, sec_meta
from .facts import STOCK, from_sec, from_esef
from .fetch import Cache, ESEF, RANK, SEC, atomic, dump, fx_snapshot, parallel, ticker_map
from .models import VERSION, fit, prepare

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

def source_history(cache, cik, lei, day):
    choices=[]
    issues=[]
    entity=None
    if cik:
        try:
            obj, meta=cache.json(SEC.format(cik),36)
            entity=obj["entityName"]
            history=from_sec(obj,meta,day,cik)
            if history:
                choices.append(("SEC",history,meta))
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
    return {"entity_name":entity,"source":source,"history":history,"issues":issues,"receipt":receipt}

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

def make_public(cache, csv_path, out, day):
    public=list_public(csv_path)
    ciks={int(x["cik"]) for x in public.values()}
    sources=parallel(sorted(ciks),lambda cik:source_history(cache,cik,None,day))
    rows=[]
    for symbol, entry in sorted(public.items()):
        cik=int(entry["cik"])
        payload,err=sources[cik]
        h=(payload or {}).get("history",[])
        s=h[-1] if h else None
        k,g,why=classify(symbol,int(entry.get("sic") or 0))
        row={"id":f"sec:{cik:010d}","name":entry["name"],
             "symbol":symbol,"country":entry.get("country",""),"kind":k,"peer_group":g,
             "classification":why,"source":"SEC" if s else None,"statement":s,
             "history":[{"end":x["end"],"currency":x["currency"],
                         "facts":{m:{"value":x["facts"][m]["value"]} for m in ("sales","ebit") if m in x["facts"]}}
                        for x in h],
             "issues":(payload or {}).get("issues",[]) + ([err] if err else []),"accounting":accounting(h)}
        rows.append(row)
    if not any(r["statement"] for r in rows):
        raise RuntimeError("Public dataset has no qualifying filings; refusing to replace the deployed snapshot")
    data={"mode":"public_fundamentals","policy_version":VERSION,"as_of":str(day),
          "source":"SEC EDGAR company facts; public issuer list is alphabetical and has no rankings or market data.",
          "stats":{"issuers":len(rows),"fresh":sum(bool(r["statement"] and (day-date.fromisoformat(r["statement"]["end"])).days<=465) for r in rows)},
          "rows":rows}
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
        cik=CIKS.get(sym,(None,None))[0] or idx.get(sym) or idx.get(sym.replace(".","-"))
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
    harvested=parallel(work,lambda x:source_history(cache,*x,day))
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
                      "ev_exclusion":"Captive finance needs a separated operating/debt bridge." if sym in {"TM","F","GM"} else None,
                      "source_receipt":outcome["receipt"],"as_of":str(day),"issues":issues},h,fx,day)
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
