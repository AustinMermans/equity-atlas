"""Tie the launch cohort to specific financial statement line items."""
import json
from pathlib import Path
import sys

EXPECTED = {
    "AAPL": ("2026-09-26", "USD", {"sales": 478834, "net": 132175, "book": 112093,
                                  "capex": 9041, "da": 13423, "div_total": 15721}),
    "BAC": ("2025-12-31", "USD", {"net": 29055, "net_parent": 30509, "preferred": 25992,
                                  "book": 303243, "common_book": 277251, "sales": 113097}),
    "BRK-B": ("2025-12-31", "USD", {"sales": 371444, "contract_sales": 247244, "net_parent": 66968,
                                    "net_consolidated": 67260}),
    "JPM": ("2025-12-31", "USD", {"net": 55681, "net_parent": 57048, "preferred": 20045,
                                  "book": 362438, "common_book": 342393}),
    "SAN": ("2025-12-31", "EUR", {"net_common": 13479, "net_parent": 14101,
                                  "net_consolidated": 15500, "book": 103170}),
    "TSM": ("2025-12-31", "TWD", {"sales": 3809054.3, "net_parent": 1697604.0,
                                  "net_consolidated": 1695124.9, "book": 5355038.7,
                                  "cash": 2767856.4, "capex": 1272410.5}),
}
rows={r["symbol"]:r for r in json.loads(Path(sys.argv[1]).read_text())["rows"]}
checked=0
for symbol,(day, currency, fields) in EXPECTED.items():
    statement=rows[symbol]["statement"]
    if not statement or (statement["end"],statement["currency"])!=(day,currency):
        raise SystemExit(f"{symbol}: expected launch cohort period/currency {day} {currency}")
    for field, millions in fields.items():
        fact=statement["facts"].get(field, {})
        if abs(fact.get("value",float("inf")) - millions*1000000)>100000:
            raise SystemExit(f"{symbol} {field}: expected {millions} million {currency}; got {fact}")
        checked+=1
print(f"Matched {checked} filed values across {len(EXPECTED)} issuers")
