"""Recover reviewed annual facts from Open10K's public SEC-derived exports."""

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from .facts import EPS_FIELDS, SHARE_FIELDS, STOCK, balance_check

ROUTE = "sec_workbook"
SOURCE = "Open10K · SEC data"
DA_TAG = f"{ROUTE}:DepreciationAmortizationSum"
DA_COMPONENTS = {
    1144967: ("da_ppe", "amortization"),
    1046179: ("depreciation", "amortization"),
}
CAPEX_TAG = f"{ROUTE}:CashCapitalInvestmentSum"
CAPEX_COMPONENTS = ("capex_ppe", "capex_intangibles")
BASE = "https://files.open10k.com/"
MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

# The fallback applies only to reviewed original accessions. Long-format
# workbooks identify the source fiscal year, while the balance sheet's current
# column links the year to the exact SEC accession and primary document.
PROFILES = {
    (1144967, "0001193125-26-322004"): (
        "2026-03-31", "INR", "US GAAP",
        "HDB-HDFC_BANK_LTD-annual_financial_statements-FY2010-FY2026-INR-20-F.xlsx",
    ),
    (313838, "0001193125-26-274893"): (
        "2026-03-31", "JPY", "IFRS",
        "SONY-Sony_Group_Corp-annual_financial_statements-FY2010-FY2026-JPY-20-F.xlsx",
    ),
    (1046179, "0001628280-26-025362"): (
        "2025-12-31", "TWD", "IFRS",
        "TSM-TAIWAN_SEMICONDUCTOR_MANUFACTURING_CO_LTD-annual_financial_statements-FY2014-FY2025-TWD-20-F.xlsx",
    ),
}

# Map concepts within the face statement where their scope is known. In
# particular, EPS in these workbooks is expressed in the currency column,
# and cash flow amounts use XBRL concept signs for outflow concepts.
COMMON = {
    "assets": "Assets", "liabilities": "Liabilities",
}
IFRS_BALANCE = {
    **COMMON, "book": "EquityAttributableToOwnersOfParent", "total_equity": "Equity",
    "minority": "NoncontrollingInterests", "cash": "CashAndCashEquivalents", "inventory": "Inventories",
}
IFRS_INCOME = {
    "net_parent": "ProfitLossAttributableToOwnersOfParent", "net_consolidated": "ProfitLoss",
    "net_nci": "ProfitLossAttributableToNoncontrollingInterests", "ebit": "ProfitLossFromOperatingActivities",
    "pretax": "ProfitLossBeforeTax", "tax": "IncomeTaxExpenseContinuingOperations",
    "eps_basic": "BasicEarningsLossPerShare", "eps_diluted": "DilutedEarningsLossPerShare",
}
IFRS_CASH = {"cfo": "CashFlowsFromUsedInOperatingActivities", "div_total": "DividendsPaidClassifiedAsFinancingActivities"}
STATEMENTS = {
    1144967: {
        "CONSOLIDATED BALANCE SHEETS": {
            **COMMON, "book": "StockholdersEquity", "total_equity": "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            "minority": "MinorityInterest", "customer_deposits": "Deposits",
            "loans_net": "LoansReceivableExcludingAccruedInterestNotDueAfterAllowanceForCreditLoss",
            "cash_including_restricted": "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "debt": "LongTermDebt", "short_borrow": "ShortTermBorrowings",
        },
        "CONSOLIDATED BALANCE SHEETS (Parenthetical)": {"shares_outstanding": "CommonStockSharesOutstanding"},
        "CONSOLIDATED STATEMENTS OF INCOME": {
            "sales": "Revenues", "net_parent": "NetIncomeLoss", "net_consolidated": "ProfitLoss",
            "net_nci": "NetIncomeLossAttributableToNoncontrollingInterest", "net_interest_income": "InterestIncomeExpenseNet",
            "credit_loss_provision": "ProvisionForLoanLeaseAndOtherLosses", "interest": "InterestExpenseOperating",
            "pretax": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "tax": "IncomeTaxExpenseBenefit", "eps_basic": "EarningsPerShareBasic", "eps_diluted": "EarningsPerShareDiluted",
            "eps_ads_basic": "EarningsPerShareAmericanDepositorySharesBasic",
            "eps_ads_diluted": "EarningsPerShareAmericanDepositorySharesDiluted",
        },
        "CONSOLIDATED STATEMENTS OF CASH FLOWS": {
            "cfo": "NetCashProvidedByUsedInOperatingActivities", "capex": "PaymentsToAcquirePropertyPlantAndEquipment",
            "da_ppe": "OtherDepreciationAndAmortization", "amortization": "AmortizationOfIntangibleAssets",
            "amortization_deferred_customer_acquisition": "AmortizationOfDeferredSalesCommissions",
            "div_total": "PaymentsOfDividends", "lt_issued": "ProceedsFromIssuanceOfLongTermDebt",
            "lt_repaid": "RepaymentsOfLongTermDebt",
        },
    },
    313838: {
        "Consolidated Statements of Financial Position": {
            **IFRS_BALANCE, "ar": "TradeAndOtherReceivablesAndContractAssetsCurrent", "ap": "TradeAndOtherCurrentPayables",
            "debt_current": "CurrentPortionOfLongtermBorrowings", "debt_noncurrent": "LongtermBorrowings",
            "short_borrow": "ShorttermBorrowings",
        },
        "Consolidated Statements of Income": {
            **IFRS_INCOME, "sales": "Revenue", "net_continuing": "ProfitLossFromContinuingOperations",
            "net_discontinued": "ProfitLossFromDiscontinuedOperations",
            "net_parent_continuing": "IncomeFromContinuingOperationsAttributableToOwnersOfParent",
        },
        "Consolidated Statements of Changes in Stockholders' Equity": {"dividend_in_kind": "DividendsPaidInKind"},
        "Consolidated Statements of Cash Flows": {
            **IFRS_CASH, "cfo_continuing": "CashFlowsFromUsedInOperatingActivitiesContinuingOperations",
            "cfo_discontinued": "CashFlowsFromUsedInOperatingActivitiesDiscontinuedOperations",
            "capex": "PurchaseOfPropertyPlantAndEquipmentIntangibleAssetsOtherThanGoodwillInvestmentPropertyAndOtherNoncurrentAssets",
            "da": "AdjustmentsForDepreciationAndAmortisationExpense",
            "buybacks": "PaymentsToAcquireOrRedeemEntitysShares",
            "lt_issued": "ProceedsFromNoncurrentBorrowings", "lt_repaid": "RepaymentsOfNoncurrentBorrowings",
        },
    },
    1046179: {
        "CONSOLIDATED STATEMENTS OF FINANCIAL POSITION": {
            **IFRS_BALANCE, "ar": "CurrentTradeReceivables", "ap": "TradeAndOtherCurrentPayablesToTradeSuppliers",
            "debt_current": "CurrentPortionOfLongtermBorrowings",
            "bonds_noncurrent": "NoncurrentPortionOfNoncurrentBondsIssued", "bank_loans_noncurrent": "LongtermBorrowings",
        },
        "CONSOLIDATED STATEMENTS OF PROFIT OR LOSS AND OTHER COMPREHENSIVE INCOME": {
            **IFRS_INCOME, "sales": "RevenueFromContractsWithCustomers", "interest": "FinanceCosts",
        },
        "CONSOLIDATED STATEMENTS OF CASH FLOWS": {
            **IFRS_CASH, "capex_ppe": "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
            "capex_intangibles": "PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
            "depreciation": "AdjustmentsForDepreciationExpense", "amortization": "AdjustmentsForAmortisationExpense",
        },
    },
}
STOCK_FIELDS = STOCK | {"cash_including_restricted", "bonds_noncurrent", "bank_loans_noncurrent"}
ADS_EPS = {"eps_ads_basic", "eps_ads_diluted"}
HEADERS = dict(zip("BDEIJKLMNOPQ", (
    "statement", "label", "tag", "row_type", "axis", "member", "fiscal_year",
    "period_end", "unit", "value", "value_source_form", "value_source_fy",
), strict=True))


def workbook_url(cik, report):
    profile = PROFILES.get((cik, report["accession"]))
    if profile and report["form"] == "20-F" and report["end"] == profile[0]:
        return BASE + profile[3]
    return None


def xml_part(archive, name):
    info = archive.getinfo(name)
    if info.file_size > 16_000_000:
        raise ValueError("Unexpected SEC workbook part size")
    data = archive.read(info)
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("Unexpected SEC workbook XML declarations")
    return ET.fromstring(data)


def cells(row):
    result = {}
    for cell in row.findall(f"{MAIN}c"):
        if cell.find(f"{MAIN}f") is not None:
            continue
        column = cell.attrib["r"].rstrip("0123456789")
        kind = cell.get("t", "n")
        if kind == "inlineStr":
            result[column] = "".join(t.text or "" for t in cell.iter(f"{MAIN}t"))
        elif kind == "n":
            result[column] = cell.findtext(f"{MAIN}v", "")
    return result


def sheet_rows(sheet):
    return sheet.findall(f"{MAIN}sheetData/{MAIN}row")


def scoped_rows(blob, cik, report):
    if len(blob) > 2_000_000:
        raise ValueError("Unexpected SEC workbook size")
    try:
        with ZipFile(BytesIO(blob)) as archive:
            workbook = xml_part(archive, "xl/workbook.xml")
            links = xml_part(archive, "xl/_rels/workbook.xml.rels")
            paths = {link.attrib["Id"]: link.attrib["Target"].lstrip("/") for link in links}
            sheets = {s.attrib["name"]: paths[s.attrib[REL_ID]] for s in workbook.findall(f"{MAIN}sheets/{MAIN}sheet")}
            readme = dict((row.get("A"), row.get("B")) for row in map(cells, sheet_rows(xml_part(archive, sheets["Read Me"]))))
            if readme.get("CIK") != str(cik):
                raise ValueError("SEC workbook registrant mismatch")
            balance_path = PurePosixPath(sheets["Balance Sheet"])
            balance = xml_part(archive, str(balance_path))
            balance_rels = xml_part(archive, str(balance_path.parent / "_rels" / (balance_path.name + ".rels")))
            filing_links = {link.attrib["Id"] for link in balance_rels if link.get("Target") in {
                report["url"], report["url"].replace("https://www.sec.gov/Archives/", "https://www.sec.gov/ix?doc=/Archives/"),
            }}
            fy = report["end"][:4]
            current_columns = {col for row in map(cells, sheet_rows(balance)[:12]) if row.get("A") == "Line item"
                               for col, val in row.items() if val == f"FY{fy}"}
            if not any(link.get(REL_ID) in filing_links and
                       link.attrib["ref"].rstrip("0123456789") in current_columns
                       for link in balance.iter(f"{MAIN}hyperlink")):
                raise ValueError("SEC workbook does not link the current fiscal year to the expected filing")
            rows = sheet_rows(xml_part(archive, sheets["Data (long)"]))
    except (BadZipFile, ET.ParseError, KeyError, TypeError) as exc:
        raise ValueError("Unexpected SEC workbook layout") from exc

    header = cells(rows[0]) if rows else {}
    if any(header.get(col) != label for col, label in HEADERS.items()):
        raise ValueError("Unexpected SEC workbook long-format columns")
    for row in map(cells, rows[1:]):
        if (row.get("M") == report["end"] and row.get("L") == row.get("Q") == fy and
                row.get("P") == report["form"] and row.get("I") == "line" and not row.get("J") and not row.get("K")):
            yield row


def read_workbook(blob, receipt, report, cik):
    source = workbook_url(cik, report)
    if not source or source != receipt["url"]:
        raise ValueError("SEC workbook does not match the requested filing")
    _, currency, accounting, _ = PROFILES[cik, report["accession"]]
    end = date.fromisoformat(report["end"])
    start = str(end.replace(year=end.year - 1) + timedelta(days=1))
    rows = defaultdict(list)
    for row in scoped_rows(blob, cik, report):
        rows[row.get("B"), row.get("E")].append(row)
    facts = {}
    for statement, mapping in STATEMENTS[cik].items():
        for key, concept in mapping.items():
            unit = "shares" if key in SHARE_FIELDS else currency
            candidates = [row for row in rows[statement, concept] if row.get("N") == unit]
            if not candidates or len({row.get("O") for row in candidates}) != 1:
                raise ValueError(f"SEC workbook has missing or ambiguous {key}")
            row = candidates[0]
            try:
                value = Decimal(row["O"])
            except (InvalidOperation, KeyError) as exc:
                raise ValueError(f"Invalid SEC workbook amount for {key}") from exc
            per_share = key in EPS_FIELDS or key in ADS_EPS
            if (not value.is_finite() or abs(value) > 10**18 or
                    (not per_share and value != value.to_integral_value())):
                raise ValueError(f"Invalid SEC workbook amount for {key}")
            facts[key] = {
                "value": float(value) if per_share else int(value),
                "unit": f"{unit}/ADS" if key in ADS_EPS else f"{unit}/shares" if per_share else unit,
                "start": None if key in STOCK_FIELDS else start, "tag": f"{ROUTE}:{concept}",
                "form": report["form"], "filed": report["filed"], "accession": report["accession"],
                "source": source, "url": report["url"], "sha256": receipt["sha256"],
                "locator": f"{statement} · {row['D']}",
            }

    facts["net"] = facts["net_parent"].copy()
    if cik == 1144967:
        for key in DA_COMPONENTS[cik]:
            concept = STATEMENTS[cik]["CONSOLIDATED STATEMENTS OF CASH FLOWS"][key]
            try:
                income = {Decimal(row["O"]) for row in rows["CONSOLIDATED STATEMENTS OF INCOME", concept]
                          if row.get("N") == currency}
            except (InvalidOperation, KeyError) as exc:
                raise ValueError(f"Invalid HDFC income statement amount for {key}") from exc
            if income != {facts[key]["value"]}:
                raise ValueError(f"HDFC income and cash-flow statements disagree on {key}")
    if cik in DA_COMPONENTS:
        components = DA_COMPONENTS[cik]
        if any(facts[key]["value"] < 0 for key in components):
            raise ValueError("SEC workbook depreciation and amortization must be nonnegative")
        facts["da"] = {
            **facts[components[0]], "value": sum(facts[key]["value"] for key in components),
            "tag": DA_TAG, "components": list(components),
            "locator": "Consolidated cash flows · " + (
                "Sum of the separate D&A and intangible amortization lines" if cik == 1144967
                else "Depreciation expense + amortization expense"
            ),
        }
    if cik == 1046179:
        components = ["bonds_noncurrent", "bank_loans_noncurrent"]
        facts["debt_noncurrent"] = {
            **facts[components[0]], "value": sum(facts[k]["value"] for k in components),
            "tag": f"{ROUTE}:NoncurrentBorrowingsSum", "components": components,
            "locator": "Consolidated financial position · Noncurrent bonds payable + long-term bank loans",
        }
        facts["capex"] = {
            **facts[CAPEX_COMPONENTS[0]], "value": sum(facts[k]["value"] for k in CAPEX_COMPONENTS),
            "tag": CAPEX_TAG, "components": list(CAPEX_COMPONENTS),
            "locator": "Consolidated cash flows · Purchases of property, plant and equipment + purchases of intangible assets",
        }
    result = {"end": str(end), "start": start, "currency": currency, "filing": report["accession"], "facts": facts,
              "conflicts": [], "period_kind": "annual", "accounting": accounting, "report": report, "route": ROUTE}
    check = balance_check(result)
    v = {key: fact["value"] for key, fact in facts.items()}
    if (not check["reconciled"] or check["unexplained_equity_attribution"] != 0 or v["assets"] <= 0 or
            abs(v["net_consolidated"] - v["net_parent"] - v["net_nci"]) > 100_000 or
            v["pretax"] - v["tax"] + v.get("net_discontinued", 0) != v["net_consolidated"]):
        raise ValueError("SEC workbook consolidated amounts do not reconcile")
    if cik == 1046179 and any(v[key] < 0 for key in CAPEX_COMPONENTS):
        raise ValueError("TSMC cash-investment components must be outflows")
    if cik == 313838 and (v["net_continuing"] + v["net_discontinued"] != v["net_consolidated"] or
                          v["cfo_continuing"] + v["cfo_discontinued"] != v["cfo"]):
        raise ValueError("Sony continuing and discontinued results do not reconcile")
    return result
