"""Normalize annual depreciation and amortization from reviewed filings."""

import re

from .capex import PDFS
from .facts import exact_sec_amount
from .fetch import SEC
from .issuer_20f import column, pdf_pages
from .rendered_filing import ENDPOINT, amount, decode_response, request_bytes, scaled

TAG = "derived:FiledDepreciationAndAmortization"
AIRBNB = (1559720, "0001559720-26-000004")
NOVARTIS = (1114448, "0001114448-26-000004")
VALERO = (1035002, "0001628280-26-011499")
CISCO = (858877, "0000858877-26-000132")
MCDONALDS = (63908, "0000063908-26-000035")
MCKESSON = (927653, "0000927653-26-000069")
NOVARTIS_PDF = "https://www.novartis.com/sites/novartis_com/files/novartis-annual-report-2025.pdf"

# Bind interpretation to the face statement of the exact accession. Tags
# alone cannot distinguish pure D&A from cash-flow adjustments with impairment.
CASH_TABLES = {
    (1108329, "0001193125-23-124228"): (  # 0857.HK
        'Consolidated Statements of Cash Flows', "R4.htm", 1_000_000, {
            "da": (
                ('ptr:DepreciationDepletionAndAmortisationExpense', 'Depreciation, depletion and amortization'),
            ),
        },
    ),
    (1551152, "0001551152-26-000008"): (  # ABBV
        'Consolidated Statements of Cash Flows', "R9.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangible assets'),
            ),
        },
    ),
    (1800, "0001628280-26-010185"): (  # ABT
        'Consolidated Statement of Cash Flows', "R6.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangible assets'),
            ),
        },
    ),
    (1467373, "0001467373-26-000049"): (  # ACN
        'CONSOLIDATED CASH FLOWS STATEMENTS', "R8.htm", 1_000, {
            "da_with_other": (
                ('acn:DepreciationAmortizationAndOther', 'Depreciation, amortization and other'),
            ),
        },
    ),
    (6281, "0000006281-25-000153"): (  # ADI
        'CONSOLIDATED STATEMENTS OF CASH FLOWS', "R10.htm", 1_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangibles'),
            ),
        },
    ),
    (2809, "0001104659-26-032153"): (  # AEM
        'CONSOLIDATED STATEMENTS OF CASH FLOWS', "R8.htm", 1_000, {
            "da": (
                ('ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense', 'Amortization of property, plant and mine development (Note 9)'),
            ),
        },
    ),
    (2488, "0000002488-26-000018"): (  # AMD
        'Consolidated Statements of Cash Flows', "R8.htm", 1_000_000, {
            "da": (
                ('us-gaap:OtherDepreciationAndAmortization', 'Depreciation and amortization'),
                ('us-gaap:AdjustmentForAmortization', 'Amortization'),
            ),
        },
    ),
    (1730168, "0001730168-25-000121"): (  # AVGO
        'Consolidated Statements of Cash Flows', "R7.htm", 1_000_000, {
            "amortization_with_rou": (
                ('avgo:Amortizationofintangibleandrightofuseassets', 'Amortization of intangible and right-of-use assets'),
            ),
        },
    ),
    (901832, "0001104659-26-019130"): (  # AZN
        'Consolidated Statement of Cash Flows', "R7.htm", 1_000_000, {
            "da_with_impairment": (
                ('ifrs-full:AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss', 'Depreciation, amortisation and impairment'),
            ),
        },
    ),
    (1303523, "0001303523-26-000017"): (  # BTI
        'Group Cash Flow Statement', "R9.htm", 1_000_000, {
            "da_with_impairment": (
                ('ifrs-full:AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss', '- depreciation, amortisation and impairment costs'),
            ),
        },
    ),
    (1668717, "0001193125-26-088105"): (  # BUD
        'Consolidated Statement of Cash Flows', "R6.htm", 1_000_000, {
            "da_with_impairment": (
                ('ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense', 'Depreciation, amortization and impairment'),
            ),
        },
    ),
    (1535527, "0001535527-26-000010"): (  # CRWD
        'Consolidated Statements of Cash Flows', "R8.htm", 1_000, {
            "da": (
                ('crwd:DepreciationAndAmortizationExcludingIntangibleAssetsAndDeferredContractAcquisitionCosts', 'Depreciation and amortization'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangible assets'),
            ),
            "amortization_deferred_contract_costs": (
                ('crwd:AmortizationOfDeferredContractAcquisitionCosts', 'Amortization of deferred contract acquisition costs'),
            ),
        },
    ),
    (1690820, "0001690820-26-000009"): (  # CVNA
        'Consolidated Statements of Cash Flows', "R8.htm", 1_000_000, {
            "da": (
                ('cvna:DepreciationAndAmortizationExcludingDebtIssuanceCosts', 'Depreciation and amortization expense'),
            ),
        },
    ),
    (313616, "0000313616-26-000062"): (  # DHR
        'Consolidated Statements of Cash Flows', "R8.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangible assets'),
            ),
        },
    ),
    (40545, "0000040545-26-000008"): (  # GE
        'STATEMENT OF CASH FLOWS', "R6.htm", 1_000_000, {
            "da": (
                ('us-gaap:DepreciationAmortizationAndAccretionNet', 'Depreciation and amortization of property, plant and equipment (Note 6)'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangible assets (Note 7)'),
            ),
        },
    ),
    (1996810, "0001996810-26-000015"): (  # GEV
        'CONSOLIDATED AND COMBINED STATEMENT OF CASH FLOWS', "R6.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation and amortization of property, plant, and equipment (Note 6)'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangible assets (Note 8)'),
            ),
        },
    ),
    (882095, "0000882095-26-000006"): (  # GILD
        'CONSOLIDATED STATEMENTS OF CASH FLOWS', "R9.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation expense'),
                ('us-gaap:AdjustmentForAmortization', 'Amortization expense'),
            ),
        },
    ),
    (51143, "0000051143-26-000010"): (  # IBM
        'CONSOLIDATED STATEMENT OF CASH FLOWS', "R7.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of capitalized software and acquired intangible assets'),
            ),
        },
    ),
    (50863, "0000050863-26-000011"): (  # INTC
        'Consolidated Statements of Cash Flows', "R7.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangibles'),
            ),
        },
    ),
    (1035267, "0001035267-26-000010"): (  # ISRG
        'Consolidated Statements Of Cash Flows', "R9.htm", 1_000_000, {
            "depreciation_with_disposal_loss": (
                ('isrg:DepreciationandGainLossonDispositionofPropertyPlantEquipment', 'Depreciation and loss on disposal of property, plant, and equipment, net'),
            ),
            "amortization_with_other_assets": (
                ('isrg:AmortizationOfIntangibleAssetsContractAcquisitionAndOtherAssets', 'Amortization of intangible and other assets'),
            ),
        },
    ),
    (1048286, "0001048286-26-000007"): (  # MAR
        'CONSOLIDATED STATEMENTS OF CASH FLOWS', "R6.htm", 1_000_000, {
            "da_with_other": (
                ('mar:DepreciationAmortizationAndOther', ('Depreciation, amortization, and other (including depreciation and '
 'amortization classified in reimbursed expenses)')),
            ),
        },
    ),
    (310158, "0000310158-26-000063"): (  # MRK
        'Consolidated Statement of Cash Flows', "R9.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AdjustmentForAmortization', 'Amortization'),
            ),
        },
    ),
    (1835632, "0001835632-26-000011"): (  # MRVL
        'CONSOLIDATED STATEMENTS OF CASH FLOWS', "R9.htm", 1_000_000, {
            "da": (
                ('us-gaap:OtherDepreciationAndAmortization', 'Depreciation and amortization'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of acquired intangible assets'),
            ),
        },
    ),
    (789019, "0001193125-26-323660"): (  # MSFT
        'CASH FLOWS STATEMENTS', "R6.htm", 1_000_000, {
            "da_with_other": (
                ('msft:DepreciationAmortizationAndOther', 'Depreciation, amortization, and other'),
            ),
        },
    ),
    (1341439, "0001193125-26-277521"): (  # ORCL
        'CONSOLIDATED STATEMENTS OF CASH FLOWS', "R8.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of intangible assets'),
            ),
        },
    ),
    (76334, "0000076334-26-000105"): (  # PH
        'Consolidated Statements of Cash Flows', "R7.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:AdjustmentForAmortization', 'Amortization'),
            ),
        },
    ),
    (1000184, "0001104659-26-020058"): (  # SAP
        'Consolidated Statements of Cash Flows', "R6.htm", 1_000_000, {
            "da": (
                ('ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense', 'Depreciation and amortization'),
            ),
        },
    ),
    (1306965, "0001628280-26-017024"): (  # SHEL
        'CONSOLIDATED STATEMENT OF CASH FLOWS', "R7.htm", 1_000_000, {
            "da": (
                ('ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense', 'Depreciation, depletion and amortisation'),
            ),
        },
    ),
    (1121404, "0001628280-26-008403"): (  # SNY
        'Consolidated statements of cash flows', "R8.htm", 1_000_000, {
            "da_with_impairment": (
                ('sny:AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossOfPropertyPlantAndEquipmentRightOfUseAssetsAndIntangibleAsset', ('Depreciation, amortization and impairment of property, plant and equipment, '
 'right-of-use assets and intangible assets')),
            ),
        },
    ),
    (92122, "0000092122-26-000006"): (  # SO
        'Consolidated Statements of Cash Flows - Southern', "R6.htm", 1_000_000, {
            "da_with_accretion": (
                ('us-gaap:DepreciationAmortizationAndAccretionNet', 'Depreciation and amortization, total'),
            ),
        },
    ),
    (1639920, "0001628280-26-006874"): (  # SPOT
        'Consolidated statement of cash flows', "R7.htm", 1, {
            "da": (
                ('ifrs-full:AdjustmentsForDepreciationExpense', 'Depreciation of property and equipment and lease right-of-use assets'),
                ('ifrs-full:AdjustmentsForAmortisationExpense', 'Amortization of intangible assets'),
            ),
        },
    ),
    (97745, "0000097745-26-000018"): (  # TMO
        'CONSOLIDATED STATEMENTS OF CASH FLOWS', "R8.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation of property, plant and equipment'),
                ('us-gaap:AmortizationOfIntangibleAssets', 'Amortization of acquisition-related intangible assets'),
            ),
        },
    ),
    (1318605, "0001628280-26-003952"): (  # TSLA
        'Consolidated Statements of Cash Flows', "R9.htm", 1_000_000, {
            "da_with_impairment": (
                ('tsla:DepreciationAmortizationAndImpairment', 'Depreciation, amortization and impairment'),
            ),
        },
    ),
    (879764, "0001104659-26-035876"): (  # TTE
        'CONSOLIDATED STATEMENT OF CASH FLOW', "R5.htm", 1_000_000, {
            "da_with_impairment": (
                ('ifrs-full:AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss', 'Depreciation, depletion, amortization and impairment'),
            ),
        },
    ),
    (97476, "0000097476-26-000059"): (  # TXN
        'Consolidated Statements of Cash Flows', "R7.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
                ('us-gaap:CapitalizedComputerSoftwareAmortization1', 'Amortization of capitalized software'),
            ),
        },
    ),
    (100885, "0000100885-26-000037"): (  # UNP
        'Consolidated Statements of Cash Flows', "R8.htm", 1_000_000, {
            "da": (
                ('us-gaap:Depreciation', 'Depreciation'),
            ),
        },
    ),
    CISCO: (
        "Consolidated Statements of Cash Flows", "R8.htm", 1_000_000, {
            "da_with_other": (("csco:DepreciationAmortizationAndOther", "Depreciation, amortization, and other"),),
        },
    ),
    MCDONALDS: (
        "Consolidated Statement of Cash Flows", "R9.htm", 1_000_000, {
            "da": (("us-gaap:DepreciationAndAmortization", "Depreciation and amortization"),),
        },
    ),
    MCKESSON: (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R9.htm", 1_000_000, {
            "da": (("us-gaap:Depreciation", "Depreciation"), ("us-gaap:AdjustmentForAmortization", "Amortization")),
        },
    ),
    VALERO: (
        "Consolidated Statements of Cash Flows", "R9.htm", 1_000_000, {
            "da": (("us-gaap:DepreciationAmortizationAndAccretionNet", "Depreciation and amortization expense"),),
        },
    ),
    (104169, "0000104169-26-000055"): (  # WMT
        'Consolidated Statements of Cash Flows', "R8.htm", 1_000_000, {
            "da": (
                ('us-gaap:DepreciationAmortizationAndAccretionNet', 'Depreciation and amortization'),
            ),
        },
    ),
}

DEPRECIATION = ("us-gaap:Depreciation", "Depreciation")
AMORTIZATION = ("us-gaap:AmortizationOfIntangibleAssets", "Amortization of intangible assets")
PPE = ("ifrs-full:DepreciationPropertyPlantAndEquipment", "Depreciation of property, plant and equipment")
ROU = ("ifrs-full:DepreciationRightofuseAssets", "Depreciation of right-of-use assets")
INTANGIBLES = ("ifrs-full:AmortisationIntangibleAssetsOtherThanGoodwill", "Amortization of intangible assets")
INTANGIBLE_IMPAIRMENT = (
    "ifrs-full:ImpairmentLossRecognisedInProfitOrLossIntangibleAssetsOtherThanGoodwill", "Impairment of intangible assets",
)
PPE_IMPAIRMENT = ("ifrs-full:ImpairmentLossRecognisedInProfitOrLossPropertyPlantAndEquipment", "Impairment of property, plant and equipment")

# Note lines are exact consolidated Company Facts values for the same filing.
NOTES = {
    (1467373, "0001467373-26-000049"): {
        "da": (DEPRECIATION, AMORTIZATION),
        "amortization_deferred_transition": (("us-gaap:CapitalizedContractCostAmortization", "Amortization of deferred transition costs"),),
        "operating_lease_cost": (("us-gaap:OperatingLeaseCost", "Operating lease cost"),),
        "other_da_adjustment": (("us-gaap:OtherDepreciationAndAmortization", "Other"),),
    },
    (1730168, "0001730168-25-000121"): {"da": (DEPRECIATION, AMORTIZATION)},
    (901832, "0001104659-26-019130"): {"da": (PPE, ROU, INTANGIBLES), "asset_impairment": (PPE_IMPAIRMENT, INTANGIBLE_IMPAIRMENT)},
    (1303523, "0001303523-26-000017"): {
        "da": (("ifrs-full:DepreciationPropertyPlantAndEquipmentIncludingRightofuseAssets", "Depreciation of PP&E and right-of-use assets"), INTANGIBLES),
        "asset_impairment": (
            ("ifrs-full:ImpairmentLossRecognisedInProfitOrLossIntangibleAssetsAndGoodwill", "Impairment of intangible assets and goodwill"),
            ("ifrs-full:ImpairmentLossRecognisedInProfitOrLossPropertyPlantAndEquipmentIncludingRightofuseAssets", "Impairment of PP&E and right-of-use assets"),
            ("-ifrs-full:ReversalOfImpairmentLossRecognisedInProfitOrLossPropertyPlantAndEquipmentIncludingRightofuseAssets", "Reversal of impairment of PP&E and right-of-use assets"),
        ),
    },
    (1035267, "0001035267-26-000010"): {"da": (DEPRECIATION, AMORTIZATION)},
    (1048286, "0001048286-26-000007"): {"da": (DEPRECIATION, AMORTIZATION)},
    (789019, "0001193125-26-323660"): {"da": (DEPRECIATION, AMORTIZATION)},
    (863064, "0001628280-26-009531"): {
        "da": (PPE, ROU, INTANGIBLES),
        "da_reported_total": (("ifrs-full:AdjustmentsForDepreciationAndAmortisationExpense", "Depreciation and amortisation in the cash-flow reconciliation"),),
    },
    VALERO: {
        "da_general_and_administrative": (("us-gaap:DepreciationAndAmortization", "General and administrative depreciation and amortization"),),
        "da_cost_of_sales": (("us-gaap:CostOfGoodsAndServicesSoldDepreciationAndAmortization", "Depreciation and amortization in cost of sales"),),
    },
    NOVARTIS: {"da": (PPE, ROU, ("disclosed:ContinuingIntangibleAmortization", "Note 11 · Continuing operations amortization charge"))},
}

CHECKS = {
    (1467373, "0001467373-26-000049"): (
        "da_with_other", "-da", "-amortization_deferred_transition", "-operating_lease_cost", "-other_da_adjustment",
    ),
    (901832, "0001104659-26-019130"): ("da_with_impairment", "-da", "-asset_impairment"),
    (1303523, "0001303523-26-000017"): ("da_with_impairment", "-da", "-asset_impairment"),
    (863064, "0001628280-26-009531"): ("da_reported_total", "-da"),
    VALERO: ("da", "-da_general_and_administrative", "-da_cost_of_sales"),
}
PDF_FIELDS = {
    AIRBNB: {"da": (("disclosed:DepreciationAndAmortization", "p. 38 · Adjusted EBITDA reconciliation · Depreciation and amortization"),)},
}
GAPS = {
    CISCO: "The cash-flow adjustment includes other items. The existing tagged amount covers only a portion of consolidated depreciation and amortization.",
    (1668717, "0001193125-26-088105"): "The cash-flow adjustment includes impairment. Separate it using the operating expense disclosures.",
    (1652044, "0001652044-26-000018"): "The cash-flow statement separately reports property and equipment depreciation. A consolidated intangible-amortization amount needs its own source.",
    (1121404, "0001628280-26-008403"): "The cash-flow adjustment includes impairment across several asset classes. Separate the continuing operations depreciation and amortization from those charges.",
    (92122, "0000092122-26-000006"): "The cash-flow adjustment uses a broader concept than the income-statement expense. Reconcile accretion and the nuclear fuel treatment before using the total.",
    (1318605, "0001628280-26-003952"): "The cash-flow adjustment includes impairment. The property and equipment note discloses depreciation separately, while the remaining amount needs to be reconciled.",
    (879764, "0001104659-26-035876"): "The cash-flow adjustment includes impairments of multiple asset classes. Separate the depreciation, depletion and amortization from those charges.",
}


# These tags were verified as partial when used as the company's total.
PARTIAL_DA = {
    VALERO: ("us-gaap:DepreciationAndAmortization", "da_general_and_administrative", "General and administrative depreciation and amortization"),
    MCDONALDS: ("us-gaap:DepreciationDepletionAndAmortization", "da_general_and_administrative", "Selling, general and administrative depreciation and amortization"),
    MCKESSON: ("us-gaap:DepreciationDepletionAndAmortization", "da_ppe_and_finance_lease", "Depreciation of PP&E and amortization of finance lease right-of-use assets"),
    CISCO: ("us-gaap:DepreciationDepletionAndAmortization", "da_tagged_component", "Tagged D&A with partial scope"),
}
PINNED = CASH_TABLES.keys() | NOTES.keys() | PDF_FIELDS.keys() | GAPS.keys()
RECURRING = {
    cik: (cik, accession) for cik, accession in sorted(
        PINNED - {AIRBNB, NOVARTIS}, key=lambda item: (item[0], item[1].split("-")[1:]),
    )
}


def rule_key(cik, report):
    key = cik, report["accession"]
    if key in PINNED:
        return key
    if report["form"] in {"10-K", "20-F", "40-F"}:
        return RECURRING.get(cik, key)
    return key


def table_fields(key):
    profile = CASH_TABLES.get(key)
    return profile[3] if profile else {}


def profile_fields(cik, report):
    key = rule_key(cik, report)
    return {**table_fields(key), **NOTES.get(key, {}), **PDF_FIELDS.get(key, {})}


def gap_reason(cik, report):
    return GAPS.get(rule_key(cik, report))


def separate_partial_da(statement, key):
    rule = PARTIAL_DA.get(key)
    current = statement["facts"].get("da")
    if not rule or not current or current["tag"] != rule[0]:
        return statement
    _, field, label = rule
    facts = statement["facts"].copy()
    facts[field] = {**facts.pop("da"), "locator": label}
    return {**statement, "facts": facts}


def table_belongs_to_filing(table_url, report, pinned_filename=None):
    path = report["path"] + "/"
    if not isinstance(table_url, str) or not table_url.startswith(path):
        return False
    filename = table_url[len(path):]
    return filename == pinned_filename if pinned_filename else bool(re.fullmatch(r"R[1-9]\d*\.htm", filename))


def cash_components(cache, obj, cik, report, statement, component):
    key = rule_key(cik, report)
    title, filename, reviewed_scale, fields = CASH_TABLES[key]
    pinned = key == (cik, report["accession"])
    request = request_bytes(f"{cik:010d}", "annual", report["accession"], "cash_flow")
    raw, receipt = cache.get(ENDPOINT, 8760, post_json=request)
    data, checksums = decode_response(raw, receipt, report, cik, "annual")
    table = data["cash_flow"]
    sources = table["sources"]
    table_url = sources[0] if len(sources) == 1 else None
    scale = table["money_scale"]
    digest = checksums.get(table_url, "")
    year = "12 months to " + statement["end"]
    if (" ".join(table["title"].casefold().split()) != " ".join(title.casefold().split()) or
            not table_belongs_to_filing(table_url, report, filename if pinned else None) or
            table["currency"] != statement["currency"] or
            scale not in {1, 1_000, 1_000_000, 1_000_000_000} or (pinned and scale != reviewed_scale) or
            table["columns"].count(year) != 1 or not re.fullmatch(r"[0-9a-f]{16}", digest)):
        raise ValueError("Unverified annual depreciation cash-flow table")
    index = table["columns"].index(year)
    cfo = statement["facts"]["cfo"]
    # SEC renders dimensional subtables after the consolidated face statement.
    rows = table["rows"]
    dimension = next((i for i, row in enumerate(rows) if row[1] is None), len(rows))
    totals = [i for i, row in enumerate(rows[:dimension]) if row[1] == cfo["tag"] and row[index] is not None]
    if len(totals) != 1 or scaled(rows[totals[0]][index], scale) != cfo["value"]:
        raise ValueError("Depreciation cash-flow table does not match consolidated operating cash")
    operating = {**table, "rows": rows[:totals[0]]}

    def get_part(tag, label):
        value = scaled(amount(operating, tag, index, label)[0], scale)
        direct = exact_sec_amount(obj, statement, report, tag)
        if direct is not None and direct != value:
            raise ValueError(f"Cash-flow line disagrees with SEC Company Facts for {label}")
        return component(tag, label, value, receipt, table_url=table_url, table_sha256_16=digest)

    return {field: [get_part(*line) for line in lines] for field, lines in fields.items()}


def airbnb_amount(cache, statement):
    source = PDFS[AIRBNB][0]
    raw, receipt = cache.get(source, 8760)
    pages = [p for p in pdf_pages(raw) if p.rstrip().endswith("38") and "Adjusted EBITDA Reconciliation" in p
             and "2024" in p and statement["end"][:4] in p and "in millions" in p]
    if len(pages) != 1 or statement["currency"] != "USD":
        raise ValueError("Missing expected Airbnb EBITDA reconciliation")
    page = pages[0].split("Free Cash Flow Reconciliation", 1)[0]
    for label, field in (("Revenue", "sales"), ("Net income", "net")):
        if scaled(column(page, label, 2, column_index=1), 1_000_000) != statement["facts"][field]["value"]:
            raise ValueError("Airbnb reconciliation does not match the selected filing")
    return scaled(column(page, "Depreciation and amortization", 2, column_index=1), 1_000_000), receipt


def novartis_amount(cache, obj, report, statement):
    raw, receipt = cache.get(NOVARTIS_PDF, 8760)
    pages = pdf_pages(raw)
    notes = [p for p in pages if p.rstrip().endswith("F-35") and "Amortization charge" in p
             and "for continuing operations" in p and statement["end"][:4] in p and "(USD millions)" in p]
    cash = [p for p in pages if p.rstrip().endswith("F-49") and "23.1) Non-cash items and other adjustments from continuing operations" in p]
    if len(notes) != 1 or len(cash) != 1 or statement["currency"] != "USD":
        raise ValueError("Missing Novartis continuing operations amortization reconciliation")

    def usd_millions(page, label):
        page = re.sub(r"(?<=\d) (?=\d{3}(?: +|$))", "", page, flags=re.M)
        page = re.sub(r"– (\d+)", r"(\1)", page)
        return scaled(column(page, label, 3), 1_000_000)

    value = -usd_millions(notes[0], "Amortization charge")
    impairment = exact_sec_amount(obj, statement, report, "ifrs-full:ImpairmentLossRecognisedInProfitOrLossIntangibleAssetsAndGoodwill")
    if impairment is None or value + impairment != usd_millions(cash[0], "Intangible assets"):
        raise ValueError("Novartis intangible amortization does not reconcile to the continuing cash-flow note")
    return value, receipt


def enrich_depreciation(cache, obj, meta, cik, report, statement):
    key = rule_key(cik, report)
    if ((statement["filing"], statement["end"], statement["period_kind"]) !=
            (report["accession"], report["end"], "annual")):
        raise ValueError("Depreciation profile does not match the selected annual statement")

    def component(tag, label, value, receipt, **source_fields):
        if value is None or value < 0:
            raise ValueError(f"Missing or negative depreciation component for {label}")
        return {
            "value": value, "tag": tag.removeprefix("-"), "sign": -1 if tag.startswith("-") else 1, "line": label,
            "unit": statement["currency"], "start": statement["start"], "form": report["form"], "filed": report["filed"],
            "accession": report["accession"], "url": report["url"], "source": receipt["url"], "sha256": receipt["sha256"],
            **source_fields,
        }

    parts = cash_components(cache, obj, cik, report, statement, component) if key in CASH_TABLES else {}
    for field, lines in NOTES.get(key, {}).items():
        parts[field] = []
        for tag, label in lines:
            if tag == "disclosed:ContinuingIntangibleAmortization":
                value, receipt = novartis_amount(cache, obj, report, statement)
            else:
                value, receipt = exact_sec_amount(obj, statement, report, tag.removeprefix("-")), meta
            parts[field].append(component(tag, label, value, receipt))

    if key == AIRBNB:
        value, receipt = airbnb_amount(cache, statement)
        tag, label = PDF_FIELDS[key]["da"][0]
        parts["da"] = [component(tag, label, value, receipt)]

    facts = separate_partial_da(statement, key)["facts"].copy()
    if cik in {40545, 104169, VALERO[0]} and "da_with_accretion" in facts:
        old = facts["da_with_accretion"]
        if any((old["tag"], old["value"]) == (part["tag"], part["value"]) for part in parts["da"]):
            del facts["da_with_accretion"]
    for field, lines in parts.items():
        value = sum(part["sign"] * part["value"] for part in lines)
        if field in facts and facts[field]["value"] != value:
            raise ValueError(f"Depreciation components disagree with existing {field}")
        facts[field] = {
            **lines[0], "value": value, "tag": TAG, "components": lines,
            "locator": lines[0]["line"] if len(lines) == 1 else "Sum of reviewed depreciation and amortization lines",
        }

    if not reconciles(key, facts):
        raise ValueError("Depreciation and amortization components do not reconcile")
    return {**statement, "facts": facts}


def reconciles(key, facts):
    check = CHECKS.get(key, ())
    if any(field.removeprefix("-") not in facts for field in check):
        return False
    if sum((-1 if field.startswith("-") else 1) * facts[field.removeprefix("-")]["value"] for field in check):
        return False
    if key == (1730168, "0001730168-25-000121"):
        return facts["da"]["components"][1]["value"] <= facts["amortization_with_rou"]["value"]
    return True


def valid_component(cik, report, field, part):
    key = rule_key(cik, report)
    source = part["source"]
    tag = part["tag"]
    if field in table_fields(key):
        filename = CASH_TABLES[key][1] if key == (cik, report["accession"]) else None
        return (source == ENDPOINT and table_belongs_to_filing(part.get("table_url"), report, filename) and
                bool(re.fullmatch(r"[0-9a-f]{16}", part.get("table_sha256_16", ""))))
    if tag == "disclosed:DepreciationAndAmortization" and key == AIRBNB:
        return source == PDFS[key][0]
    if tag == "disclosed:ContinuingIntangibleAmortization" and key == NOVARTIS:
        return source == NOVARTIS_PDF
    return source == SEC.format(cik)
