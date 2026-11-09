"""Reconcile operating profit and revenue to exact annual filing lines."""

from dataclasses import dataclass

from .facts import annual_rule_key, recurring_annual_rules
from .rendered_filing import ENDPOINT, annual_table, scaled

OPERATING_TAG = "derived:FiledOperatingProfit"
SALES_BASIS = "operating_sales"

@dataclass(frozen=True)
class Profile:
    title: str
    table: str
    scale: int
    anchors: dict
    fields: dict
    checks: tuple = ()
    tolerance: int = 0
    revised_sales: bool = False
    line_tags: tuple = ()


CNQ_ACCRETION = "Asset retirement obligation accretion"
CNQ_RISK = "Risk management (gain) loss"
CNQ_FX = "Foreign exchange (gain) loss"
CNQ_TRANSACTIONS = "Gain on acquisitions, disposition, and remeasurement"
CNQ_OPERATING = (
    "Revenue", "-Production", "-Blending and feedstock", "-Transportation",
    "-Depletion, depreciation and amortization", "-Administration", "-Share-based compensation",
)
COP_REVENUE = "Sales and other operating revenues"
COP_OPERATING = (
    COP_REVENUE, "-Total costs and expenses", "Interest and debt expense",
    "Foreign currency transaction (gain) loss", "Other expenses",
)
CVX_REVENUE = "Sales and other operating revenues"
CVX_OPERATING = (
    CVX_REVENUE, "-Total Costs and Other Deductions", "Interest and debt expense",
    "Other components of net periodic benefit costs",
)
ETN_OPERATING = (
    "Net sales", "-Cost of products sold", "-Selling and administrative expense", "-Research and development expense",
)
HCA_OPERATING = (
    "Revenues", "-Salaries and benefits", "-Supplies", "-Other operating expenses", "-Depreciation and amortization",
)
KLAC_OPERATING = (
    "Total revenues", "-Costs of revenues", "-Research and development", "-Selling, general and administrative",
    "-Impairment of goodwill and purchased intangible assets",
)
LLY_OPERATING = (
    "Revenue", "-Cost of sales", "-Research and development", "-Marketing, selling, and administrative",
    "-Acquired in-process research and development", "-Asset impairment, restructuring, and other special charges",
)
NEM_PRETAX = "Income (loss) before income and mining tax and other items"
NEM_OPERATING = ("Sales (Note 5)", "-Total costs and expenses")
PSX_OPERATING = (
    "Sales and other operating revenues", "-Total Costs and Expenses", "Interest and debt expense",
    "Foreign currency transaction (gains) losses",
)
SHEL_OPERATING = ("Revenue", "-Total expenditure", "Interest expense")
TJX_OPERATING = ("Net sales", "-Cost of sales, including buying and occupancy costs", "-Selling, general and administrative expenses")
TTE_OPERATING = (
    "Revenues from sales", "Purchases, net of inventory variation", "Other operating expenses", "Exploration costs",
    "Depreciation, depletion and impairment of tangible assets and mineral interests", "Other income", "Other expense",
)
XOM_SALES = "Sales and other operating revenue::Revenues"
XOM_AFFILIATES = "Income from equity affiliates::Revenues"
XOM_OTHER = "Other income::Revenues"
XOM_OPERATING = (
    XOM_SALES, "-Total costs and other deductions", "Interest expense", "Non-service pension and postretirement benefit expense",
)

# All checks are zero-sum on the filed presentation signs. Excluded lines
# reconcile operating profit to pretax income, or net income where necessary.
PROFILES = {
    (1017413, "0001017413-26-000018"): Profile(
        "Consolidated Statements of Earnings", "R4.htm", 1_000_000,
        {"sales": "Revenue", "pretax": "Earnings before taxes"},
        {"ebit": CNQ_OPERATING, "asset_transaction_gain": (CNQ_TRANSACTIONS,),
         "retirement_accretion": (CNQ_ACCRETION,), "risk_management_net_gain": ("-" + CNQ_RISK,),
         "foreign_exchange_net_gain": ("-" + CNQ_FX,)},
        (
            ("Product sales", "Less: royalties", "-Revenue"),
            CNQ_OPERATING + ("-" + CNQ_ACCRETION, "-Interest and other financing expense", "-" + CNQ_RISK,
                             "-" + CNQ_FX, CNQ_TRANSACTIONS, "Gain from investment", "-Earnings before taxes"),
        ),
    ),
    (92122, "0000092122-26-000006"): Profile(
        "Consolidated Statements of Income - Southern", "R3.htm", 1,
        {"sales": "Total operating revenues", "ebit": "Operating Income"},
        {"da_excluding_nuclear_fuel": ("Depreciation and amortization",)},
        (("Total operating revenues", "-Total operating expenses", "-Operating Income"),),
        line_tags=(("Depreciation and amortization", "so:DepreciationAndAmortizationExcludingNuclearFuel"),),
    ),
    (1163165, "0001163165-26-000009"): Profile(
        "Consolidated Income Statement", "R3.htm", 1,
        {"sales": COP_REVENUE, "pretax": "Income (loss) before income taxes"},
        {"ebit": COP_OPERATING},
        (COP_OPERATING + ("Equity in earnings of affiliates", "Gain (loss) on dispositions", "Other income",
                          "-Interest and debt expense", "-Foreign currency transaction (gain) loss",
                          "-Other expenses", "-Income (loss) before income taxes"),),
    ),
    (93410, "0000093410-26-000078"): Profile(
        "Consolidated Statement of Income", "R3.htm", 1_000_000,
        {"sales": "Total Revenues and Other Income", "net": "Net Income (Loss) Attributable to Chevron Corporation"},
        {"sales": (CVX_REVENUE,), "ebit": CVX_OPERATING},
        (
            (CVX_REVENUE, "Income (loss) from equity affiliates", "Other income (loss)", "-Total Revenues and Other Income"),
            CVX_OPERATING + ("Income (loss) from equity affiliates", "Other income (loss)", "-Interest and debt expense",
                             "-Other components of net periodic benefit costs", "-Income (Loss) Before Income Tax Expense"),
        ), revised_sales=True,
    ),
    (1551182, "0001551182-26-000007"): Profile(
        "CONSOLIDATED STATEMENTS OF INCOME", "R3.htm", 1_000_000,
        {"sales": "Net sales", "pretax": "Income before income taxes"},
        {"ebit": ETN_OPERATING},
        (ETN_OPERATING + ("-Interest expense - net", "-Other expense (income) - net", "-Income before income taxes"),),
        tolerance=1_000_000,
    ),
    (860730, "0001193125-26-044769"): Profile(
        "Consolidated Income Statements", "R2.htm", 1_000_000,
        {"sales": "Revenues", "pretax": "Income before income taxes"},
        {"ebit": HCA_OPERATING},
        (HCA_OPERATING + ("-Equity in earnings of affiliates", "-Interest expense", "-Losses (gains) on sales of facilities",
                          "-Income before income taxes"),),
    ),
    (319201, "0000319201-26-000027"): Profile(
        "Consolidated Statements of Operations", "R5.htm", 1_000,
        {"sales": "Total revenues", "pretax": "Income before income taxes"},
        {"ebit": KLAC_OPERATING},
        (KLAC_OPERATING + ("-Interest expense", "-Other expense (income), net", "-Income before income taxes"),),
    ),
    (59478, "0000059478-26-000013"): Profile(
        "Consolidated Statements of Operations", "R3.htm", 1_000_000,
        {"sales": "Revenue", "pretax": "Income before income taxes"},
        {"ebit": LLY_OPERATING},
        (LLY_OPERATING + ("-Other-net, (income) expense", "-Income before income taxes"),),
        tolerance=1_000_000,
    ),
    (1164727, "0001164727-26-000010"): Profile(
        "CONSOLIDATED STATEMENTS OF OPERATIONS", "R3.htm", 1_000_000,
        {"sales": "Sales (Note 5)", "pretax": NEM_PRETAX},
        {"ebit": NEM_OPERATING},
        (NEM_OPERATING + ("Total other income (expense)", "-" + NEM_PRETAX),),
    ),
    (1534701, "0001534701-26-000006"): Profile(
        "Consolidated Statement of Income", "R3.htm", 1_000_000,
        {"sales": "Sales and other operating revenues", "net_parent": "Net Income Attributable to Phillips 66"},
        {"ebit": PSX_OPERATING},
        (PSX_OPERATING + ("Equity in earnings of affiliates", "Net gain on dispositions", "Other income",
                          "-Interest and debt expense", "-Foreign currency transaction (gains) losses", "-Income before income taxes"),),
    ),
    (1306965, "0001628280-26-017024"): Profile(
        "CONSOLIDATED STATEMENT OF INCOME", "R3.htm", 1_000_000,
        {"sales": "Revenue", "pretax": "Income before taxation"},
        {"ebit": SHEL_OPERATING},
        (SHEL_OPERATING + ("Share of profit of joint ventures and associates", "Interest and other income",
                           "-Interest expense", "-Income before taxation"),),
    ),
    (109198, "0000109198-26-000008"): Profile(
        "Consolidated Statements of Income", "R3.htm", 1_000_000,
        {"sales": "Net sales", "pretax": "Income before income taxes"},
        {"ebit": TJX_OPERATING},
        (TJX_OPERATING + ("-Interest (income) expense, net", "-Income before income taxes"),),
    ),
    (879764, "0001104659-26-035876"): Profile(
        "CONSOLIDATED STATEMENT OF INCOME", "R2.htm", 1_000_000,
        {"net": "TotalEnergies share"},
        {"sales": ("Revenues from sales",), "sales_before_excise": ("Sales",),
         "excise_taxes_on_sales": ("-Excise taxes",), "ebit": TTE_OPERATING},
        (
            ("Sales", "Excise taxes", "-Revenues from sales"),
            ("Financial interest on debt", "Financial income and expense from cash & cash equivalents", "-Cost of net debt"),
            TTE_OPERATING + ("Cost of net debt", "Other financial income", "Other financial expense",
                             "Net income (loss) from equity affiliates", "Income taxes", "-CONSOLIDATED NET INCOME"),
            ("CONSOLIDATED NET INCOME", "-Non-controlling interests", "-TotalEnergies share"),
        ), revised_sales=True,
    ),
    (34088, "0000034088-26-000045"): Profile(
        "Consolidated Statement Of Income", "R3.htm", 1_000_000,
        {"sales": "Revenues", "pretax": "Income (loss) before income taxes"},
        {"sales": (XOM_SALES,), "ebit": XOM_OPERATING},
        (
            (XOM_SALES, XOM_AFFILIATES, XOM_OTHER, "-Revenues"),
            XOM_OPERATING + (XOM_AFFILIATES, XOM_OTHER, "-Interest expense",
                             "-Non-service pension and postretirement benefit expense", "-Income (loss) before income taxes"),
        ), revised_sales=True,
    ),
    (1114448, "0001114448-26-000004"): Profile(
        "Consolidated income statements", "R2.htm", 1_000_000,
        {"ebit": "Operating income from continuing operations", "net": "Shareholders of Novartis AG"},
        {"sales": ("Net sales from continuing operations",), "other_revenues": ("Other revenues",)},
        (("Net sales from continuing operations", "Other revenues", "Cost of goods sold",
          "-Gross profit from continuing operations"),),
    ),
    (1121404, "0001628280-26-008403"): Profile(
        "Consolidated income statements", "R4.htm", 1_000_000,
        {"ebit": "Operating income", "net": "Net income attributable to equity holders of Sanofi"},
        {"sales": ("Net sales",), "other_revenues": ("Other revenues",)},
        (("Net sales", "Other revenues", "Cost of sales", "-Gross profit"),),
    ),
}

# These accessions require a different source scope before they can supply a
# consolidated operating-profit input. Keep that distinction visible.
REVIEWED_GAPS = {
    (8670, "0000008670-26-000030"): "Operating and corporate financing need to be separated. ADP earns interest on client funds and includes related borrowing expense in its adjusted measure.",
    (2809, "0001104659-26-032153"): "The income statement groups mining costs with derivatives, currency effects and other expenses. Their operating scope needs a note-level reconciliation.",
    (14272, "0000014272-26-000004"): "The other-income and expense line includes financing, litigation and other items. It needs a note-level reconciliation.",
    (315189, "0001104659-25-122321"): "Deere reports segment operating profit and consolidates a captive finance business. The equipment and finance scopes need separate reconciliations.",
    (40545, "0000040545-26-000008"): "GE reports adjusted aerospace operating profit and consolidates insurance results. Aerospace and insurance need separate reconciliations.",
    (51143, "0000051143-26-000010"): "IBM consolidates its financing segment and publishes a non-GAAP operating measure. Consolidated operating and financing items need separate reconciliations.",
    (200406, "0000200406-26-000016"): "The other-income and expense line mixes operating and nonoperating items. The note disclosures need to be reconciled before deriving an operating subtotal.",
    (310158, "0000310158-26-000063"): "The other-income and expense line includes financing, investment and commercialization-related items. It needs a note-level reconciliation.",
    (78003, "0000078003-26-000026"): "Other deductions include intangible asset impairments and financing expenses. The operating items need a note-level reconciliation.",
}


def gap_reason(cik, report):
    return REVIEWED_GAPS.get((cik, report["accession"]))


RECURRING = recurring_annual_rules(PROFILES)


def profile_for(cik, report):
    return PROFILES.get(annual_rule_key(cik, report, PROFILES, RECURRING))


def supported(cik, report):
    return profile_for(cik, report) is not None


def enrich_operating(cache, cik, report, statement):
    profile = profile_for(cik, report)
    pinned = (cik, report["accession"]) in PROFILES
    table, index, receipt, evidence = annual_table(cache, cik, report, statement, "income", profile.title,
                                                    profile.table if pinned else None, profile.scale if pinned else None)
    scale = table["money_scale"]
    groups = {"": []}
    group = ""
    for row in table["rows"]:
        if row[1] is None:
            group = row[0]
            if group in groups:
                raise ValueError("Duplicate rendered income statement section")
            groups[group] = []
        else:
            groups[group].append(row)

    def get_line(term):
        sign = -1 if term.startswith("-") else 1
        address = term[1:] if sign == -1 else term
        member, _, label = address.rpartition("::")
        rows = [r for r in groups.get(member, ()) if r[0] == label and r[index] is not None]
        unique = {(r[1], r[index]) for r in rows}
        if len(unique) != 1:
            raise ValueError(f"Missing or ambiguous income statement row {address}")
        tag, value = unique.pop()
        return {"line": address, "tag": tag, "value": scaled(value, scale), "sign": sign}

    def sum_terms(parts):
        return sum(p["sign"] * p["value"] for p in parts)

    facts = statement["facts"].copy()
    for key, term in profile.anchors.items():
        line = get_line(term)
        if facts.get(key, {}).get("value") != line["value"]:
            raise ValueError(f"Annual income statement disagrees with SEC Company Facts on {key}")
    for line, tag in profile.line_tags:
        if get_line(line)["tag"] != tag:
            raise ValueError(f"Filed concept changed for {line}")
    for equation in profile.checks:
        if abs(sum_terms([get_line(t) for t in equation])) > profile.tolerance:
            raise ValueError("Filed operating-income components do not reconcile")
    if profile.revised_sales and "sales" in profile.anchors:
        facts["sales_and_other_income"] = facts["sales"]
    for key, terms in profile.fields.items():
        parts = [get_line(term) for term in terms]
        value = sum_terms(parts)
        if key == "ebit" and "ebit" in facts and abs(facts["ebit"]["value"] - value) > profile.tolerance:
            raise ValueError("Operating-income derivation disagrees with the filed subtotal")
        facts[key] = {
            "value": value, "tag": OPERATING_TAG if key == "ebit" else parts[0]["tag"],
            "unit": statement["currency"], "start": statement["start"], "form": report["form"],
            "filed": report["filed"], "accession": report["accession"], "url": report["url"], "source": ENDPOINT,
            "sha256": receipt["sha256"], "components": parts, **evidence,
            "locator": "Reconciled from filed income statement lines" if key == "ebit" else parts[0]["line"],
        }
    result = {**statement, "facts": facts, "income_profiled": True}
    if profile.revised_sales:
        result["sales_basis"] = SALES_BASIS
    return result
