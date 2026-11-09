"""Keep licensed/private market data outside the public Pages artifact."""
from datetime import date
import json
from pathlib import Path
import sys

snap=json.loads(Path(sys.argv[1]).read_text())
rows=snap["rows"]
if snap["mode"]!="public_fundamentals" or "ranking" in snap or not rows:
    raise SystemExit("Wrong snapshot edition")
if [r["symbol"] for r in rows]!=sorted({r["symbol"] for r in rows}):
    raise SystemExit("Public universe must be alphabetical by unique symbol")
asof=date.fromisoformat(snap["as_of"])
fresh=0
for row in rows:
    if {"market_cap_usd","rank","models","ratios","fx"}&row.keys():
        raise SystemExit("Market data found in public snapshot")
    if row["statement"]:
        s=row["statement"]
        if row["source"]!="SEC" or any(not f["source"].startswith("https://data.sec.gov/") or
            date.fromisoformat(f["filed"])>asof for f in s["facts"].values()):
            raise SystemExit("Public source provenance changed")
        fresh += 0 <= (asof-date.fromisoformat(s["end"])).days <= 465
if fresh < .80*len(rows) or fresh!=snap["stats"]["fresh"]:
    raise SystemExit(f"Refusing to deploy coverage regression: {fresh}/{len(rows)} fresh")
print(f"Public artifact verified: {fresh}/{len(rows)} fresh, source-only, dated {asof}")
