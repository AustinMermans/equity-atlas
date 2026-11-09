"""Recover reviewed annual cash investment lines with filing-level provenance."""

import re

from .facts import annual_rule_key, exact_sec_amount, recurring_annual_rules
from .fetch import SEC
from .issuer_20f import column, pdf_pages
from .rendered_filing import ENDPOINT, amount, annual_table, scaled, table_belongs_to_filing

PPE_OTHER = "us-gaap:PaymentsToAcquireOtherPropertyPlantAndEquipment"
PPE = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
INTANGIBLES = "us-gaap:PaymentsToAcquireIntangibleAssets"
IFRS_PPE = "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
IFRS_INTANGIBLES = "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"
COMBINED = "ifrs-full:PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets"
TURNAROUND = "us-gaap:PaymentsForCapitalImprovements"
CAPEX_TAG = "derived:CashCapitalInvestment"
APPLOVIN = (1751008, "0001751008-26-000010")
APP_INTANGIBLE_FIELDS = {
    "capex_intangibles_discontinued": ("disclosed:DiscontinuedIntangiblePurchases", "p. 65 · Note 3 · Acquisition of intangible assets by discontinued operations"),
    "capex_intangibles_continuing": ("derived:ContinuingIntangiblePurchases", "Consolidated intangible purchases less purchases by discontinued operations"),
}
APP_INVESTMENT_GAP = ("Cash investment includes the discontinued Apps business. The 10-K separates intangible purchases "
                      "by operation and reports PP&E cash purchases on a consolidated basis.")
ADDITIONAL_FIELDS = {"capex_mixed_outflow", "capex_financing_payment", "capex_reported_total", *APP_INTANGIBLE_FIELDS}
FINANCING_TAGS = {
    "arm:RepaymentsOfIntangibleAssetObligation",
    "intc:PaymentsToAcquirePropertyPlantAndEquipmentFinancingActivities",
    "nvda:PaymentsForFinancedPropertyPlantAndEquipmentAndIntangibleAssetsFinancingActivities",
}
INVESTING_TOTALS = {
    "us-gaap:NetCashProvidedByUsedInInvestingActivities",
    "ifrs-full:CashFlowsFromUsedInInvestingActivities",
}
FINANCING_TOTALS = {
    "us-gaap:NetCashProvidedByUsedInFinancingActivities",
    "ifrs-full:CashFlowsFromUsedInFinancingActivities",
}

# These are face cash-flow amounts unless a filing exposes its separate PP&E
# outflow in the FCF reconciliation. Reviewed rules revalidate the current filing.
DIRECT = {
    (937966, "0001628280-26-011378"): (
        (PPE, "Purchase of property, plant and equipment"), (INTANGIBLES, "Purchase of intangible assets"),
    ),
    (895728, "0001193125-26-049810"): (
        (PPE, "Capital expenditures"), (INTANGIBLES, "Additions to intangible assets"),
    ),
    (8670, "0000008670-26-000030"): (
        (PPE_OTHER, "Capital expenditures"), (INTANGIBLES, "Additions to intangibles"),
    ),
    APPLOVIN: ((INTANGIBLES, "Purchase of intangible assets"),),
    (59478, "0000059478-26-000013"): ((PPE_OTHER, "Purchases of property and equipment"),),
    (863064, "0001628280-26-009531"): ((COMBINED, "Purchases of property, plant and equipment and intangible assets"),),
    (1000184, "0001104659-26-020058"): ((COMBINED, "Purchase of intangible assets and property, plant, and equipment"),),
    (1121404, "0001628280-26-008403"): ((COMBINED, "Acquisitions of property, plant and equipment and intangible assets from continuing operations"),),
    (732712, "0000732712-26-000007"): (
        ("us-gaap:PaymentsToAcquireOtherProductiveAssets", "Capital expenditures (including capitalized software)"),
    ),
}

# Exact purchases anchored to the consolidated investing or financing section.
SECTION_PROFILES = {
    (1108329, "0001193125-23-124228"): (  # 0857.HK
        "Consolidated Statements of Cash Flows", "R4.htm", 1_000_000, (
            (IFRS_PPE, "Capital expenditures"),
        ),
    ),
    (1117795, "0001193125-22-125601"): (  # 0941.HK
        "Consolidated Statements of Cash Flows", "R5.htm", 1_000_000, (
            (IFRS_PPE, "Payment for property, plant and equipment"),
            (IFRS_INTANGIBLES, "Payment for other intangible assets"),
        ),
    ),
    (796343, "0000796343-26-000003"): (  # ADBE
        "Consolidated Statements of Cash Flows", "R8.htm", 1_000_000, (
            (PPE, "Purchases of property and equipment"),
        ),
    ),
    (1973239, "0001973239-26-000097"): (  # ARM
        "Consolidated Statements of Cash Flows", "R9.htm", 1_000_000, (
            (PPE, "Purchases of property and equipment"),
            (INTANGIBLES, "Purchases of intangible assets"),
        ),
    ),
    (901832, "0001104659-26-019130"): (  # AZN
        "Consolidated Statement of Cash Flows", "R7.htm", 1_000_000, (
            (IFRS_PPE, "Purchase of property, plant and equipment"),
            (IFRS_INTANGIBLES, "Purchase of intangible assets"),
        ),
    ),
    (1303523, "0001303523-26-000017"): (  # BTI
        "Group Cash Flow Statement", "R9.htm", 1_000_000, (
            (IFRS_PPE, "Purchases of property, plant and equipment"),
            (IFRS_INTANGIBLES, "Purchases of intangibles"),
        ),
    ),
    (18230, "0000018230-26-000008"): (  # CAT
        "Consolidated Statement of Cash Flow for the Years Ended December 31", "R9.htm", 1_000_000, (
            (PPE, "Capital expenditures - excluding equipment leased to others"),
            ("us-gaap:PaymentsToAcquireEquipmentOnLease", "Expenditures for equipment leased to others"),
        ),
    ),
    (1652044, "0001652044-26-000018"): (  # GOOG
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R10.htm", 1_000_000, (
            (PPE, "Purchases of property and equipment"),
        ),
    ),
    (1131399, "0001131399-26-000004"): (  # GSK
        "Consolidated cash flow statement", "R7.htm", 1_000_000, (
            (IFRS_PPE, "Purchase of property, plant and equipment"),
            (IFRS_INTANGIBLES, "Purchase of intangible assets"),
        ),
    ),
    (51143, "0000051143-26-000010"): (  # IBM
        "CONSOLIDATED STATEMENT OF CASH FLOWS", "R7.htm", 1_000_000, (
            (PPE, "Payments for property, plant and equipment"),
            ("ibm:PaymentsToAcquireAndDevelopSoftware", "Investment in software"),
        ),
    ),
    (50863, "0000050863-26-000011"): (  # INTC
        "Consolidated Statements of Cash Flows", "R7.htm", 1_000_000, (
            (PPE, "Additions to property, plant and equipment"),
            ("intc:PaymentsToAcquirePropertyPlantAndEquipmentFinancingActivities", "Additions to property, plant and equipment"),
        ),
    ),
    (1035267, "0001035267-26-000010"): (  # ISRG
        "Consolidated Statements Of Cash Flows", "R9.htm", 1_000_000, (
            ("us-gaap:PaymentsToAcquireProductiveAssets", "Purchases of property, plant, and equipment"),
        ),
    ),
    (1326801, "0001628280-26-003942"): (  # META
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R9.htm", 1_000_000, (
            (PPE, "Purchases of property and equipment"),
        ),
    ),
    (1682852, "0001682852-26-000033"): (  # MRNA
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R8.htm", 1_000_000, (
            (PPE, "Purchases of property, plant and equipment"),
            (INTANGIBLES, "Purchase of intangible asset"),
        ),
    ),
    (789019, "0001193125-26-323660"): (  # MSFT
        "CASH FLOWS STATEMENTS", "R6.htm", 1_000_000, (
            (PPE, "Additions to property and equipment"),
        ),
    ),
    (1373715, "0001373715-26-000007"): (  # NOW
        "Consolidated Statements of Cash Flows", "R8.htm", 1_000_000, (
            (PPE, "Purchases of property and equipment"),
            (INTANGIBLES, "Purchases of other intangibles"),
        ),
    ),
    (1045810, "0001045810-26-000021"): (  # NVDA
        "Consolidated Statements of Cash Flows", "R9.htm", 1_000_000, (
            ("us-gaap:PaymentsToAcquireProductiveAssets", "Purchases related to property and equipment and intangible assets"),
        ),
    ),
    (1114448, "0001114448-26-000004"): (  # NVS
        "Consolidated cash flow statements", "R6.htm", 1_000_000, (
            (IFRS_PPE, "Purchases of property, plant and equipment"),
            (IFRS_INTANGIBLES, "Purchases of intangible assets"),
        ),
    ),
    (77476, "0000077476-26-000007"): (  # PEP
        "Consolidated Statement of Cash Flows", "R5.htm", 1_000_000, (
            ("us-gaap:PaymentsToAcquireProductiveAssets", "Capital spending"),
        ),
    ),
    (872589, "0000872589-26-000008"): (  # REGN
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R7.htm", 1_000_000, (
            ("us-gaap:PaymentsToAcquireProductiveAssets", "Capital expenditures"),
            ("regn:PaymentsToAcquireIntangibleAssets1", "Payments for intangible assets"),
        ),
    ),
    (1640147, "0001640147-26-000008"): (  # SNOW
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R9.htm", 1_000, (
            (PPE, "Purchases of property and equipment"),
            (INTANGIBLES, "Purchases of intangible assets"),
        ),
    ),
    (1283699, "0001283699-26-000010"): (  # TMUS
        "Consolidated Statements of Cash Flows", "R7.htm", 1_000_000, (
            (PPE, "Purchases of property and equipment, including capitalized interest"),
            (INTANGIBLES, "Purchases of spectrum licenses and other intangible assets, including deposits"),
        ),
    ),
    (217410, "0000217410-26-000007"): (  # UL
        "Consolidated cash flow statement", "R9.htm", 1_000_000, (
            (IFRS_PPE, "Purchase of property, plant and equipment"),
            (IFRS_INTANGIBLES, "Purchase of intangible assets"),
        ),
    ),
}

# Separately reported outflows with a scope outside cash capital investment.
ADDITIONAL_OUTFLOWS = {
    (1108329, "0001193125-23-124228"): {
        "capex_mixed_outflow": ("ptr:PurchaseOfIntangibleAssetsAndOtherLongtermAssetsClassifiedAsInvestingActivities", "Acquisition of intangible assets and other non-current assets"),
    },
    (796343, "0000796343-26-000003"): {
        "capex_mixed_outflow": ("us-gaap:PaymentsToAcquireLongtermInvestments", "Purchases of long-term investments, intangibles and other assets"),
    },
    (1973239, "0001973239-26-000097"): {
        "capex_financing_payment": ("arm:RepaymentsOfIntangibleAssetObligation", "Payments of intangible asset obligations"),
    },
    (1652044, "0001652044-26-000018"): {
        "capex_mixed_outflow": ("goog:AcquisitionsNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets", "Acquisitions, net of cash acquired, and purchases of intangible assets"),
    },
    (1035267, "0001035267-26-000010"): {
        "capex_mixed_outflow": ("us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired", "Acquisition of businesses, net of cash, and intellectual property and other investing activities"),
    },
    (1326801, "0001628280-26-003942"): {
        "capex_mixed_outflow": ("meta:PaymentsToAcquireBusinessesNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets", "Acquisitions of businesses and intangible assets"),
    },
    (789019, "0001193125-26-323660"): {
        "capex_mixed_outflow": ("msft:AcquisitionsNetOfCashAcquiredAndPurchasesOfIntangibleAndOtherAssets", "Acquisition of companies, net of cash acquired and divestitures, and purchases of intangible and other assets"),
    },
    (1045810, "0001045810-26-000021"): {
        "capex_financing_payment": ("nvda:PaymentsForFinancedPropertyPlantAndEquipmentAndIntangibleAssetsFinancingActivities", "Principal payments on property and equipment and intangible assets"),
    },
    (77476, "0000077476-26-000007"): {
        "capex_mixed_outflow": ("us-gaap:PaymentsToAcquireBusinessesAndInterestInAffiliates", "Acquisitions, net of cash acquired, investments in noncontrolled affiliates and purchases of intangible and other assets"),
    },
}

# Report title, SEC rendered table, scale, and reviewed concept/label pairs.
RENDERED = {
    **SECTION_PROFILES,
    (353278, "0000353278-26-000012"): (
        "Cash flow statement", "R5.htm", 1_000_000,
        ((IFRS_PPE, "Purchase of property, plant and equipment"), (IFRS_INTANGIBLES, "Purchase of intangible assets")),
    ),
    (1577552, "0001193125-26-231755"): (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R8.htm", 1_000_000,
        (("baba:PaymentsToAcquireLandUseRightsPropertyAndEquipment", "Land use rights, property and equipment"),
         (INTANGIBLES, "Intangible assets")),
    ),
    (313807, "0000313807-26-000006"): (
        "Group cash flow statement", "R6.htm", 1_000_000,
        ((COMBINED, "Expenditure on property, plant and equipment, intangible and other assets"),),
    ),
    (1017413, "0001017413-26-000018"): (
        "Consolidated Statements of Cash Flows", "R8.htm", 1_000_000,
        (("cnq:CashFlowsFromUsedInPropertyPlantandEquipmentClassifiedAsInvestingActivities", "Net expenditures on property, plant and equipment"),
         ("ifrs-full:CashFlowsFromUsedInExplorationForAndEvaluationOfMineralResourcesClassifiedAsInvestingActivities",
          "Net expenditures on exploration and evaluation assets")),
    ),
    (1163165, "0001163165-26-000009"): (
        "Consolidated Statement of Cash Flows", "R7.htm", 1,
        (("cop:PaymentToAcquireProductiveAssetsAndInvestments", "Capital expenditures and investments"),),
    ),
    (753308, "0000753308-26-000015"): (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R8.htm", 1_000_000,
        (("nee:CapitalExpendituresOfFPL", "Capital expenditures of FPL"),
         ("nee:IndependentPowerInvestments", "Independent power and other investments of NEER"),
         ("us-gaap:PaymentsForProceedsFromNuclearFuel", "Nuclear fuel purchases"),
         ("nee:OtherCapitalExpenditures", "Other capital expenditures")),
    ),
    (1737806, "0001104659-26-050727"): (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R7.htm", 1_000,
        (("pdd:PaymentsToAcquirePropertyEquipmentAndSoftwareAndIntangibleAssets",
          "Purchase of property, equipment and software and intangible assets"),),
    ),
    (1534701, "0001534701-26-000006"): (
        "Consolidated Statement of Cash Flows", "R7.htm", 1_000_000,
        (("psx:CapitalExpendituresAndInvestments", "Capital expenditures and investments"),),
    ),
    (1306965, "0001628280-26-017024"): (
        "CONSOLIDATED STATEMENT OF CASH FLOWS", "R7.htm", 1_000_000,
        (("ifrs-full:PurchaseOfOtherLongtermAssetsClassifiedAsInvestingActivities", "Capital expenditure"),),
    ),
    (879764, "0001104659-26-035876"): (
        "CONSOLIDATED STATEMENT OF CASH FLOW", "R5.htm", 1_000_000,
        (("tot:PurchaseOfPropertyPlantAndEquipmentAndIntangibleAssets",
          "Intangible assets and property, plant and equipment additions"),),
    ),
    (1035002, "0001628280-26-011499"): (
        "Consolidated Statements of Cash Flows", "R9.htm", 1_000_000, (),
    ),
}
PDFS = {
    (1559720, "0001559720-26-000004"): (
        "https://d18rn0p25nwr6d.cloudfront.net/CIK-0001559720/52fc9020-faa3-4ed3-b6e3-9a982ecdda93.pdf",
        "38", 1_000_000, 2, 1, "Purchases of property and equipment", "FCF", "in millions",
    ),
    APPLOVIN: (
        "https://s21.q4cdn.com/165405286/files/doc_financials/2025/ar/d6d59334-570b-453f-8c55-30d0bda96a8e.pdf",
        "39", 1_000, 3, 0, "Purchase of property and equipment", "Free Cash Flow", "in thousands",
    ),
}
REPORTED_TOTALS = {
    313807: ("ifrs-full:OutflowsOfCashFromInvestingActivities", "Total cash capital expenditure"),
    1306965: ("shel:CashOutflowForTotalCashCapitalExpenditure", "Cash capital expenditure"),
}
VALERO_MEMBERS = (
    ("Excluding Variable Interest Entities (VIEs) [Member]", ((PPE, "Capital expenditures"), (TURNAROUND, "Deferred turnaround and catalyst cost expenditures"))),
    ("Diamond Green Diesel Holdings LLC (DGD) [Member]", ((PPE, "Capital expenditures"), (TURNAROUND, "Deferred turnaround and catalyst cost expenditures"))),
    ("Other VIEs [Member]", ((PPE, "Capital expenditures"),)),
)


PINNED = DIRECT.keys() | RENDERED.keys() | PDFS.keys()
RECURRING = recurring_annual_rules(PINNED - PDFS.keys())


def rule_key(cik, report):
    return annual_rule_key(cik, report, PINNED, RECURRING)


def supported(cik, report):
    return rule_key(cik, report) in PINNED


def section(table, label):
    rows = table["rows"]
    matches = [i for i, row in enumerate(rows) if row[0] == label and row[1] is None]
    if len(matches) != 1:
        raise ValueError(f"Missing or ambiguous cash-flow section {label}")
    index = matches[0]
    stop = next((i for i in range(index+1, len(rows)) if rows[i][1] is None), len(rows))
    return {**table, "rows": rows[index+1:stop]}, {**table, "rows": rows[:index]}


def cash_activity(table, column, cfo_tag, financing):
    """Return only the rows between the consolidated cash-flow subtotals."""
    rows = table["rows"]
    dimension = next((i for i, row in enumerate(rows) if row[1] is None), len(rows))
    rows = rows[:dimension]

    def subtotal(tags):
        indices = [i for i, row in enumerate(rows) if row[1] in tags and type(row[column]) in (int, float)]
        if len(indices) != 1:
            raise ValueError("Missing or ambiguous consolidated cash-flow subtotal")
        return indices[0]

    operating = subtotal({cfo_tag})
    investing = subtotal(INVESTING_TOTALS)
    financing_end = subtotal(FINANCING_TOTALS) if financing else len(rows)
    if not operating < investing < financing_end:
        raise ValueError("Consolidated cash-flow sections are out of order")
    return ({**table, "rows": rows[operating + 1:investing]},
            {**table, "rows": rows[investing + 1:financing_end]})


def activity_label(key, tag):
    if key not in SECTION_PROFILES:
        return ""
    return "Financing activities · " if tag in FINANCING_TAGS else "Investing activities · "


def rendered_components(cache, obj, key, statement, report, component):
    title, filename, scale, concepts = RENDERED[key]
    cik = key[0]
    pinned = key == (cik, report["accession"])
    table, index, receipt, evidence = annual_table(cache, cik, report, statement, "cash_flow", title,
                                                    filename if pinned else None, scale if pinned else None)
    scale = table["money_scale"]
    if cik == 753308:
        _, consolidated = section(table, "FPL")
    elif cik == 1035002:
        _, consolidated = section(table, VALERO_MEMBERS[0][0])
    else:
        consolidated = table

    cfo = statement["facts"]["cfo"]
    if scaled(amount(consolidated, cfo["tag"], index)[0], scale) != cfo["value"]:
        raise ValueError("Cash-flow table operating cash disagrees with the exact SEC statement")

    def extract(part, tag, label, scope="", *, dimensioned=False):
        value = -scaled(amount(part, tag, index, label)[0], scale)
        direct = exact_sec_amount(obj, statement, report, tag) if not dimensioned else None
        if direct is not None and abs(direct) != value:
            raise ValueError(f"Cash-flow table and SEC Company Facts disagree for {label}")
        return component(tag, value, title + " · " + scope + label, receipt, **evidence)

    extras = ADDITIONAL_OUTFLOWS.get(key, {})
    investing, financing = consolidated, None
    if key in SECTION_PROFILES:
        needs_financing = any(tag in FINANCING_TAGS for tag, _ in (*concepts, *extras.values()))
        investing, financing = cash_activity(consolidated, index, cfo["tag"], needs_financing)
    if cik == 1283699:
        # The footnote in this face line contains three years of interest amounts.
        investing = {**investing, "rows": [
            [row[0].split(" of $", 1)[0], *row[1:]]
            if row[1] == PPE and "including capitalized interest of $" in row[0] else row
            for row in investing["rows"]
        ]}

    def extract_cash(tag, label):
        return extract(financing if tag in FINANCING_TAGS else investing, tag, label, activity_label(key, tag))

    parts = [extract_cash(tag, label) for tag, label in concepts]
    reported = {field: extract_cash(tag, label) for field, (tag, label) in extras.items()}
    if cik == 1035002:
        for member, lines in VALERO_MEMBERS:
            group, _ = section(table, member)
            parts.extend(extract(group, tag, label, member + " · ", dimensioned=True) for tag, label in lines)
        # The three members partition PP&E and turnaround spending. Reconcile
        # their outflows to consolidated investing cash, excluding the other
        # investing lines shown before the total.
        other = sum(scaled(amount(consolidated, tag, index)[0], scale) for tag in (
            "us-gaap:PaymentsToAcquireAvailableForSaleSecuritiesDebt",
            "us-gaap:ProceedsFromSaleAndMaturityOfAvailableForSaleSecurities",
            "us-gaap:PaymentsToAcquireInterestInJointVenture",
            "us-gaap:PaymentsForProceedsFromOtherInvestingActivities",
        ))
        investing_total = scaled(amount(consolidated, "us-gaap:NetCashProvidedByUsedInInvestingActivities", index)[0], scale)
        if other - sum(part["value"] for part in parts) != investing_total:
            raise ValueError("Valero member cash investments do not reconcile")
    if cik in REPORTED_TOTALS:
        total = extract(consolidated, *REPORTED_TOTALS[cik])
        reported["capex_reported_total"] = total
        if total["value"] < sum(part["value"] for part in parts):
            raise ValueError("Reported total capital expenditure is below its productive-asset component")
    return parts, reported


def pdf_component(cache, key, statement, component):
    url, footer, scale, years, index, label, fcf_label, scale_label = PDFS[key]
    raw, receipt = cache.get(url, 8760)
    if receipt["url"] != url or statement["currency"] != "USD":
        raise ValueError("FCF reconciliation source or currency mismatch")
    pages = pdf_pages(raw)
    matches = [p for p in pages if p.rstrip().endswith(footer) and label in p and fcf_label in p
               and scale_label in p and statement["end"][:4] in p and "reconciliation" in p.lower()]
    if len(matches) != 1:
        raise ValueError("Missing expected FCF reconciliation table")
    table = matches[0]
    cfo = column(table, "Net cash provided by operating activities", years, column_index=index)
    capex = -column(table, label, years, column_index=index)
    fcf = column(table, fcf_label, years, column_index=index)
    finance_lease = -column(table, "Principal payments of finance leases", years, column_index=index) if key == APPLOVIN else 0
    if scaled(cfo, scale) != statement["facts"]["cfo"]["value"] or cfo - capex - finance_lease != fcf:
        raise ValueError("FCF reconciliation does not tie to filed operating cash flow")
    ppe = component("disclosed:CashPurchasesOfPropertyAndEquipment", scaled(capex, scale),
                    f"p. {footer} · FCF reconciliation · {label}", receipt)
    if key != APPLOVIN:
        return ppe, {}
    notes = [p for p in pages if p.rstrip().endswith("65") and "capital expenditures related to discontinued operations" in p
             and "consolidated statements of cash flows" in p and "(in thousands)" in p
             and re.search(r"Year Ended December 31,\s+" + statement["end"][:4] + r"\s+", p)]
    if len(notes) != 1:
        raise ValueError("Missing filed AppLovin discontinued operations table")
    value = scaled(column(notes[0], "Acquisition of intangible assets", years), scale)
    tag, locator = APP_INTANGIBLE_FIELDS["capex_intangibles_discontinued"]
    return ppe, {"capex_intangibles_discontinued": component(tag, value, locator, receipt)}


def enrich_capex(cache, obj, meta, cik, report, statement):
    key = rule_key(cik, report)
    if (not supported(cik, report) or statement["period_kind"] != "annual" or
            (statement["filing"], statement["end"]) != (report["accession"], report["end"])):
        raise ValueError("Cash investment profile must match the selected annual statement")

    def component(tag, value, label, receipt, **evidence):
        if value < 0:
            raise ValueError(f"Cash investment is not an outflow for {label}")
        return {
            "value": value, "tag": tag, "unit": statement["currency"], "start": statement["start"],
            "form": report["form"], "filed": report["filed"], "accession": report["accession"], "url": report["url"],
            "source": receipt["url"], "sha256": receipt["sha256"], "locator": label, **evidence,
        }

    parts, reported = [], {}
    if key in PDFS:
        ppe, reported = pdf_component(cache, key, statement, component)
        parts.append(ppe)
    if key in RENDERED:
        parts, reported = rendered_components(cache, obj, key, statement, report, component)
    for tag, label in DIRECT.get(key, ()):
        value = exact_sec_amount(obj, statement, report, tag)
        if value is None:
            raise ValueError(f"Missing exact SEC Company Facts cash outflow for {label}")
        parts.append(component(tag, value, "Consolidated cash flow · " + label, meta))

    total = sum(p["value"] for p in parts)
    existing = statement["facts"].get("capex")
    if existing and existing["value"] not in {total, *(p["value"] for p in parts)}:
        raise ValueError("Cash investment components disagree with existing filed capex")
    capex = {**parts[0], "value": total, "tag": CAPEX_TAG, "components": parts}
    if len(parts) > 1:
        capex["locator"] = "Sum of " + str(len(parts)) + " reviewed cash investment lines"
    if key == APPLOVIN:
        discontinued = reported["capex_intangibles_discontinued"]
        tag, locator = APP_INTANGIBLE_FIELDS["capex_intangibles_continuing"]
        intangible, = (part["value"] for part in parts if part["tag"] == INTANGIBLES)
        value = intangible - discontinued["value"]
        reported["capex_intangibles_continuing"] = component(
            tag, value, locator, {"url": discontinued["source"], "sha256": discontinued["sha256"]},
        )
        statement = {**statement, "capital_investment_gap": APP_INVESTMENT_GAP}
    facts = {**statement["facts"], "capex": capex, **reported}
    return {**statement, "facts": facts}


def required_additional_fields(cik, report):
    fields = set(ADDITIONAL_OUTFLOWS.get(rule_key(cik, report), {}))
    if cik in REPORTED_TOTALS:
        fields.add("capex_reported_total")
    if rule_key(cik, report) == APPLOVIN:
        fields.update(APP_INTANGIBLE_FIELDS)
    return fields


def valid_capex_components(parts, cik, report, field):
    key = rule_key(cik, report)
    expected = []
    pinned_filename = None
    if field == "capex" and key in PDFS:
        source, footer, _, _, _, label, _, _ = PDFS[key]
        expected.append((source, "disclosed:CashPurchasesOfPropertyAndEquipment",
                         f"p. {footer} · FCF reconciliation · {label}"))
    if key == APPLOVIN and field in APP_INTANGIBLE_FIELDS:
        tag, label = APP_INTANGIBLE_FIELDS[field]
        expected.append((PDFS[key][0], tag, label))
    if key in RENDERED:
        title, filename, _, lines = RENDERED[key]
        pinned_filename = filename if key == (cik, report["accession"]) else None
        if field == "capex":
            expected.extend((ENDPOINT, tag, f"{title} · {activity_label(key, tag)}{label}") for tag, label in lines)
            if cik == 1035002:
                expected.extend((ENDPOINT, tag, f"{title} · {member} · {label}")
                                for member, lines in VALERO_MEMBERS for tag, label in lines)
        elif field in ADDITIONAL_OUTFLOWS.get(key, {}):
            tag, label = ADDITIONAL_OUTFLOWS[key][field]
            expected.append((ENDPOINT, tag, f"{title} · {activity_label(key, tag)}{label}"))
        elif field == "capex_reported_total" and cik in REPORTED_TOTALS:
            tag, label = REPORTED_TOTALS[cik]
            expected.append((ENDPOINT, tag, f"{title} · {label}"))
    if field == "capex":
        expected.extend((SEC.format(cik), tag, f"Consolidated cash flow · {label}")
                        for tag, label in DIRECT.get(key, ()))
    return bool(expected) and len(parts) == len(expected) and all(
        (part["source"], part["tag"], part["locator"]) == (source, tag, label) and
        (source != ENDPOINT or (
            table_belongs_to_filing(part.get("table_url"), report, pinned_filename) and
            bool(re.fullmatch(r"[0-9a-f]{16}", part.get("table_sha256_16", "")))
        )) for part, (source, tag, label) in zip(parts, expected)
    )
