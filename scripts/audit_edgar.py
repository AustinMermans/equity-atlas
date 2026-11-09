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
    "HDB": ("2026-03-31", "INR", {"sales": 2327345.3, "net_parent": 704793.4, "net_interest_income": 1499769.5,
                                  "credit_loss_provision": 168272.2, "loans_net": 30993886.5, "minority": 993299.1}),
    "JPM": ("2025-12-31", "USD", {"net": 55681, "net_parent": 57048, "preferred": 20045,
                                  "book": 362438, "common_book": 342393}),
    "SAN": ("2025-12-31", "EUR", {"net_common": 13479, "net_parent": 14101,
                                  "net_consolidated": 15500, "book": 103170}),
    "SONY": ("2026-03-31", "JPY", {"net_parent": -326865, "net_parent_continuing": 1030893,
                                   "net_discontinued": -1357758, "dividend_in_kind": 955700,
                                   "cfo_continuing": 1966292, "cfo_discontinued": -20675, "capex": 457681}),
    "TSM": ("2025-12-31", "TWD", {"sales": 3809054.3, "net_parent": 1697604.0,
                                  "net_consolidated": 1695124.9, "book": 5355038.7,
                                  "cash": 2767856.4, "capex": 1272410.5}),
}
PER_SHARE = {"eps_basic": (45.89, "INR/shares"), "eps_diluted": (45.75, "INR/shares"),
             "eps_ads_basic": (137.67, "INR/ADS"), "eps_ads_diluted": (137.25, "INR/ADS")}
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
for key, expected in PER_SHARE.items():
    fact = rows["HDB"]["statement"]["facts"].get(key, {})
    if (fact.get("value"), fact.get("unit")) != expected:
        raise SystemExit(f"HDB {key}: expected {expected}; got {fact}")
    checked += 1
print(f"Matched {checked} filed values across {len(EXPECTED)} issuers")
