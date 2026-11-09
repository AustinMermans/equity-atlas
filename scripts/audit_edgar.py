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
    "BX": ("2025-12-31", "USD", {"minority": 11835.143, "minority_consolidated_entities": 7224.211,
                                 "minority_holdings": 4610.932, "redeemable_nci": 1380.503}),
    "EQIX": ("2025-12-31", "USD", {"minority": -3, "redeemable_nci": 25}),
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
interim = rows["SO"]["edgar"]
for kind, expected in {
    "quarter": {"sales": 8843, "net_parent": 2046, "net_nci": 28, "assets": 164204,
                "book": 42056, "minority": 2750, "da_excluding_nuclear_fuel": 1444},
    "ytd": {"sales": 24218, "net_parent": 4577, "net_nci": 24, "cfo": 7880, "capex": 10200,
            "div": 2399, "div_nci": 127, "da_with_accretion": 4809},
}.items():
    period = interim.get(kind, {})
    if period.get("filing") != "0000092122-26-000069" or period.get("currency") != "USD":
        raise SystemExit(f"SO {kind}: missing the verified Q3 2026 filing")
    for key, millions in expected.items():
        if period["facts"].get(key, {}).get("value") != millions * 1000000:
            raise SystemExit(f"SO {kind}: unexpected {key}")
        checked += 1
    if kind == "quarter" and {"cfo", "capex"} & period["facts"].keys():
        raise SystemExit("SO standalone quarter contains year-to-date cash flow")
# Independently checked face-statement and reconciliation amounts, in base units.
CASH_INVESTMENT = {
    "ABNB": ("USD", 33_000_000), "ADP": ("USD", 665_100_000),
    "APP": ("USD", 28_791_000), "ASML": ("EUR", 1_631_200_000),
    "BABA": ("CNY", 126_937_000_000), "BP": ("USD", 13_221_000_000),
    "CNQ": ("CAD", 6_791_000_000), "COP": ("USD", 12_553_000_000),
    "ENB": ("CAD", 9_165_000_000), "LLY": ("USD", 7_841_000_000),
    "NEE": ("USD", 24_606_000_000), "PDD": ("CNY", 1_145_077_000),
    "PSX": ("USD", 2_233_000_000), "RIO": ("USD", 12_335_000_000),
    "SAP": ("EUR", 739_000_000), "SHEL": ("USD", 18_947_000_000),
    "SNY": ("EUR", 3_538_000_000), "TTE": ("USD", 16_953_000_000),
    "VLO": ("USD", 1_885_000_000), "VZ": ("USD", 17_011_000_000),
}
for symbol, expected in CASH_INVESTMENT.items():
    period = rows[symbol]["statement"]
    fact = period["facts"].get("capex", {})
    if (period["currency"], fact.get("value")) != expected:
        raise SystemExit(f"{symbol} cash investment: expected {expected}; got {fact}")
    checked += 1
for symbol, key, amount in (("BP", "capex_reported_total", 14_533_000_000),
                            ("SHEL", "capex_reported_total", 20_915_000_000),
                            ("PDD", "cfo", 106_938_690_000)):
    if rows[symbol]["statement"]["facts"].get(key, {}).get("value") != amount:
        raise SystemExit(f"{symbol} {key}: expected {amount}")
    checked += 1
print(f"Matched {checked} filed values across {len(set(EXPECTED) | set(CASH_INVESTMENT) | {'SO'})} issuers")
