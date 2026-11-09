"""Verify source provenance and date/coverage rules before publishing Pages."""
from datetime import date
import json
import math
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from equity_atlas.capex import CAPEX_TAG, REPORTED_TOTALS, supported as capex_supported, valid_capex_source
from equity_atlas.catalog import SUCCESSIONS
from equity_atlas.inline import inline_url
from equity_atlas.facts import balance_check
from equity_atlas.edgar import REVIEWED_AMENDMENTS, issuer_instance_url
from equity_atlas.issuer_claims import claim_copy
from equity_atlas.issuer_10q import ROUTE as QUARTER_PDF_ROUTE, quarter_copy_url
from equity_atlas.issuer_20f import COPY_SOURCES, FCA_BHP, MIRRORS
from equity_atlas.sec_workbook import PROFILES, ROUTE as WORKBOOK_ROUTE, SOURCE as WORKBOOK_SOURCE, workbook_url
from equity_atlas.rendered_10q import ROUTE as RENDERED_ROUTE, TABLES, rendered_10q_url, table_url
from equity_atlas.operating import OPERATING_TAG, SALES_BASIS, PROFILES as INCOME_PROFILES, gap_reason
from equity_atlas.rendered_filing import ENDPOINT as RENDERED_ENDPOINT
from equity_atlas.market import CBC_FX, OPEN_LICENSE, TWSE_CLOSE, TWSE_DAILY_QUOTES, TWSE_ISSUERS

snap=json.loads(Path(sys.argv[1]).read_text())
rows=snap["rows"]
open_market=snap["mode"]=="public_market"
if snap["mode"] not in {"public_fundamentals","public_market"} or "ranking" in snap or not rows:
    raise SystemExit("Wrong snapshot edition")
if [r["symbol"] for r in rows]!=sorted({r["symbol"] for r in rows}):
    raise SystemExit("Public universe must be alphabetical by unique symbol")
asof=date.fromisoformat(snap["as_of"])
fresh=0
sec_count=0
interim_expected=0
quarters=0
capex_profiles=0
income_profiles=0
operating_gaps=0
prices=[]
market=snap.get("market_sources",{})
if open_market:
    receipts=market.get("receipts",{})
    close_url = receipts.get("close", {}).get("url")
    dated_close = TWSE_DAILY_QUOTES.format(date.fromisoformat(market["date"]).strftime("%Y%m%d"))
    if (market.get("license") != OPEN_LICENSE or close_url not in {TWSE_CLOSE, dated_close} or
            receipts.get("shares", {}).get("url") != TWSE_ISSUERS):
        raise SystemExit("Unverified public market sources")
    fx=market.get("fx")
    if fx and (fx["date"]!=market["date"] or fx["source"]["url"]!=CBC_FX or not 15<=fx["rate"]<=60):
        raise SystemExit("Unverified same-date FX")

def annual_income_cik(row, report):
    cik = int(row["id"].removeprefix("sec:"))
    succession = SUCCESSIONS.get(cik)
    if succession and row["edgar"].get("succession") == succession:
        predecessor = succession["predecessor_cik"]
        if report["path"].startswith(f"https://www.sec.gov/Archives/edgar/data/{predecessor}/"):
            return predecessor
    return cik


def verify_income_fact(period, report, profile, key, fact):
    parts = fact.get("components", [])
    terms = profile.fields[key]
    return (
        period["period_kind"] == "annual" and
        period["filing"] == report["accession"] == fact["accession"] and
        period["end"] == report["end"] and fact["url"] == report["url"] and
        fact["filed"] == report["filed"] and fact["form"] == report["form"] and
        fact["start"] == period["start"] and fact["unit"] == period["currency"] and
        fact["source"] == RENDERED_ENDPOINT and
        fact.get("table_url") == report["path"] + "/" + profile.table and
        re.fullmatch(r"[0-9a-f]{64}", fact["sha256"]) and
        re.fullmatch(r"[0-9a-f]{16}", fact.get("table_sha256_16", "")) and
        bool(fact.get("locator")) and len(parts) == len(terms) and
        all(part["sign"] == (-1 if term.startswith("-") else 1) and
            part["line"] == term.removeprefix("-") and bool(part["tag"]) and
            math.isfinite(part["value"]) for part, term in zip(parts, terms)) and
        fact["value"] == sum(part["sign"] * part["value"] for part in parts) and
        fact["tag"] == (OPERATING_TAG if key == "ebit" else parts[0]["tag"])
    )


def verify_period(period, row):
    mirror = None
    workbook = None
    route = period.get("route")
    interim_copy = None
    rendered = None
    resolvers = {"issuer_inline": inline_url, "issuer_instance": issuer_instance_url, QUARTER_PDF_ROUTE: quarter_copy_url}
    if route in resolvers:
        report = row["edgar"]["latest_interim"]
        cik = int(row["id"].removeprefix("sec:"))
        interim_copy = resolvers[route](cik,report)
        if (not interim_copy or period["report"] != report or
                row["edgar"]["interim_routes"].get(period["period_kind"]) != route):
            raise SystemExit("Public copy does not match the expected SEC interim filing")
    if route == RENDERED_ROUTE:
        report = row["edgar"]["latest_interim"]
        cik = int(row["id"].removeprefix("sec:"))
        rendered = rendered_10q_url(cik, report)
        if (not rendered or period["report"] != report or
                row["edgar"]["interim_routes"].get(period["period_kind"]) != route):
            raise SystemExit("Rendered tables do not match the expected SEC interim filing")
        sections = TABLES if period["period_kind"] == "ytd" else TABLES.keys() - {"cash_flow"}
        rendered_tables = {table_url(report, section) for section in sections}
    if route in COPY_SOURCES:
        report = row["edgar"]["latest_annual"]
        cik = int(row["id"].removeprefix("sec:"))
        mirror = MIRRORS.get((cik, report["accession"]))
        if (not mirror or period["filing"] != report["accession"] or
                (period["end"], period["currency"]) != mirror[:2] or period["report"] != report or
                row["source"] != COPY_SOURCES[route] or row["edgar"]["annual_route"] != route or
                (route == "regulator_20f") != (mirror[2] == FCA_BHP)):
            raise SystemExit("Public copy does not match the expected SEC filing")
    elif row["source"] in COPY_SOURCES.values() and period is row["statement"]:
        raise SystemExit("Missing public 20-F provenance")
    if route == WORKBOOK_ROUTE:
        report = row["edgar"]["latest_annual"]
        cik = int(row["id"].removeprefix("sec:"))
        workbook = workbook_url(cik, report)
        if (not workbook or period is not row["statement"] or period["filing"] != report["accession"] or
                period["report"] != report or period["end"] != report["end"] or
                period["currency"] != PROFILES[cik, report["accession"]][1] or
                row["source"] != WORKBOOK_SOURCE or row["edgar"]["annual_route"] != WORKBOOK_ROUTE):
            raise SystemExit("SEC workbook does not match the expected annual filing")
    elif row["source"] == WORKBOOK_SOURCE and period is row["statement"]:
        raise SystemExit("Missing SEC workbook provenance")
    annual_report = period.get("report") if period is row["statement"] else None
    income_profile = INCOME_PROFILES.get((annual_income_cik(row, annual_report), annual_report["accession"])) if annual_report else None
    for key, fact in period["facts"].items():
        source=fact["source"]
        url=fact["url"]
        official=source.startswith(("https://data.sec.gov/", "https://www.sec.gov/Archives/edgar/"))
        if mirror:
            official=(source==mirror[2] and url==report["url"] and fact["filed"]==report["filed"] and
                      fact["form"]==report["form"] and fact["tag"].startswith(route + ":") and
                      len(fact["sha256"])==64)
        if workbook:
            official = (source == workbook and url == report["url"] and fact["accession"] == report["accession"]
                        and fact["filed"] == report["filed"] and fact["form"] == report["form"]
                        and fact["tag"].startswith(WORKBOOK_ROUTE + ":") and bool(fact.get("locator"))
                        and len(fact["sha256"]) == 64)
        if interim_copy:
            locator = fact.get("locator") if route == QUARTER_PDF_ROUTE else fact.get("context_id")
            official = (source == interim_copy and url == report["url"] and fact["accession"] == report["accession"]
                        and fact["filed"] == report["filed"] and fact["form"] == report["form"]
                        and bool(locator) and len(fact["sha256"]) == 64)
        if rendered:
            official = (source == rendered and url == report["url"] and fact["accession"] == report["accession"]
                        and fact["filed"] == report["filed"] and fact["form"] == report["form"]
                        and fact.get("table_url") in rendered_tables and bool(fact.get("locator"))
                        and len(fact["table_sha256_16"]) == 16 and len(fact["sha256"]) == 64)
        if fact["tag"].startswith("filing_claims:"):
            report = period.get("report")
            cik = int(row["id"].removeprefix("sec:"))
            profile = claim_copy(cik,report) if report else None
            official = bool(profile and period is row["statement"] and
                            profile[:3] == (report["form"],period["end"],period["currency"]) and
                            source == profile[3] and key in profile[4] and fact["tag"] == f"filing_claims:{key}" and
                            url == report["url"] and period["filing"] == report["accession"] == fact["accession"] and
                            fact["filed"] == report["filed"] and fact["form"] == report["form"] and
                            fact["unit"] == period["currency"] and fact["start"] is None and
                            bool(fact.get("locator")) and len(fact["sha256"]) == 64)
        if fact["tag"] == CAPEX_TAG or key == "capex_reported_total":
            report = period.get("report")
            cik = int(row["id"].removeprefix("sec:"))
            components = fact.get("components", []) if key == "capex" else [fact]
            official = bool(
                report and period is row["statement"] and capex_supported(cik, report) and
                key in {"capex", "capex_reported_total"} and components and
                (key != "capex_reported_total" or (cik in REPORTED_TOTALS and fact["tag"] == REPORTED_TOTALS[cik][0])) and
                period["filing"] == report["accession"] and period["end"] == report["end"] and
                fact["value"] == sum(p["value"] for p in components) and
                len(components) == len({(p["tag"], p["locator"]) for p in components}) and
                fact["source"] == components[0]["source"] and fact["sha256"] == components[0]["sha256"] and
                all(p["url"] == report["url"] and p["accession"] == report["accession"] and
                    p["filed"] == report["filed"] and p["form"] == report["form"] and
                    p["start"] == period["start"] and p["unit"] == period["currency"] and
                    math.isfinite(p["value"]) and p["value"] >= 0 and bool(p.get("locator")) and
                    re.fullmatch(r"[0-9a-f]{64}", p["sha256"]) and valid_capex_source(p, cik, report)
                    for p in components) and
                all(fact[k] == components[0][k] for k in ("url", "accession", "filed", "form", "start", "unit"))
            )
        if fact["tag"] == OPERATING_TAG or (income_profile and key in income_profile.fields and source == RENDERED_ENDPOINT):
            official = bool(income_profile and key in income_profile.fields and
                            verify_income_fact(period, annual_report, income_profile, key, fact))
        if not official or not url.startswith("https://www.sec.gov/Archives/edgar/"):
            raise SystemExit("Unverified SEC fact source")
        if not date.fromisoformat(period["end"])<=date.fromisoformat(fact["filed"])<=asof:
            raise SystemExit("Fact dated outside the observation window")
        if not math.isfinite(fact["value"]):
            raise SystemExit("Nonfinite fact")

for row in rows:
    if row["id"].startswith("sec:"):
        sec_count += 1
    if {"market_cap_usd","rank","fx"}&row.keys():
        raise SystemExit("Unapproved market data found in public snapshot")
    q=row.get("market")
    if q:
        if not open_market or q["exchange"]!="XTAI" or q["date"]!=market["date"]:
            raise SystemExit("Unexpected exchange quote")
        if not 0 <= (asof-date.fromisoformat(q["date"])).days <= 7 or date.fromisoformat(q["shares_date"])>asof:
            raise SystemExit("Unusable market date")
        if q["issued_shares"]<=0 or q["close"]<=0 or not math.isclose(q["estimated_cap_twd"],q["close"]*q["issued_shares"]):
            raise SystemExit("Market-cap calculation mismatch")
        if fx and not math.isclose(q["estimated_cap_usd"],q["estimated_cap_twd"]/fx["rate"]):
            raise SystemExit("Currency conversion mismatch")
        prices.append(q)
    if {"models","ratios"}&row.keys() and not q:
        raise SystemExit("Valuation without an approved market input")
    if row["statement"]:
        verify_period(row["statement"], row)
        if "annual_cash_investment_profiled" in snap["stats"] and row["id"].startswith("sec:"):
            period = row["statement"]
            report = period.get("report")
            if report and capex_supported(int(row["id"].removeprefix("sec:")), report):
                if period["facts"].get("capex", {}).get("tag") != CAPEX_TAG:
                    raise SystemExit(f"Refusing to lose verified annual cash investment for {row['symbol']}")
                capex_profiles += 1
        if "annual_income_profiled" in snap["stats"] and row["id"].startswith("sec:"):
            period = row["statement"]
            report = period.get("report")
            cik = annual_income_cik(row, report) if report else None
            profile = INCOME_PROFILES.get((cik, report["accession"])) if report else None
            if profile:
                expected_basis = SALES_BASIS if profile.revised_sales else None
                if (not period.get("income_profiled") or period.get("sales_basis") != expected_basis or
                        any(period["facts"].get(key, {}).get("source") != RENDERED_ENDPOINT
                            for key in profile.fields)):
                    raise SystemExit(f"Refusing to lose reconciled income statement fields for {row['symbol']}")
                income_profiles += 1
            elif period.get("income_profiled") or period.get("sales_basis"):
                raise SystemExit(f"Unexpected annual income statement profile for {row['symbol']}")
            if row["history"][-1].get("sales_basis") != period.get("sales_basis"):
                raise SystemExit(f"Annual revenue basis differs between the statement and history for {row['symbol']}")
            expected_gap = gap_reason(cik, report) if report and "ebit" not in period["facts"] else None
            if period.get("operating_profit_gap") != expected_gap:
                raise SystemExit(f"Unverified annual operating profit gap for {row['symbol']}")
            operating_gaps += bool(expected_gap)
        if "balance_check" in row and row["balance_check"] != balance_check(row["statement"]):
            raise SystemExit("Balance-sheet reconciliation does not match published facts")
        fresh += 0 <= (asof-date.fromisoformat(row["statement"]["end"])).days <= 465
    audit = row.get("edgar", {})
    annual = audit.get("latest_annual")
    if row["id"].startswith("sec:"):
        cik = int(row["id"].removeprefix("sec:"))
        if annual and workbook_url(cik, annual) and (row["statement"] or {}).get("filing") != annual["accession"]:
            raise SystemExit(f"Refusing to lose verified annual coverage for {row['symbol']}")
        interim = audit.get("latest_interim")
        if (audit.get("metadata") == "verified" and interim and
                interim["end"] > (annual or {}).get("end", "")):
            interim_expected += 1
            quarters += bool(audit.get("quarter"))
            if rendered_10q_url(cik, interim) and not (audit.get("quarter") and audit.get("ytd")):
                raise SystemExit(f"Refusing to lose verified interim coverage for {row['symbol']}")
    succession = audit.get("succession")
    if succession:
        cik = int(row["id"].removeprefix("sec:"))
        if succession != SUCCESSIONS.get(cik) or date.fromisoformat(succession["effective"]) > asof:
            raise SystemExit("Unverified registrant succession")
    reviews = audit.get("amendment_reviews", [])
    if reviews:
        statement, annual = row["statement"], audit["latest_annual"]
        if (statement["end"] != annual["end"] or reviews[-1]["accession"] != annual["accession"]
                or reviews[-1]["url"] != annual["url"] or
                any(REVIEWED_AMENDMENTS.get((statement["filing"], r["accession"])) != r["scope"] for r in reviews)):
            raise SystemExit("Amendment review does not match the reported accessions")
    for kind in ("quarter","ytd"):
        if audit.get(kind):
            period, interim = audit[kind], audit["latest_interim"]
            if period["period_kind"] != kind or period["filing"] != interim["accession"] or period["end"] != interim["end"]:
                raise SystemExit("Interim period does not match the expected SEC filing")
            verify_period(period, row)

for source, count in (("Issuer 20-F", "latest_annual_issuer_mirror"), ("FCA 20-F", "latest_annual_regulator_mirror"),
                      (WORKBOOK_SOURCE, "latest_annual_sec_workbook")):
    if sum(r["source"]==source for r in rows)!=snap["stats"].get(count,0):
        raise SystemExit(f"{source} coverage mismatch")
if "annual_cash_investment_profiled" in snap["stats"] and capex_profiles != snap["stats"]["annual_cash_investment_profiled"]:
    raise SystemExit("Annual cash investment profile coverage mismatch")
if "annual_income_profiled" in snap["stats"] and (income_profiles, operating_gaps) != (
        snap["stats"]["annual_income_profiled"], snap["stats"]["annual_operating_profit_reviewed_gaps"]):
    raise SystemExit("Annual income statement coverage mismatch")
if "interim_expected" in snap["stats"] and (interim_expected, quarters) != (
        snap["stats"]["interim_expected"], snap["stats"]["interim_available"]):
    raise SystemExit("Standalone interim coverage mismatch")
if fresh < .80*sec_count or fresh!=snap["stats"]["fresh"]:
    raise SystemExit(f"Refusing to deploy coverage regression: {fresh}/{sec_count} recent statements")
if open_market:
    prices.sort(key=lambda q:q["rank"])
    if (len(prices)!=50 or len({q["code"] for q in prices})!=50
            or [q["rank"] for q in prices]!=list(range(1,51))
            or any(a["estimated_cap_twd"]<b["estimated_cap_twd"] for a,b in zip(prices,prices[1:]))):
        raise SystemExit("Public Taiwan universe incomplete or misranked")
    if snap["stats"]["metadata_verified"] < .95*sec_count:
        raise SystemExit("Insufficient SEC submissions coverage")
print(f"Public artifact verified: {fresh}/{sec_count} recent statements, {len(prices)} exchange prices, dated {asof}")
