"""Normalize annual depreciation and amortization from reviewed filings."""

from datetime import date
import re

from .capex import PDFS
from .catalog import SUCCESSIONS
from .facts import annual_rule_key, exact_sec_amount, recurring_annual_rules
from .fetch import SEC
from .issuer_20f import column, linked_report, pdf_pages
from .rendered_filing import amount, annual_table, filing_tables, scaled, table_belongs_to_filing, valid_table_source

TAG = "derived:FiledDepreciationAndAmortization"
ADOBE = (796343, "0000796343-26-000003")
APPLOVIN = (1751008, "0001751008-26-000010")
DUKE = (1326160, "0001326160-26-000014")
EQUINOR = (1140625, "0001140625-26-000013")
EXXON = (34088, "0000034088-26-000045")
GENERAL_DYNAMICS = (40533, "0000040533-26-000006")
HOME_DEPOT = (354950, "0001628280-26-019436")
MODERNA = (1682852, "0001682852-26-000033")
NETFLIX = (1065280, "0001065280-26-000034")
SP_GLOBAL = (64040, "0000064040-26-000013")
UBER = (1543151, "0001543151-26-000015")
UNILEVER = (217410, "0000217410-26-000007")
US_DA = "us-gaap:DepreciationDepletionAndAmortization"
US_AMORTIZATION = "us-gaap:AmortizationOfIntangibleAssets"
IFRS_DA = "ifrs-full:DepreciationAndAmortisationExpense"
IFRS_CASH_DA_AND_IMPAIRMENT = "ifrs-full:AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"
HOME_DEPOT_PPE_DA = (US_DA, "Depreciation and amortization, excluding amortization of intangible assets")
NETFLIX_OTHER_DA = (US_DA, "Depreciation and amortization of property, equipment and intangibles")
NETFLIX_CONTENT_DA = ("nflx:CostofServicesAmortizationofStreamingContentAssets", "Amortization of content assets")
AMGEN = (318154, "0000318154-26-000010")
AMAZON = (1018724, "0001018724-26-000004")
SANOFI = (1121404, "0001628280-26-008403")
SOUTHERN = (92122, "0000092122-26-000006")
TESLA = (1318605, "0001628280-26-003952")
TOTALENERGIES = (879764, "0001104659-26-035876")
ALIBABA = (1577552, "0001193125-26-231755")
SALESFORCE = (1108524, "0001108524-26-000060")
NOVO = (353278, "0000353278-26-000012")
BUD = (1668717, "0001193125-26-088105")
AIRBNB = (1559720, "0001559720-26-000004")
NOVARTIS = (1114448, "0001114448-26-000004")
VALERO = (1035002, "0001628280-26-011499")
CISCO = (858877, "0000858877-26-000132")
MCDONALDS = (63908, "0000063908-26-000035")
MCKESSON = (927653, "0000927653-26-000069")
NOVARTIS_PDF = "https://www.novartis.com/sites/novartis_com/files/novartis-annual-report-2025.pdf"

# Bind interpretation to the face statement of the exact accession. Tags
# alone cannot distinguish pure D&A from cash-flow adjustments with impairment.
CASH_DA = ("us-gaap:DepreciationAmortizationAndAccretionNet", "Depreciation and amortization")
SCHWAB = (316709, "0000316709-26-000009")
SCHWAB_DA = ("schw:DepreciationAndAmortizationExcludingAmortizationOfIntangibleAssets", "Depreciation and amortization")
SCHWAB_AMORTIZATION = (US_AMORTIZATION, "Amortization of acquired intangible assets")
BMO = (927971, "0001193125-25-307982")
BMO_PPE = ("bmo:AdjustmentsForDepreciationOfPremisesAndEquipment", "Depreciation of premises and equipment (Note 8)")
BMO_OTHER = ("bmo:AdjustmentsForDepreciationOfOtherAssets", "Depreciation of other assets")
BMO_AMORTIZATION = ("bmo:AdjustmentsForAmortizationOfIntangibleAssets", "Amortization of intangible assets (Note 10)")
CIBC = (1045520, "0001193125-25-307488")
JPM = (19617, "0001628280-26-008131")
TD = (947263, "0001562762-25-000289")
TD_DEPRECIATION = ("ifrs-full:AdjustmentsForDepreciationExpense", "Depreciation")
TD_AMORTIZATION = ("td:AdjustmentsForAmortizationExpenseOfOtherIntangibles", "Amortization of other intangibles")
UBS = (1610520, "0001610520-26-000023")

CASH_TABLES = {
    (4962, "0000004962-26-000080"): (  # AXP
        "Consolidated Statements of Cash Flows", "R8.htm", 1_000_000, {"da": (CASH_DA,)},
    ),
    BMO: (
        "Consolidated Statement of Cash Flows", "R7.htm", 1_000_000, {
            "da": (BMO_PPE, BMO_OTHER, BMO_AMORTIZATION),
            "da_ppe": (BMO_PPE,),
            "depreciation_other_assets": (BMO_OTHER,),
            "amortization": (BMO_AMORTIZATION,),
        },
    ),
    CIBC: (
        "Consolidated statement of cash flows", "R9.htm", 1_000_000, {
            "da_with_impairment": ((IFRS_CASH_DA_AND_IMPAIRMENT, "Amortization and impairment"),),
        },
    ),
    (1381197, "0001381197-26-000062"): (  # IBKR
        "Condensed Consolidated Statements of Cash Flows", "R8.htm", 1_000_000, {
            "da": (CASH_DA,),
            "amortization_operating_rou": (
                ("us-gaap:OperatingLeaseRightOfUseAssetAmortizationExpense", "Amortization of right-of-use assets"),
            ),
        },
    ),
    SCHWAB: (
        "Consolidated Statements of Cash Flows", "R9.htm", 1_000_000, {
            "da": (SCHWAB_DA, SCHWAB_AMORTIZATION),
            "da_excluding_acquired_intangibles": (SCHWAB_DA,),
            "amortization": (SCHWAB_AMORTIZATION,),
        },
    ),
    TD: (
        "Consolidated Statement of Cash Flows", "R7.htm", 1_000_000, {
            "da": (TD_DEPRECIATION, TD_AMORTIZATION),
            "depreciation": (TD_DEPRECIATION,),
            "amortization": (TD_AMORTIZATION,),
        },
    ),
    UBS: (
        "Consolidated Statement of Cash Flows", "R9.htm", 1_000_000, {
            "da_with_impairment": ((IFRS_CASH_DA_AND_IMPAIRMENT, "Depreciation, amortization and impairment of non-financial assets"),),
        },
    ),
    (896159, "0000896159-26-000005"): (  # CB
        "Consolidated Statements Of Cash Flows", "R8.htm", 1_000_000, {
            "amortization": (("us-gaap:PresentValueOfFutureInsuranceProfitsAmortizationExpense1", "Amortization of purchased intangibles"),),
        },
    ),
    (80661, "0000080661-26-000086"): (  # PGR
        "Consolidated Statements of Cash Flows", "R7.htm", 1_000_000, {
            "depreciation": (("us-gaap:Depreciation", "Depreciation"),),
        },
    ),
    ADOBE: (
        "Consolidated Statements of Cash Flows", "R8.htm", 1_000_000, {
            "da_with_accretion": ((US_DA, "Depreciation, amortization and accretion"),),
        },
    ),
    APPLOVIN: (
        "Consolidated Statements of Cash Flows", "R8.htm", 1_000, {
            "da_with_writeoffs": ((US_DA, "Amortization, depreciation and write-offs"),),
        },
    ),
    DUKE: (
        "Condensed Consolidated Statements of Cash Flows", "R8.htm", 1_000_000, {
            "da_with_accretion": ((US_DA, "Depreciation, amortization and accretion (including amortization of nuclear fuel)"),),
        },
    ),
    EQUINOR: (
        "CONSOLIDATED STATEMENT OF CASH FLOWS", "R7.htm", 1_000_000, {
            "da_with_impairment_and_writeoffs": (
                (IFRS_CASH_DA_AND_IMPAIRMENT, "Depreciation, amortisation and net impairments, including exploration write-offs"),
            ),
        },
    ),
    EXXON: (
        "Consolidated Statement Of Cash Flows", "R7.htm", 1_000_000, {
            "da_with_impairment": ((US_DA, "Depreciation and depletion (includes impairments)"),),
        },
    ),
    GENERAL_DYNAMICS: (
        "Consolidated Statement of Cash Flows", "R6.htm", 1_000_000, {
            "da": (
                ("us-gaap:Depreciation", "Depreciation of property, plant and equipment"),
                ("gd:AmortizationofIntangibleAssetsAndFinanceLeaseRightofUseAssets",
                 "Amortization of intangible and finance lease right-of-use assets"),
            ),
        },
    ),
    HOME_DEPOT: (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R8.htm", 1_000_000, {
            "da": (HOME_DEPOT_PPE_DA, (US_AMORTIZATION, "Intangible asset amortization")),
            "da_ppe": (HOME_DEPOT_PPE_DA,),
        },
    ),
    MODERNA: (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R8.htm", 1_000_000, {
            "da": (("us-gaap:OtherDepreciationAndAmortization", "Depreciation and amortization"),),
        },
    ),
    NETFLIX: (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R5.htm", 1_000, {
            "da": (NETFLIX_OTHER_DA,),
            "amortization_content": (NETFLIX_CONTENT_DA,),
            "da_including_content": (NETFLIX_OTHER_DA, NETFLIX_CONTENT_DA),
        },
    ),
    SP_GLOBAL: (
        "Consolidated Statements of Cash Flows", "R7.htm", 1_000_000, {
            "da": (("us-gaap:Depreciation", "Depreciation"), (US_AMORTIZATION, "Amortization of intangibles")),
        },
    ),
    UBER: (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R8.htm", 1_000_000, {
            "da_including_nonoperating": (("uber:DepreciationAndAmortizationIncludingAmountFromOtherIncomeExpense",
                                            "Depreciation and amortization"),),
        },
    ),
    UNILEVER: (
        "Consolidated cash flow statement", "R9.htm", 1_000_000, {
            "da_with_impairment": ((IFRS_CASH_DA_AND_IMPAIRMENT, "Depreciation, amortisation and impairment"),),
        },
    ),
    AMGEN: (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R9.htm", 1_000_000, {
            "da_with_other": (("us-gaap:DepreciationDepletionAndAmortization", "Depreciation, amortization and other"),),
        },
    ),
    AMAZON: (
        "Consolidated Statements of Cash Flows", "R3.htm", 1_000_000, {
            "da_with_other": (("us-gaap:DepreciationDepletionAndAmortization",
                               "Depreciation and amortization of property and equipment and capitalized content costs, operating lease assets, and other"),),
        },
    ),
    ALIBABA: (
        "CONSOLIDATED STATEMENTS OF CASH FLOWS", "R8.htm", 1_000_000, {
            "amortization": (("us-gaap:AmortizationOfIntangibleAssets", "Amortization of intangible assets and licensed copyrights"),),
            "ppe_da_with_impairment_and_lease": (("baba:DepreciationAndImpairmentOfPropertyAndEquipmentAndLandUseRights",
                                                   "Depreciation and impairment of property and equipment, and operating lease cost relating to land use rights"),),
        },
    ),
    SALESFORCE: (
        "Consolidated Statements of Cash Flows", "R9.htm", 1_000_000, {
            "da_with_rou_and_impairment": (("us-gaap:DepreciationAndAmortization", "Depreciation and amortization"),),
            "amortization_deferred_contract_costs": (("us-gaap:CapitalizedContractCostAmortization",
                                                       "Amortization of costs capitalized to obtain revenue contracts, net"),),
        },
    ),
    NOVO: (
        "Cash flow statement", "R5.htm", 1_000_000, {
            "da_with_impairment": (("ifrs-full:AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
                                     "Depreciation, amortisation and impairment losses"),),
        },
    ),
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
    BUD: (
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
    SANOFI: (
        'Consolidated statements of cash flows', "R8.htm", 1_000_000, {
            "da_with_impairment": (
                ('sny:AdjustmentsForDepreciationAndAmortisationExpenseAndImpairmentLossReversalOfImpairmentLossOfPropertyPlantAndEquipmentRightOfUseAssetsAndIntangibleAsset', ('Depreciation, amortization and impairment of property, plant and equipment, '
 'right-of-use assets and intangible assets')),
            ),
        },
    ),
    SOUTHERN: (
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
    TESLA: (
        'Consolidated Statements of Cash Flows', "R9.htm", 1_000_000, {
            "da_with_impairment": (
                ('tsla:DepreciationAmortizationAndImpairment', 'Depreciation, amortization and impairment'),
            ),
        },
    ),
    TOTALENERGIES: (
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
APP_PPE = ("us-gaap:Depreciation", "Note 5 · Continuing PP&E depreciation, including finance leases (rounded)")
APP_INTANGIBLES = (US_AMORTIZATION, "Note 7 · Continuing intangible amortization")
AMAZON_PPE = ("us-gaap:Depreciation", "Note 10 · Consolidated PP&E D&A, including finance leases")
AMAZON_INTANGIBLES = (US_AMORTIZATION, "Note 5 · Acquired intangible amortization, excluding video content")
FINANCE_LEASE_DA = ("us-gaap:FinanceLeaseRightOfUseAssetAmortization", "Leases note · Finance lease asset amortization")
RETIREMENT_ACCRETION = ("us-gaap:AssetRetirementObligationAccretionExpense", "Asset retirement obligations note · Accretion expense")

NOTES = {
    ADOBE: {
        "da": (("us-gaap:OtherDepreciationAndAmortization", "Property and equipment note · Depreciation and amortization"),
               (US_AMORTIZATION, "Goodwill and other intangibles note · Amortization of other intangibles")),
    },
    APPLOVIN: {
        "da": (APP_PPE, APP_INTANGIBLES),
        "da_ppe_and_finance_lease": (APP_PPE,),
        "amortization": (APP_INTANGIBLES,),
    },
    AMGEN: {
        "da_ppe": (("us-gaap:Depreciation", "Note 12 · PP&E depreciation and amortization"),),
        "da_ppe_and_rou": (("us-gaap:DepreciationAndAmortization", "Note 2 · Depreciation and right-of-use asset amortization"),),
    },
    AMAZON: {
        "da": (AMAZON_PPE, AMAZON_INTANGIBLES),
        "da_ppe_and_finance_lease": (AMAZON_PPE,),
        "amortization": (AMAZON_INTANGIBLES,),
        "amortization_finance_rou": (FINANCE_LEASE_DA,),
    },
    SANOFI: {
        "amortization": (("ifrs-full:AmortisationIntangibleAssetsOtherThanGoodwill", "Income statement · Separately presented intangible amortization"),),
        "impairment_intangible_net": (("ifrs-full:ImpairmentLossRecognisedInProfitOrLossIntangibleAssetsOtherThanGoodwill",
                                      "Note D.4 · Intangible impairment net of reversals"),),
        "impairment_ppe_net": (("ifrs-full:ImpairmentLossRecognisedInProfitOrLossPropertyPlantAndEquipment",
                                "Note D.3 · Owned PP&E impairment net of reversals"),),
    },
    SOUTHERN: {"retirement_accretion": (RETIREMENT_ACCRETION,)},
    (831001, "0000831001-26-000011"): {  # C
        "da": ((CASH_DA[0], "Continuing cash flow · Depreciation and amortization"),),
    },
    JPM: {
        "da": ((CASH_DA[0], "Consolidated cash flow · Depreciation and amortization"),),
        "depreciation_leased_assets": (("us-gaap:OperatingLeasesIncomeStatementDepreciationExpenseOnPropertySubjectToOrHeldForLease",
                                       "Noninterest expense note · Depreciation of assets under operating leases"),),
    },
    (1393818, "0001193125-26-082531"): {  # BX
        "depreciation": (("us-gaap:Depreciation", "Note 10 · Furniture, equipment and leasehold improvement depreciation"),),
        "amortization": ((US_AMORTIZATION, "Consolidated cash flow · Amortization of intangibles"),),
    },
    SALESFORCE: {
        "da_ppe": ((US_DA, "Note 5 · Fixed-asset D&A, including finance leases (rounded)"),),
        "amortization_finance_rou": (FINANCE_LEASE_DA,),
    },
    TOTALENERGIES: {
        "impairment_ppe_and_exploration": (("ifrs-full:ImpairmentLossRecognisedInProfitOrLossPropertyPlantAndEquipment",
                                            "Note 7.2 · Exceptional PP&E impairments and capitalized exploration charges"),),
        "impairment_intangibles_and_goodwill": (("ifrs-full:ImpairmentLossRecognisedInProfitOrLossIntangibleAssetsAndGoodwill",
                                                 "Note 7.1 · Exceptional impairments of intangible assets including goodwill"),),
        "impairment_goodwill": (("ifrs-full:ImpairmentLossRecognisedInProfitOrLossGoodwill",
                                 "Note 7.1 · Goodwill impairments included in intangible impairments"),),
    },
    TESLA: {
        "da_ppe": (("us-gaap:Depreciation", "Note 6 · PP&E depreciation (rounded)"),),
        "amortization_finance_rou": (FINANCE_LEASE_DA,),
    },
    DUKE: {
        "da_excluding_nuclear_fuel": (("us-gaap:CostDepreciationAmortizationAndDepletion",
                                       "Consolidated statement of operations · Depreciation and amortization"),),
        "retirement_accretion": (RETIREMENT_ACCRETION,),
    },
    EQUINOR: {
        "da": ((IFRS_DA, "Operating segments note · Consolidated depreciation and amortisation"),),
        "da_with_impairment": (("ifrs-full:DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
                                "Consolidated statement of income · Depreciation, amortisation and net impairments"),),
    },
    MODERNA: {
        "da_ppe": ((US_DA, "Property, plant and equipment note · Depreciation and amortization"),),
    },
    UBER: {
        "da": ((US_DA, "Consolidated statement of operations · Depreciation and amortization"),),
    },
    UNILEVER: {
        "da": ((IFRS_DA, "Depreciation and amortisation expense"),),
        "asset_impairment": (("ifrs-full:ImpairmentLoss", "Impairment"),),
    },
    ALIBABA: {
        "da": (("us-gaap:DepreciationDepletionAndAmortization", "Note 15 · Property and equipment depreciation"),
               ("us-gaap:AmortizationOfIntangibleAssets", "Amortization of intangible assets and licensed copyrights")),
        "da_ppe": (("us-gaap:DepreciationDepletionAndAmortization", "Note 15 · Property and equipment depreciation"),),
    },
    NOVO: {
        "da": (("ifrs-full:DepreciationAndAmortisationExpense", "Consolidated depreciation and amortisation expenses"),),
        "asset_impairment": (
            ("ifrs-full:ImpairmentLossRecognisedInProfitOrLossPropertyPlantAndEquipmentIncludingRightofuseAssets",
             "Impairment of property, plant and equipment including right-of-use assets"),
            INTANGIBLE_IMPAIRMENT,
        ),
    },
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
    BMO: ("da", "-da_ppe", "-depreciation_other_assets", "-amortization"),
    CIBC: ("da_with_impairment", "-ppe_da_with_impairment", "-amortization_with_impairment"),
    SCHWAB: ("da", "-da_excluding_acquired_intangibles", "-amortization"),
    TD: ("da", "-depreciation", "-amortization"),
    NETFLIX: ("da_including_content", "-da", "-amortization_content"),
    UNILEVER: ("da_with_impairment", "-da", "-asset_impairment"),
    NOVO: ("da_with_impairment", "-da", "-asset_impairment"),
    (1467373, "0001467373-26-000049"): (
        "da_with_other", "-da", "-amortization_deferred_transition", "-operating_lease_cost", "-other_da_adjustment",
    ),
    (901832, "0001104659-26-019130"): ("da_with_impairment", "-da", "-asset_impairment"),
    (1303523, "0001303523-26-000017"): ("da_with_impairment", "-da", "-asset_impairment"),
    (863064, "0001628280-26-009531"): ("da_reported_total", "-da"),
    VALERO: ("da", "-da_general_and_administrative", "-da_cost_of_sales"),
}
BUD_PDF_LINES = (
    ("disclosed:OwnedPropertyDepreciation", "Note 13 · Depreciation of owned property, plant and equipment"),
    ("disclosed:IntangibleAssetAmortization", "Note 15 · Amortization of intangible assets"),
)
PDF_FIELDS = {
    BUD: {"da": BUD_PDF_LINES + (ROU,)},
    AIRBNB: {"da": (("disclosed:DepreciationAndAmortization", "p. 38 · Adjusted EBITDA reconciliation · Depreciation and amortization"),)},
}
CIBC_ASSET_LINES = {
    "ppe_da_with_impairment": (("disclosed:PPEAndLeaseDepreciationWithImpairment",
                               "Property and equipment note · Depreciation and impairment"),),
    "amortization_with_impairment": (("disclosed:IntangibleAmortizationWithImpairment",
                                     "Software and other intangible assets note · Amortization and impairment"),),
}
UBS_ASSET_NOTES = {
    "Property, equipment and software (Detail)": (
        "Accumulated depreciation Depreciation Impairment owned properties leased properties software",
        "R113.htm", "Accumulated depreciation", {
            "depreciation_ppe_and_software": ("Depreciation", "disclosed:PropertyEquipmentAndSoftwareDepreciation",
                                             "Property, equipment and software note · Depreciation including leased property"),
            "impairment_ppe_and_software": ("Impairment", "disclosed:PropertyEquipmentAndSoftwareImpairment",
                                          "Property, equipment and software note · Impairment"),
        },
    ),
    "Goodwill and intangible assets (Detail 2)": (
        "Accumulated amortization and impairment Amortization reversal of impairment goodwill",
        "R116.htm", "Accumulated amortization and impairment", {
            "amortization": ("Amortization", "disclosed:IntangibleAmortization",
                             "Goodwill and intangible assets note · Amortization"),
        },
    ),
}
ASSET_FIELDS = {
    CIBC: CIBC_ASSET_LINES,
    UBS: {field: ((tag, label),) for _, _, _, fields in UBS_ASSET_NOTES.values()
          for field, (_, tag, label) in fields.items()},
}
GAPS = {
    CIBC: "Property and equipment and intangible asset note totals reconcile to the cash-flow adjustment. Both include impairment.",
    UBS: "The asset notes report depreciation, amortization and impairment separately. The note amounts do not fully reconcile to the cash-flow adjustment.",
    APPLOVIN: "The cash-flow adjustment includes write-offs and the discontinued Apps business. Continuing asset-note amounts are required for the add-back.",
    AMAZON: "The cash-flow adjustment includes content and operating lease items. Separate PP&E and acquired intangible amounts are required for the add-back.",
    DUKE: "The cash-flow adjustment includes accretion and nuclear fuel amortization. The income statement and asset-retirement note show narrower amounts.",
    EXXON: "The cash-flow line includes impairments. The filing describes impairments across several expense lines without separately identifying an exact depreciation and depletion subtotal.",
    AMGEN: "The cash-flow line includes operating lease amortization. A matching annual exhibit and reviewed lease scope are required for the add-back.",
    SALESFORCE: "The cash-flow adjustment includes amortization and impairment of right-of-use assets. Fixed-asset depreciation and contract-acquisition amortization are shown separately.",
    CISCO: "The cash-flow adjustment includes other items. The property and equipment note covers only those assets. Purchased intangible amortization has a separate disclosure scope.",
    BUD: "The cash-flow adjustment includes impairment. The pure depreciation and amortization amounts require the audited asset notes.",
    (1652044, "0001652044-26-000018"): "The cash-flow statement separately reports property and equipment depreciation. A consolidated intangible-amortization amount needs its own source.",
    SANOFI: "The cash-flow adjustment includes impairment across several asset classes. Separate the continuing operations depreciation and amortization from those charges.",
    SOUTHERN: "The cash-flow adjustment uses a broader concept than the income-statement expense. Reconcile accretion and the nuclear fuel treatment before using the total.",
    TESLA: "The cash-flow adjustment includes impairment. The property and equipment note discloses depreciation separately, while the remaining amount needs to be reconciled.",
    TOTALENERGIES: "The cash-flow adjustment includes impairments of multiple asset classes. Separate the depreciation, depletion and amortization from those charges.",
}


# These tags were verified as partial when used as the company's total.
PARTIAL_DA = {
    ADOBE: (US_DA, "da_with_accretion", "Depreciation, amortization and accretion"),
    APPLOVIN: (US_DA, "da_with_writeoffs", "Amortization, depreciation and write-offs, including discontinued operations"),
    DUKE: (US_DA, "da_with_accretion", "Depreciation, amortization and accretion including nuclear fuel"),
    EXXON: (US_DA, "da_with_impairment", "Depreciation and depletion including impairments"),
    HOME_DEPOT: (US_DA, "da_ppe", HOME_DEPOT_PPE_DA[1]),
    MODERNA: (US_DA, "da_ppe", "Property, plant and equipment depreciation and amortization"),
    AMGEN: ("us-gaap:DepreciationDepletionAndAmortization", "da_with_other", "Depreciation, amortization and other"),
    AMAZON: ("us-gaap:DepreciationDepletionAndAmortization", "da_with_other",
             "Cash-flow D&A including capitalized content, operating lease assets, and other"),
    ALIBABA: ("us-gaap:DepreciationDepletionAndAmortization", "da_ppe", "Property and equipment depreciation"),
    SALESFORCE: (US_DA, "da_ppe", "Note 5 · Fixed-asset D&A, including finance leases (rounded)"),
    VALERO: ("us-gaap:DepreciationAndAmortization", "da_general_and_administrative", "General and administrative depreciation and amortization"),
    MCDONALDS: ("us-gaap:DepreciationDepletionAndAmortization", "da_general_and_administrative", "Selling, general and administrative depreciation and amortization"),
    MCKESSON: ("us-gaap:DepreciationDepletionAndAmortization", "da_ppe_and_finance_lease", "Depreciation of PP&E and amortization of finance lease right-of-use assets"),
    CISCO: ("us-gaap:DepreciationDepletionAndAmortization", "da_ppe",
            "Property and equipment depreciation and amortization"),
}
PINNED = CASH_TABLES.keys() | NOTES.keys() | PDF_FIELDS.keys() | GAPS.keys()
RECURRING = recurring_annual_rules(PINNED - {AIRBNB, NOVARTIS})
# Carry reviewed scope forward for SEC-confirmed registrant successions.
for successor, succession in SUCCESSIONS.items():
    predecessor = succession["predecessor_cik"]
    if successor not in RECURRING and predecessor in RECURRING:
        RECURRING[successor] = RECURRING[predecessor]


def rule_key(cik, report):
    return annual_rule_key(cik, report, PINNED, RECURRING)


def table_fields(key):
    profile = CASH_TABLES.get(key)
    return profile[3] if profile else {}


def profile_fields(cik, report):
    key = rule_key(cik, report)
    return {**table_fields(key), **NOTES.get(key, {}), **PDF_FIELDS.get(key, {}), **ASSET_FIELDS.get(key, {})}


def gap_reason(cik, report):
    return GAPS.get(rule_key(cik, report))


def separate_partial_da(statement, key):
    rule = PARTIAL_DA.get(key)
    current = statement["facts"].get("da")
    if not rule or not current:
        return statement
    tag, field, label = rule
    facts = statement["facts"].copy()
    if current["tag"] != tag:
        field, label = "da_tagged_component", "Tagged amount pending scope reconciliation"
    facts[field] = {**facts.pop("da"), "locator": label}
    return {**statement, "facts": facts}


def cash_components(cache, obj, cik, report, statement, component):
    key = rule_key(cik, report)
    title, filename, reviewed_scale, fields = CASH_TABLES[key]
    pinned = key == (cik, report["accession"])
    table, index, receipt, evidence = annual_table(cache, cik, report, statement, "cash_flow", title,
                                                    filename if pinned else None, reviewed_scale if pinned else None)
    scale = table["money_scale"]
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
        return component(tag, label, value, receipt, **evidence)

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


def bud_report_url(report):
    year = report["end"][:4]
    return f"https://www.ab-inbev.com/news-media/news-stories/ab-in-bev-{year}-annual-report"


def bud_amounts(cache, obj, report, statement):
    year = report["end"][:4]
    if statement["currency"] != "USD" or report["form"] != "20-F" or report["end"] != f"{year}-12-31":
        raise ValueError("Unexpected AB InBev reporting period or currency")
    source = bud_report_url(report)
    page, _ = cache.get(source, 8760)
    href = linked_report(page, f"Click here to view and download the {year} Annual Report (English)", "cdn.builder.io")
    raw, receipt = cache.get(href, 8760)
    pages = pdf_pages(raw)

    def read(heading, anchor, label, count, index, occurrence=None, dated_header=False):
        matches = [p for p in pages if heading in p and anchor in p and year in p and "Million US dollar" in p]
        if len(matches) != 1:
            raise ValueError(f"Missing unique AB InBev annual table for {heading}")
        table = matches[0]
        if dated_header:
            start = table.index(heading)
            current = table.find(f"31 December {year}", start)
            previous = table.find(f"31 December {int(year)-1}", start)
            if not 0 <= current < previous:
                raise ValueError("Unexpected order of years in AB InBev asset notes")
        table = re.sub(r"(?<=\d) (?=\d{3}(?:[)\s]|$))", "", table)
        return scaled(column(table, label, count, occurrence=occurrence, column_index=index), 1_000_000)

    cfo = read("Consolidated statement of cash flows", "Depreciation, amortization and impairment",
               "Cash flow from/(used in) operating activities", 2, 0)
    if cfo != statement["facts"]["cfo"]["value"]:
        raise ValueError("AB InBev annual report does not match the filed consolidated cash flow")
    depreciation = -read("13. Property, plant and equipment", "Depreciation and impairment losses",
                         "Depreciation", 5, 3, dated_header=True)
    amortization = -read("15. Intangible assets", "Amortization and impairment losses", "Amortization", 6, 4, dated_header=True)
    leases = exact_sec_amount(obj, statement, report, ROU[0])
    if leases != -read("Property, plant and equipment leased by the company", "Net carrying amount at 31 December",
                        "Depreciation for the year ended 31 December", 3, 2, occurrence=0, dated_header=True):
        raise ValueError("AB InBev lease depreciation does not match the filed note")
    return (depreciation, amortization), leases, {**receipt, "url": source}


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


def cibc_asset_report_url(report):
    year = report["end"][:4]
    return ("https://www.cibc.com/content/dam/cibc-public-assets/about-cibc/investor-relations/pdfs/"
            f"quarterly-results/{year}/consolidated-financials-{year}-en.pdf")


def cibc_asset_amounts(cache, report, statement, adjustment, component):
    url = cibc_asset_report_url(report)
    raw, receipt = cache.get(url, 8760)
    pages = pdf_pages(raw)
    year = report["end"][:4]
    cash, = [page for page in pages if re.search(r"^ *Consolidated statement of cash flows *$", page, re.M)]
    if (receipt["url"] != url or statement["currency"] != "CAD" or not report["end"].endswith("-10-31") or
            not re.search(rf"Millions of Canadian dollars, for the year ended October 31 +{year} +{int(year) - 1}\b", cash) or
            scaled(column(cash, "Net cash flows provided by (used in) operating activities", 2), 1_000_000) !=
            statement["facts"]["cfo"]["value"] or
            scaled(column(cash, "Amortization and impairment (1)", 2), 1_000_000) != adjustment):
        raise ValueError("CIBC issuer financial statements disagree with EDGAR cash flow")

    layouts = {
        "ppe_da_with_impairment": ("Property and equipment", "depreciation", "Depreciation and impairment", 6),
        "amortization_with_impairment": ("Software and other intangible assets", "amortization",
                                        "Amortization and impairment", 5),
    }
    result = {}
    for field, (title, accumulated, row, count) in layouts.items():
        page, = [page for page in pages if title in page and
                 re.search(rf"^ *{year} +Accumulated {accumulated} *$", page, re.M)
                 and "$ millions, as at or for the year ended October 31" in page]
        section = re.split(rf"^ *{year} +Accumulated {accumulated} *$", page, maxsplit=1, flags=re.M)[1]
        current, = re.findall(rf"^ *({row}(?: \(\d+\))?) {{2,}}", section, re.M)
        amounts = [scaled(column(section, current, count, column_index=i), 1_000_000) for i in range(count)]
        if sum(amounts[:-1]) != amounts[-1]:
            raise ValueError(f"CIBC asset class amounts disagree with {row} total")
        result[field] = [component(*CIBC_ASSET_LINES[field][0], amounts[-1], receipt)]
    return result


def ubs_asset_amounts(cache, report, statement, component, pinned):
    end = date.fromisoformat(report["end"])
    period = f"12 Months Ended Dec. {end.day}, {end.year}"
    if end.month != 12 or statement["currency"] != "USD":
        raise ValueError("Unexpected UBS annual reporting period or currency")
    result = {}
    for title, (query, filename, section, fields) in UBS_ASSET_NOTES.items():
        tables, receipts, receipt = filing_tables(cache, UBS[0], report, query)
        table, = [t for t in tables if t["source"] == "xbrl report" and t["title"] == title
                  and t["units"] == "USD ($) $ in Millions" and t["columns"].count(period) == 1
                  and table_belongs_to_filing(t.get("url"), report, filename if pinned else None)]
        url = table["url"]
        evidence = {"table_url": url, "table_sha256_16": receipts.get(url, "")}
        if not valid_table_source({**evidence, "source": receipt["url"], "sha256": receipt["sha256"]}, report):
            raise ValueError(f"Missing SEC source checksum for {title}")
        index = table["columns"].index(period)
        rows = table["rows"]
        start, = [i for i, row in enumerate(rows) if row[0] == section and all(v is None for v in row[1:])]
        # Stop at the next dimensional member heading.
        stop = next((i for i in range(start + 1, len(rows)) if all(v is None for v in rows[i][1:])), len(rows))
        for field, (line, tag, label) in fields.items():
            value, = [r[index] for r in rows[start + 1:stop] if r[0] == line]
            if type(value) not in (int, float):
                raise ValueError(f"Missing consolidated UBS asset note amount for {line}")
            result[field] = [component(tag, label, scaled(value, 1_000_000), receipt, **evidence)]
    return result


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

    if key == CIBC:
        parts.update(cibc_asset_amounts(cache, report, statement, parts["da_with_impairment"][0]["value"], component))
    if key == UBS:
        parts.update(ubs_asset_amounts(cache, report, statement, component, key == (cik, report["accession"])))

    if key == AIRBNB:
        value, receipt = airbnb_amount(cache, statement)
        tag, label = PDF_FIELDS[key]["da"][0]
        parts["da"] = [component(tag, label, value, receipt)]

    if key == BUD:
        values, leases, receipt = bud_amounts(cache, obj, report, statement)
        parts["da"] = [component(tag, label, value, receipt)
                       for (tag, label), value in zip(BUD_PDF_LINES, values, strict=True)]
        parts["da"].append(component(*ROU, leases, meta))

    facts = separate_partial_da(statement, key)["facts"].copy()
    if cik in {4962, 19617, 40545, 104169, 831001, 1381197, VALERO[0]} and "da_with_accretion" in facts:
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


DA_SCOPE_BOUNDS = {
    ADOBE: ("da", "da_with_accretion"),
    APPLOVIN: ("da", "da_with_writeoffs"),
    AMGEN: ("da_ppe", "da_ppe_and_rou"),
    AMAZON: ("da", "da_with_other"),
    TESLA: ("da_ppe", "da_with_impairment"),
    SALESFORCE: ("amortization_finance_rou", "da_ppe"),
    TOTALENERGIES: ("impairment_goodwill", "impairment_intangibles_and_goodwill"),
    DUKE: ("da_excluding_nuclear_fuel", "da_with_accretion"),
    MODERNA: ("da_ppe", "da"),
    UBER: ("da", "da_including_nonoperating"),
}


def reconciles(key, facts):
    check = CHECKS.get(key, ())
    if any(field.removeprefix("-") not in facts for field in check):
        return False
    if sum((-1 if field.startswith("-") else 1) * facts[field.removeprefix("-")]["value"] for field in check):
        return False
    if key in {ALIBABA, APPLOVIN, AMAZON}:
        ppe = "da_ppe" if key == ALIBABA else "da_ppe_and_finance_lease"
        if (facts["da"]["components"][0]["value"] != facts[ppe]["value"] or
                facts["da"]["components"][1]["value"] != facts["amortization"]["value"]):
            return False
        if key == AMAZON and not 0 <= facts["amortization_finance_rou"]["value"] <= facts[ppe]["value"]:
            return False
    bounds = DA_SCOPE_BOUNDS.get(key)
    if bounds:
        lower, upper = bounds
        return 0 <= facts[lower]["value"] <= facts[upper]["value"]
    if key == EQUINOR:
        return 0 <= facts["da"]["value"] <= facts["da_with_impairment"]["value"] <= facts["da_with_impairment_and_writeoffs"]["value"]
    if key == BUD:
        return 0 < facts["da"]["value"] <= facts["da_with_impairment"]["value"]
    if key == (1730168, "0001730168-25-000121"):
        return facts["da"]["components"][1]["value"] <= facts["amortization_with_rou"]["value"]
    return True


def valid_component(cik, report, field, part):
    key = rule_key(cik, report)
    source = part["source"]
    tag = part["tag"]
    if field in table_fields(key):
        filename = CASH_TABLES[key][1] if key == (cik, report["accession"]) else None
        return valid_table_source(part, report, filename)
    if key == CIBC and field in CIBC_ASSET_LINES:
        return source == cibc_asset_report_url(report)
    if key == UBS and field in ASSET_FIELDS[UBS]:
        filename, = [filename for _, filename, _, fields in UBS_ASSET_NOTES.values() if field in fields]
        return valid_table_source(part, report, filename if key == (cik, report["accession"]) else None)
    if key == BUD and tag in {tag for tag, _ in BUD_PDF_LINES}:
        return source == bud_report_url(report)
    if tag == "disclosed:DepreciationAndAmortization" and key == AIRBNB:
        return source == PDFS[key][0]
    if tag == "disclosed:ContinuingIntangibleAmortization" and key == NOVARTIS:
        return source == NOVARTIS_PDF
    return source == SEC.format(cik)
