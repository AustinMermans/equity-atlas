"""Verify source provenance and date/coverage rules before publishing Pages."""
from datetime import date
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from equity_atlas.issuer_20f import MIRRORS
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
    if period.get("route") == "issuer_20f":
        report = row["edgar"]["latest_annual"]
        cik = int(row["id"].removeprefix("sec:"))
        mirror = MIRRORS.get((cik, report["accession"]))
        if (not mirror or period["filing"] != report["accession"] or
                (period["end"], period["currency"]) != mirror[:2] or period["report"] != report or
                row["source"] != "Issuer 20-F" or row["edgar"]["annual_route"] != "issuer_20f"):
            raise SystemExit("Issuer mirror does not match the expected SEC filing")
    elif row["source"] == "Issuer 20-F" and period is row["statement"]:
        raise SystemExit("Missing issuer mirror provenance")
    for fact in period["facts"].values():
        source=fact["source"]
        url=fact["url"]
        official=source.startswith(("https://data.sec.gov/", "https://www.sec.gov/Archives/edgar/"))
        if mirror:
            official=(source==mirror[2] and url==report["url"] and fact["filed"]==report["filed"] and
                      fact["form"]==report["form"] and fact["tag"].startswith("issuer20f:") and
                      len(fact["sha256"])==64)
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
        fresh += 0 <= (asof-date.fromisoformat(row["statement"]["end"])).days <= 465
    for kind in ("quarter","ytd"):
        if row.get("edgar",{}).get(kind):
            verify_period(row["edgar"][kind], row)

if sum(r["source"]=="Issuer 20-F" for r in rows)!=snap["stats"].get("latest_annual_issuer_mirror",0):
    raise SystemExit("Issuer mirror coverage mismatch")
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
