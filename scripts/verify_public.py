"""Verify source provenance and date/coverage rules before publishing Pages."""
from datetime import date
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from equity_atlas.catalog import SUCCESSIONS
from equity_atlas.inline import inline_url
from equity_atlas.facts import balance_check
from equity_atlas.edgar import REVIEWED_AMENDMENTS, issuer_instance_url
from equity_atlas.issuer_claims import claim_copy
from equity_atlas.issuer_10q import ROUTE as QUARTER_PDF_ROUTE, quarter_copy_url
from equity_atlas.issuer_20f import COPY_SOURCES, FCA_BHP, MIRRORS
from equity_atlas.sec_workbook import PROFILES, ROUTE as WORKBOOK_ROUTE, SOURCE as WORKBOOK_SOURCE, workbook_url
from equity_atlas.rendered_10q import ROUTE as RENDERED_ROUTE, TABLES, rendered_10q_url, table_url
from equity_atlas.market import CBC_FX, OPEN_LICENSE, TWSE_CLOSE, TWSE_ISSUERS

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
prices=[]
market=snap.get("market_sources",{})
if open_market:
    receipts=market.get("receipts",{})
    if market.get("license")!=OPEN_LICENSE or receipts.get("close",{}).get("url")!=TWSE_CLOSE or receipts.get("shares",{}).get("url")!=TWSE_ISSUERS:
        raise SystemExit("Unverified public market sources")
    fx=market.get("fx")
    if fx and (fx["date"]!=market["date"] or fx["source"]["url"]!=CBC_FX or not 15<=fx["rate"]<=60):
        raise SystemExit("Unverified same-date FX")

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
