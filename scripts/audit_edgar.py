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
                                  "cash": 2767856.4, "capex": 1282557.4}),
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
    "0941.HK": ("CNY", 207_267_000_000),
    "ARM": ("USD", 575_000_000),
    "AZN": ("USD", 5_905_000_000),
    "BTI": ("GBP", 704_000_000),
    "CAT": ("USD", 4_286_000_000),
    "GSK": ("GBP", 2_985_000_000),
    "IBM": ("USD", 1_738_000_000),
    "INTC": ("USD", 17_672_000_000),
    "MRNA": ("USD", 202_000_000),
    "NOW": ("USD", 911_000_000),
    "NVS": ("USD", 3_900_000_000),
    "REGN": ("USD", 1_213_700_000),
    "SNOW": ("USD", 104_729_000),
    "TMUS": ("USD", 12_523_000_000),
    "UL": ("EUR", 1_591_000_000),
    "TSM": ("TWD", 1_282_557_400_000),
    "ABNB": ("USD", 33_000_000), "ADP": ("USD", 665_100_000),
    "APP": ("USD", 28_791_000), "ASML": ("EUR", 1_631_200_000),
    "BABA": ("CNY", 126_937_000_000), "BP": ("USD", 13_221_000_000),
    "CNQ": ("CAD", 6_791_000_000), "COP": ("USD", 12_553_000_000),
    "ENB": ("CAD", 9_165_000_000), "LLY": ("USD", 7_841_000_000),
    "NEE": ("USD", 24_606_000_000), "NVO": ("DKK", 90_113_000_000),
    "PDD": ("CNY", 1_145_077_000),
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
OTHER_CASH_FLOWS = (
    ("0857.HK", "capex_mixed_outflow", 1_524_000_000),
    ("ADBE", "capex_mixed_outflow", 134_000_000),
    ("ARM", "capex_financing_payment", 67_000_000),
    ("GOOG", "capex_mixed_outflow", 1_592_000_000),
    ("ISRG", "capex_mixed_outflow", 13_900_000),
    ("META", "capex_mixed_outflow", 4_231_000_000),
    ("MSFT", "capex_mixed_outflow", 1_743_000_000),
    ("NVDA", "capex_financing_payment", 101_000_000),
    ("PEP", "capex_mixed_outflow", 3_391_000_000),
    ("BP", "capex_reported_total", 14_533_000_000),
    ("SHEL", "capex_reported_total", 20_915_000_000),
    ("PDD", "cfo", 106_938_690_000),
    ("TSM", "capex_ppe", 1_272_410_500_000),
    ("TSM", "capex_intangibles", 10_146_900_000),
)
for symbol, key, amount in OTHER_CASH_FLOWS:
    if rows[symbol]["statement"]["facts"].get(key, {}).get("value") != amount:
        raise SystemExit(f"{symbol} {key}: expected {amount}")
    checked += 1
INCOME_STATEMENT = {
    "ADP": ("USD", {"ebit": 5_738_800_000, "client_funds_interest_expense": 318_300_000,
                     "client_funds_interest_income_corporate": 278_100_000,
                     "corporate_interest_expense_other": 141_000_000, "corporate_interest_income_other": 92_900_000}),
    "CNQ": ("CAD", {"ebit": 8_606_000_000, "asset_transaction_gain": 5_069_000_000,
                    "retirement_accretion": 380_000_000, "risk_management_net_gain": 18_000_000,
                    "foreign_exchange_net_gain": 762_000_000}),
    "COP": ("USD", {"ebit": 10_938_000_000}),
    "CVX": ("USD", {"ebit": 16_674_000_000, "sales": 184_432_000_000, "sales_and_other_income": 189_031_000_000}),
    "ETN": ("USD", {"ebit": 5_209_000_000}),
    "HCA": ("USD", {"ebit": 11_965_000_000}),
    "KLAC": ("USD", {"ebit": 5_660_780_000}),
    "LLY": ("USD", {"ebit": 26_302_000_000}),
    "NEM": ("USD", {"ebit": 10_961_000_000}),
    "NVS": ("USD", {"sales": 54_532_000_000, "other_revenues": 2_142_000_000}),
    "PSX": ("USD", {"ebit": 2_274_000_000}),
    "SHEL": ("USD", {"ebit": 27_582_000_000}),
    "SNY": ("EUR", {"sales": 43_626_000_000, "other_revenues": 3_090_000_000}),
    "TJX": ("USD", {"ebit": 7_178_000_000}),
    "TTE": ("USD", {"ebit": 21_407_000_000, "sales": 182_344_000_000,
                    "sales_before_excise": 201_196_000_000, "excise_taxes_on_sales": 18_852_000_000}),
    "XOM": ("USD", {"ebit": 33_938_000_000, "sales": 323_905_000_000, "sales_and_other_income": 332_238_000_000}),
}
for symbol, (currency, fields) in INCOME_STATEMENT.items():
    period = rows[symbol]["statement"]
    for key, amount in fields.items():
        fact = period["facts"].get(key, {})
        if (period["currency"], fact.get("value")) != (currency, amount):
            raise SystemExit(f"{symbol} {key}: expected {currency} {amount}; got {fact}")
        checked += 1
reviewed_gaps = {"AEM", "BMY", "DE", "GE", "IBM", "JNJ", "MRK", "PFE"}
for symbol in reviewed_gaps:
    period = rows[symbol]["statement"]
    if "ebit" in period["facts"] or not period.get("operating_profit_gap"):
        raise SystemExit(f"{symbol}: expected a documented operating profit gap")
# Face-statement and note reconciliations, in millions of reporting currency.
DEPRECIATION = {
    "ADBE": ("USD", {"da": 546, "da_with_accretion": 818}),
    "APP": ("USD", {"da_with_writeoffs": 194.778, "da_ppe_and_finance_lease": 25.7, "amortization": 97.404}),
    "DUK": ("USD", {"da_with_accretion": 7704, "da_excluding_nuclear_fuel": 6324, "retirement_accretion": 474}),
    "EQNR": ("USD", {"da": 9838, "da_with_impairment": 12318, "da_with_impairment_and_writeoffs": 12473}),
    "GD": ("USD", {"da": 924}),
    "HD": ("USD", {"da": 4121, "da_ppe": 3514, "amortization": 607}),
    "MRNA": ("USD", {"da": 215, "da_ppe": 211}),
    "NFLX": ("USD", {"da": 333.389, "amortization_content": 16422.166, "da_including_content": 16755.555}),
    "SPGI": ("USD", {"da": 1179}),
    "UBER": ("USD", {"da": 719, "da_including_nonoperating": 747}),
    "UL": ("EUR", {"da": 1310, "da_with_impairment": 1353, "asset_impairment": 43}),
    "XOM": ("USD", {"da_with_impairment": 25993}),
    "AMGN": ("USD", {"da_with_other": 5167}),
    "AMZN": ("USD", {"da_with_other": 65756}),
    "BABA": ("CNY", {"da": 45014, "da_ppe": 34963, "amortization": 10051, "ppe_da_with_impairment_and_lease": 37067}),
    "CRM": ("USD", {"amortization_purchased_intangibles": 1687, "da_ppe": 1200, "da_with_rou_and_impairment": 3631, "amortization_deferred_contract_costs": 2197}),
    "NVO": ("DKK", {"da": 14666, "da_with_impairment": 21982, "asset_impairment": 7316}),
    "0857.HK": ("CNY", {"da": 238036}),
    "ABBV": ("USD", {"da": 8139}),
    "ABNB": ("USD", {"da": 91}),
    "ABT": ("USD", {"da": 3116}),
    "ACN": ("USD", {"da": 1239.157, "da_with_other": 2355.282, "operating_lease_cost": 781.808,
                    "amortization_deferred_transition": 327.680, "other_da_adjustment": 6.637}),
    "ADI": ("USD", {"da": 1998.845}),
    "AEM": ("USD", {"da": 1645.297}),
    "AMD": ("USD", {"da": 3004}),
    "AVGO": ("USD", {"da": 8636, "amortization_with_rou": 8201}),
    "AZN": ("USD", {"da": 5490, "da_with_impairment": 5733, "asset_impairment": 243}),
    "BTI": ("GBP", {"da": 2245, "da_with_impairment": 2547, "asset_impairment": 302}),
    "BUD": ("USD", {"da_with_impairment": 5652, "da": 5045}),
    "CRWD": ("USD", {"da": 281.451, "amortization_deferred_contract_costs": 449.413}),
    "CSCO": ("USD", {"da_with_other": 2540, "da_ppe": 700}),
    "CVNA": ("USD", {"da": 275}),
    "DHR": ("USD", {"da": 2447}),
    "GE": ("USD", {"da": 1220}),
    "GEV": ("USD", {"da": 853}),
    "GILD": ("USD", {"da": 2760}),
    "GOOG": ("USD", {"depreciation": 21136}),
    "IBM": ("USD", {"da": 5021}),
    "INTC": ("USD", {"da": 11706}),
    "ISRG": ("USD", {"da": 613.2, "depreciation_with_disposal_loss": 614.7, "amortization_with_other_assets": 62.4}),
    "MAR": ("USD", {"da": 458, "da_with_other": 599}),
    "MCD": ("USD", {"da": 2199, "da_general_and_administrative": 457}),
    "MCK": ("USD", {"da": 729, "da_ppe_and_finance_lease": 287}),
    "MRK": ("USD", {"da": 5838}),
    "MRVL": ("USD", {"da": 1290.6}),
    "MSFT": ("USD", {"da": 39000, "da_with_other": 38534}),
    "NVS": ("USD", {"da": 4744}),
    "ORCL": ("USD", {"da": 9294}),
    "PH": ("USD", {"da": 937}),
    "RIO": ("USD", {"da": 6577}),
    "SAP": ("EUR", {"da": 1311}),
    "SHEL": ("USD", {"da": 25299}),
    "SNY": ("EUR", {"da_with_impairment": 5678}),
    "SO": ("USD", {"da_with_accretion": 6030, "da_excluding_nuclear_fuel": 5501}),
    "SPOT": ("EUR", {"da": 102}),
    "TMO": ("USD", {"da": 2780}),
    "TSLA": ("USD", {"da_with_impairment": 6148}),
    "TSM": ("TWD", {"da": 688096.4}),
    "TTE": ("USD", {"da_with_impairment": 13847}),
    "TXN": ("USD", {"da": 1999}),
    "UNP": ("USD", {"da": 2465}),
    "VLO": ("USD", {"da": 3158, "da_cost_of_sales": 3095, "da_general_and_administrative": 63}),
    "WMT": ("USD", {"da": 14203}),
}
for symbol, (currency, fields) in DEPRECIATION.items():
    period = rows[symbol]["statement"]
    for key, millions in fields.items():
        fact = period["facts"].get(key, {})
        amount = round(millions * 1_000_000)
        if (period["currency"], fact.get("value")) != (currency, amount):
            raise SystemExit(f"{symbol} {key}: expected {currency} {amount}; got {fact}")
        checked += 1
for symbol in ("AMGN", "AMZN", "APP", "CRM", "CSCO", "DUK", "GOOG", "SNY", "SO", "TSLA", "TTE", "XOM"):
    period = rows[symbol]["statement"]
    if "da" in period["facts"] or not period.get("depreciation_gap"):
        raise SystemExit(f"{symbol}: expected a documented D&A gap")
issuers = set(EXPECTED) | set(CASH_INVESTMENT) | set(INCOME_STATEMENT) | set(DEPRECIATION) | {"SO"}
issuers.update(symbol for symbol, _, _ in OTHER_CASH_FLOWS)
print(f"Matched {checked} filed and reconciled values across {len(issuers)} issuers")
