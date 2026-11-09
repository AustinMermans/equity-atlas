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
    "AXP": ("USD", 2_426_000_000),
    "C": ("USD", 6_520_000_000),
    "IBKR": ("USD", 67_000_000),
    "PGR": ("USD", 348_000_000),
    "SCHW": ("USD", 548_000_000),
    "UBS": ("USD", 2_362_000_000),
    "BHP": ("USD", 9_910_000_000),
    "0941.HK": ("CNY", 207_267_000_000),
    "ARM": ("USD", 575_000_000),
    "AZN": ("USD", 5_905_000_000),
    "BTI": ("GBP", 704_000_000),
    "CAT": ("USD", 4_286_000_000),
    "DE": ("USD", 4_228_000_000),
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
    "PLD": ("USD", 3_670_812_000), "SMFG": ("JPY", 459_404_000_000), "WELL": ("USD", 1_487_994_000),
}
for symbol, expected in CASH_INVESTMENT.items():
    period = rows[symbol]["statement"]
    fact = period["facts"].get("capex", {})
    if (period["currency"], fact.get("value")) != expected:
        raise SystemExit(f"{symbol} cash investment: expected {expected}; got {fact}")
    checked += 1
OTHER_CASH_FLOWS = (
    ("AXP", "capex_net_of_disposals", 2_425_000_000),
    ("AXP", "capex_disposal_proceeds", 1_000_000),
    ("BMO", "capex_net_of_disposals", 1_729_000_000),
    ("CM", "capex_net_of_disposals", 1_109_000_000),
    ("PGR", "capex_disposal_proceeds", 80_000_000),
    ("TD", "capex_net_of_disposals", 2_145_000_000),
    ("UBS", "capex_disposal_proceeds", 209_000_000),
    ("BNS", "capex_net_of_disposals", 347_000_000),
    ("HSBC", "capex_net_of_disposals", 1_447_000_000),
    ("HSBC", "capex_net_intangibles", 3_214_000_000),
    ("MS", "capex_net_of_disposals", 2_898_000_000),
    ("RY", "capex_net_of_disposals", 2_243_000_000),
    ("PLD", "capex_property_acquisitions", 1_800_527_000),
    ("PLD", "capex_disposal_proceeds", 2_246_186_000),
    ("SMFG", "capex_disposal_proceeds", 11_552_000_000),
    ("WELL", "capex_property_acquisitions", 13_913_975_000),
    ("WELL", "capex_capitalized_interest", 33_799_000),
    ("WELL", "capex_disposal_proceeds", 5_658_270_000),
    ("APP", "capex_intangibles_discontinued", 22_429_000),
    ("APP", "capex_intangibles_continuing", 5_889_000),
    ("BHP", "capex_ppe", 9_849_000_000),
    ("BHP", "capex_exploration_capitalized", 61_000_000),
    ("BHP", "exploration_evaluation_spending", 408_000_000),
    ("BHP", "exploration_evaluation_expensed", 347_000_000),
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
    "AEM": ("USD", {"mining_profit_before_financial_and_other": 6_638_437_000, "finance_costs_filed": 91_145_000,
                    "derivatives_net_gain_filed": 223_960_000, "fx_translation_net_gain": 25_654_000,
                    "other_income_expense_filed": 92_995_000, "pretax_before_financing_and_portfolio": 6_665_884_000}),
    "BMY": ("USD", {"operating_profit_before_other_items": 10_002_000_000, "other_income_expense_filed": 674_000_000,
                    "pretax_before_financing_and_portfolio": 10_709_000_000}),
    "JNJ": ("USD", {"operating_profit_before_other_items": 25_287_000_000, "other_income_expense_filed": -7_209_000_000,
                    "net_interest_expense_filed": -85_000_000}),
    "MRK": ("USD", {"operating_profit_before_other_items": 21_218_000_000, "other_income_expense_filed": 151_000_000,
                    "pretax_before_financing_portfolio_and_nonservice_benefits": 21_098_000_000}),
    "PFE": ("USD", {"operating_profit_before_other_items": 14_244_000_000, "other_income_expense_filed": 6_724_000_000,
                    "pretax_before_financing_portfolio_and_nonservice_benefits": 8_977_000_000}),
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
# Deere's fiscal 2025 segment note and supplemental consolidating data, USD millions.
DEERE_SCOPES = {
    "ebit_equipment_segments": 4906, "ebit_financial_services_segment": 1114,
    "ebit_reported_segment_total": 6020, "pretax_equipment_operations": 5145,
    "pretax_financial_services": 1112, "net_equipment_operations": 4137,
    "net_financial_services": 890, "cfo_equipment_operations": 5100,
    "cfo_financial_services": 2480, "distributions_from_financial_services": 1368,
    "cfo_equipment_before_finance_distributions": 3732, "da_equipment_operations": 1280,
    "da_financial_services": 1082, "capex_ppe_equipment_operations": 1358,
    "capex_ppe_financial_services": 2, "operating_lease_equipment_purchases_financial_services": 3053,
    "operating_lease_equipment_sales_financial_services": 1917, "assets_equipment_operations": 42859,
    "assets_financial_services": 70021, "equity_equipment_operations_adjusted": 18887,
    "equity_financial_services": 7069,
}
for key, amount in DEERE_SCOPES.items():
    fact = rows["DE"]["statement"]["facts"].get(key, {})
    if (fact.get("unit"), fact.get("value")) != ("USD", amount * 1_000_000):
        raise SystemExit(f"DE {key}: annual business-scope amount changed")
    checked += 1
reviewed_gaps = {"AEM", "BMY", "DE", "GE", "IBM", "JNJ", "MRK", "PFE"}
for symbol in reviewed_gaps:
    period = rows[symbol]["statement"]
    if "ebit" in period["facts"] or not period.get("operating_profit_gap"):
        raise SystemExit(f"{symbol}: expected a documented operating profit gap")
# USD millions in the sign convention printed by the filing notes.
ANNUAL_NOTES = {
    "AEM": {
        "other_income_expense_note": (92.995, (41.219, -58.144, 43.239, 40.175, 26.506)),
        "derivative_gain_loss_note": (-223.960, (-0.968, -111.203, 15.796, -127.585)),
    },
    "BMY": {"other_income_expense_note": (674, (1891, -1129, -1093, -586, 563, 434, 356, 351, -280, 147, 9, 11))},
    "MRK": {"other_income_expense_note": (151, (-343, 1357, 323, -368, -615, -203))},
    "PFE": {"other_income_expense_note": (6724, (-603, 2671, 67, -192, -678, 1057, 4940, 0, -538))},
    "CSCO": {"amortization_purchased_intangibles_with_impairment": (1863, (947, 916))},
    "GE": {"ge_insurance_income_note": (877, (1002, -125))},
    "IBM": {
        "other_income_expense_note": (-442, (993, -641, -645, 7, 65, -221)),
        "ibm_segment_profit_bridge": (10328, (16364, -2166, -154, -65, -1685, -1312, -653, -33, 31)),
        "ibm_segment_profit_note": (16364, (9920, 2464, 3458, 521)),
        "ibm_debt_split_note": (61260, (15093, 46167)),
    },
    "JNJ": {"other_income_expense_note": (-7200, (-6000, -500, -400, 200, 0, -500)),
            "jnj_segment_pretax_bridge": (32581, (22266, 4113, -6202))},
}
for symbol, fields in ANNUAL_NOTES.items():
    period = rows[symbol]["statement"]
    for key, (total, components) in fields.items():
        fact = period["facts"].get(key, {})
        actual = tuple(p["sign"] * p["value"] for p in fact.get("components", ()))
        expected = tuple(round(x * 1_000_000) for x in components)
        if (fact.get("unit"), fact.get("value"), actual) != ("USD", round(total * 1_000_000), expected):
            raise SystemExit(f"{symbol} {key}: annual note amounts changed")
        checked += 1 + len(expected)
SCOPED_LINES = {
    "BMY": {"divestiture_royalty_expense_income": -1129, "royalty_licensing_expense_income": -1093,
            "loss_on_debt_redemption": 356},
    "JNJ": {"jnj_innovative_medicine_pretax": 22266, "jnj_medtech_pretax": 4113, "jnj_unallocated_expense_income": -6202,
            "litigation_expense_income_rounded": -6000, "employee_benefit_expense_income_rounded": -500,
            "securities_fair_value_expense_income_rounded": -400},
    "PFE": {"asset_impairments_in_other_expense": 4940, "litigation_in_other_expense": 1057,
            "collaboration_licensing_expense_income": -192},
    "GE": {"runoff_insurance_pretax_income": 1002, "runoff_insurance_tax_effect": -125,
           "runoff_insurance_costs": 2541, "runoff_insurance_operating_profit": 992},
    "IBM": {"ibm_reportable_segment_profit": 16364, "ibm_net_interest_ex_financing": -1312,
            "ibm_nonoperating_retirement_income": -65, "ibm_financing_debt": 15093,
            "ibm_nonfinancing_debt": 46167, "ibm_software_segment_profit": 9920,
            "ibm_consulting_segment_profit": 2464, "ibm_infrastructure_segment_profit": 3458,
            "ibm_financing_segment_profit": 521},
}
for symbol, fields in SCOPED_LINES.items():
    facts = rows[symbol]["statement"]["facts"]
    for key, amount in fields.items():
        if (facts.get(key, {}).get("unit"), facts.get(key, {}).get("value")) != ("USD", amount * 1_000_000):
            raise SystemExit(f"{symbol} {key}: filed business-scope amount changed")
        checked += 1
# Face-statement and note reconciliations, in millions of reporting currency.
DEPRECIATION = {
    "HDB": ("INR", {"da": 61832.3, "da_ppe": 41150.7, "amortization": 20681.6,
                    "amortization_deferred_customer_acquisition": 52259.1}),
    "HSBC": ("USD", {"da_with_impairment": 4916, "ppe_da_with_impairment_and_rou": 1971,
                     "amortization_with_impairment": 2945}),
    "CB": ("USD", {"amortization": 301, "policy_acquisition_costs": 9847,
                   "amortization_p_and_c_dac": 8649, "amortization_voba": 224}),
    "PGR": ("USD", {"da": 313, "depreciation": 313, "amortization_policy_acquisition": 6096}),
    "AXP": ("USD", {"da": 1777}),
    "BMO": ("CAD", {"da": 2180, "da_ppe": 1015, "depreciation_other_assets": 13, "amortization": 1152}),
    "BX": ("USD", {"depreciation": 98, "amortization": 36.023}),
    "C": ("USD", {"da": 4373}),
    "CM": ("CAD", {"da_with_impairment": 1178, "ppe_da_with_impairment": 518, "amortization_with_impairment": 660}),
    "IBKR": ("USD", {"da": 61, "amortization_operating_rou": 32}),
    "JPM": ("USD", {"da": 8821, "depreciation_leased_assets": 2418}),
    "SCHW": ("USD", {"da": 1362, "da_excluding_acquired_intangibles": 850, "amortization": 512}),
    "TD": ("CAD", {"da": 2166, "depreciation": 1386, "amortization": 780}),
    "UBS": ("USD", {"da_with_impairment": 3529, "depreciation_ppe_and_software": 3339,
                    "impairment_ppe_and_software": 69, "amortization": 140}),
    "ADBE": ("USD", {"da": 546, "da_with_accretion": 818}),
    "APP": ("USD", {"da": 123.104, "da_with_writeoffs": 194.778, "da_ppe_and_finance_lease": 25.7, "amortization": 97.404}),
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
    "AMGN": ("USD", {"da": 5043, "da_with_other": 5167, "da_including_operating_rou": 5167,
                     "da_ppe": 763, "da_ppe_and_rou": 887}),
    "AMZN": ("USD", {"da": 42677, "da_with_other": 65756, "da_ppe_and_finance_lease": 41860,
                     "amortization": 817, "amortization_finance_rou": 3284}),
    "BABA": ("CNY", {"da": 45014, "da_ppe": 34963, "amortization": 10051, "ppe_da_with_impairment_and_lease": 37067}),
    "CRM": ("USD", {"da": 2887, "amortization_purchased_intangibles": 1687, "da_ppe": 1200, "amortization_finance_rou": 375, "da_with_rou_and_impairment": 3631, "amortization_deferred_contract_costs": 2197}),
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
    "SNY": ("EUR", {"da_with_impairment": 5678, "amortization": 1776,
                    "impairment_intangible_net": 2241, "impairment_ppe_net": 68, "depreciation": 977,
                    "ppe_da_with_impairment_and_rou": 269, "amortization_intangibles_total": 1924}),
    "SO": ("USD", {"da_with_accretion": 6030, "da_excluding_nuclear_fuel": 5501, "retirement_accretion": 393}),
    "SPOT": ("EUR", {"da": 102}),
    "TMO": ("USD", {"da": 2780}),
    "TSLA": ("USD", {"da_with_impairment": 6148, "da_ppe": 5030, "amortization_finance_rou": 118}),
    "TSM": ("TWD", {"da": 688096.4}),
    "TTE": ("USD", {"da_with_impairment": 13847, "impairment_ppe_and_exploration": 575,
                     "impairment_intangibles_and_goodwill": 235, "impairment_goodwill": 47,
                     "ppe_da_with_impairment": 12315, "mineral_amortization_with_impairment": 997,
                     "da_tangible_and_mineral_with_impairment": 13312}),
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
for symbol in ("BX", "CB", "CM", "CSCO", "DUK", "GOOG", "HSBC", "SNY", "SO", "TSLA", "TTE", "UBS", "XOM"):
    period = rows[symbol]["statement"]
    if "da" in period["facts"] or not period.get("depreciation_gap"):
        raise SystemExit(f"{symbol}: expected a documented D&A gap")
for symbol in ("BMO", "CM", "TD"):
    if "capex" in rows[symbol]["statement"]["facts"]:
        raise SystemExit(f"{symbol}: net purchases must remain separate from gross cash investment")
# FY2025/26 face-statement liability totals or sums of its disclosed lines, in millions.
LIABILITY_BALANCES = {
    "ABBV": 137188, "ABT": 33942, "ACN": 40340.676, "ADI": 14176.957, "AMD": 13927,
    "AMGN": 81928, "AMZN": 406977, "BUD": 121071, "DHR": 30923, "DIS": 82902,
    "DUK": 142717, "ETN": 21782, "GD": 31627, "GILD": 36405, "HCA": 63491,
    "INTC": 85069, "KO": 70541, "LLY": 85941, "MAR": 31311, "MCD": 61307,
    "MCK": 83157, "MRK": 84204, "ORCL": 218703, "SCCO": 10276.5, "SHOP": 1716,
    "SNY": 55095, "T": 291706, "TJX": 25577, "TMO": 56807, "TMUS": 160034,
    "TTE": 173532, "VLO": 31383, "VZ": 298517, "WMT": 178488,
}
for symbol, amount in LIABILITY_BALANCES.items():
    row = rows[symbol]
    fact = row["statement"]["facts"]["liabilities"]
    currency = "EUR" if symbol == "SNY" else "USD"
    residual = {"BUD": 1_000_000, "MCD": -1_000_000, "TMO": -1_000_000}.get(symbol, 0)
    if (fact["unit"], fact["value"], fact["balance_rounding_residual"]) != (currency, round(amount * 1_000_000), residual):
        raise SystemExit(f"{symbol}: recovered liability balance or rounding residual changed")
    checked += 1
for symbol, amount in {"ACN": 532_762_000, "MCK": 943_000_000, "T": 2_001_000_000,
                       "TMO": 122_000_000, "WMT": 293_000_000}.items():
    row = rows[symbol]
    if row["statement"]["facts"]["redeemable_nci"]["value"] != amount or row["balance_check"]["unexplained_residual"]:
        raise SystemExit(f"{symbol}: redeemable noncontrolling interest changed or the claims do not reconcile")
    checked += 1
marriott = rows["MAR"]["statement"]["facts"]["liabilities"]["components"]
if {part["member"]: part["value"] for part in marriott if "member" in part} != {
        "Liability for guest loyalty program": 4_495_000_000, "Deferred revenue": 1_200_000_000}:
    raise SystemExit("Marriott noncurrent contract-liability dimensions changed")
checked += 2
# Bank income before credit impairment, net fee income, and credit expense, in millions.
BANK_INCOME = {
    "HSBC": ("USD", (68274, 13343, 3850)),
    "SAN": ("EUR", (58670, 12976, 12546)),
    "SMFG": ("JPY", (4841783, 1517767, 392157)),
    "UBS": ("USD", (49573, 27912, 524)),
}
for symbol, (currency, amounts) in BANK_INCOME.items():
    statement = rows[symbol]["statement"]
    expected = tuple((currency, amount * 1_000_000) for amount in amounts)
    actual = tuple((statement["facts"][key]["unit"], statement["facts"][key]["value"])
                   for key in ("sales", "net_fee_income", "credit_impairment_expense"))
    if actual != expected or statement.get("sales_basis") != "bank_income_before_credit_impairment":
        raise SystemExit(f"{symbol}: bank revenue or credit scope changed")
    checked += len(amounts)

# Closing parent and common equity, in each issuer's reporting currency.
PARENT_EQUITY = {
    "AEM": ("USD", 24742464000, 24742464000), "AVGO": ("USD", 81292000000, 81292000000),
    "CNQ": ("CAD", 44366000000, 44366000000), "JNJ": ("USD", 81544000000, 81544000000),
    "NVO": ("DKK", 194047000000, 194047000000), "QCOM": ("USD", 30401000000, 30401000000),
    "SYK": ("USD", 22420000000, 22420000000), "TD": ("CAD", 127827000000, 116206000000),
    "V": ("USD", 36111000000, 35604000000),
}
for symbol, (currency, parent, common) in PARENT_EQUITY.items():
    facts = rows[symbol]["statement"]["facts"]
    if ((facts["book"]["unit"], facts["book"]["value"]) != (currency, parent)
            or (facts["common_book"]["unit"], facts["common_book"]["value"]) != (currency, common)):
        raise SystemExit(f"{symbol}: parent or common equity changed")
    checked += 2
if rows["TD"]["statement"]["facts"]["preferred_and_other_equity"]["value"] != 11_621_000_000:
    raise SystemExit("TD preferred shares and other equity instruments changed")
checked += 1
# Annual cash scopes independently reconciled to the selected filings.
CASH_BALANCES = {
    "AXP": ("USD", {"cash": 47623, "cash_including_restricted": 47792, "restricted_cash": 169}),
    "BAC": ("USD", {"cash": 225345, "cash_including_restricted": 231845, "restricted_cash": 6500}),
    "BRK-B": ("USD", {"cash": 51877, "cash_including_restricted": 52569, "restricted_cash": 692}),
    "C": ("USD", {"cash": 325161, "cash_including_restricted": 349579, "restricted_cash": 24418}),
    "CB": ("USD", {"cash": 2272, "cash_including_restricted": 2470, "restricted_cash": 198}),
    "COF": ("USD", {"cash": 57434, "restricted_cash": 4659}),
    "CVX": ("USD", {"cash": 6293}), "DHR": ("USD", {"cash": 4615}),
    "GE": ("USD", {"cash_including_restricted": 12392, "insurance_cash": 1264}),
    "GEV": ("USD", {"cash": 8469, "cash_including_restricted": 8848, "restricted_cash": 379}),
    "GILD": ("USD", {"cash": 7564}),
    "HDB": ("INR", {"cash": 1537828.1, "cash_including_restricted": 2547835.1, "restricted_cash": 1010007}),
    "JPM": ("USD", {"cash": 314338, "cash_including_restricted": 343338, "restricted_cash": 29000}),
    "MFG": ("JPY", {"cash": 62606401}), "MMM": ("USD", {"cash": 5235}),
    "MUFG": ("JPY", {"cash_including_restricted": 90378397, "cash_and_bank_deposits": 90369985,
                     "restricted_cash_in_other_assets": 8412}),
    "PG": ("USD", {"cash": 9942}),
    "PGR": ("USD", {"cash": 125, "restricted_cash": 13, "cash_including_restricted": 138}),
    "SBUX": ("USD", {"cash": 3219.8}),
    "WFC": ("USD", {"cash_including_restricted": 172593}),
}
for symbol, (currency, values) in CASH_BALANCES.items():
    facts = rows[symbol]["statement"]["facts"]
    for key, millions in values.items():
        fact = facts[key]
        if (fact["unit"], fact["value"]) != (currency, round(millions * 1_000_000)):
            raise SystemExit(f"{symbol}: unexpected {key} amount or currency")
        checked += 1
for symbol in ("BAC", "JPM"):
    if rows[symbol]["statement"]["facts"]["cash"].get("rounding_increment") != 100_000_000:
        raise SystemExit(f"{symbol}: missing restricted-cash source precision")
for symbol in ("GE", "MUFG", "WFC"):
    period = rows[symbol]["statement"]
    if "cash" in period["facts"] or not period.get("cash_gap"):
        raise SystemExit(f"{symbol}: expected a documented cash scope")

issuers = set(EXPECTED) | set(CASH_INVESTMENT) | set(INCOME_STATEMENT) | set(DEPRECIATION) | {"SO"}
for symbol, key in (("CRM", "da"), ("JNJ", "other_income_expense_note")):
    if rows[symbol]["statement"]["facts"][key].get("rounding_increment") != 100_000_000:
        raise SystemExit(f"{symbol}: missing source rounding disclosure")
if rows["JNJ"]["statement"]["facts"]["other_income_expense_note"]["anchor_value"] != 7_209_000_000:
    raise SystemExit("JNJ: incorrect exact other income and expense anchor")
checked += 1
for key, millions in {"ebit_adjusted": 9055, "sales_adjusted": 42322, "costs_adjusted": 34606,
                      "other_income_adjusted": 1339, "insurance_revenue": 3533}.items():
    fact = rows["GE"]["statement"]["facts"].get(key, {})
    if (fact.get("unit"), fact.get("value")) != ("USD", millions * 1_000_000):
        raise SystemExit(f"GE adjusted reconciliation: incorrect {key}")
    checked += 1
issuers.update(ANNUAL_NOTES)
issuers.update(LIABILITY_BALANCES)
issuers.update(BANK_INCOME)
issuers.update(PARENT_EQUITY)
issuers.update(CASH_BALANCES)
issuers.update(symbol for symbol, _, _ in OTHER_CASH_FLOWS)
print(f"Matched {checked} filed and reconciled values across {len(issuers)} issuers")
