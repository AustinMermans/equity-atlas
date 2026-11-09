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
from equity_atlas.issuer_10q import ROUTE as QUARTER_PDF_ROUTE, quarter_copy_url
from equity_atlas.issuer_20f import COPY_SOURCES, FCA_BHP, MIRRORS
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
    route = period.get("route")
    interim_copy = None
    resolvers = {"issuer_inline": inline_url, "issuer_instance": issuer_instance_url, QUARTER_PDF_ROUTE: quarter_copy_url}
    if route in resolvers:
        report = row["edgar"]["latest_interim"]
        cik = int(row["id"].removeprefix("sec:"))
        interim_copy = resolvers[route](cik,report)
        if (not interim_copy or period["report"] != report or
                row["edgar"]["interim_routes"].get(period["period_kind"]) != route):
            raise SystemExit("Public copy does not match the expected SEC interim filing")
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
    for fact in period["facts"].values():
        source=fact["source"]
        url=fact["url"]
        official=source.startswith(("https://data.sec.gov/", "https://www.sec.gov/Archives/edgar/"))
        if mirror:
            official=(source==mirror[2] and url==report["url"] and fact["filed"]==report["filed"] and
                      fact["form"]==report["form"] and fact["tag"].startswith(route + ":") and
                      len(fact["sha256"])==64)
        if interim_copy:
            locator = fact.get("locator") if route == QUARTER_PDF_ROUTE else fact.get("context_id")
            official = (source == interim_copy and url == report["url"] and fact["accession"] == report["accession"]
                        and fact["filed"] == report["filed"] and fact["form"] == report["form"]
                        and bool(locator) and len(fact["sha256"]) == 64)
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

for source, count in (("Issuer 20-F", "latest_annual_issuer_mirror"), ("FCA 20-F", "latest_annual_regulator_mirror")):
    if sum(r["source"]==source for r in rows)!=snap["stats"].get(count,0):
        raise SystemExit(f"{source} coverage mismatch")
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
