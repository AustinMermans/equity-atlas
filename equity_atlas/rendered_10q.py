"""Extract the Southern consolidated statements from SEC-rendered tables."""

from datetime import date
import json
import math
import re

from .facts import EPS_FIELDS, SHARE_FIELDS, STOCK, balance_check

ROUTE = "rendered_10q"
ENDPOINT = "https://canlicapital.com/mcp/canli"
CIK = 92122
ACCESSION = "0000092122-26-000069"
END = "2026-09-30"
TABLES = {
    "income": ("Condensed Consolidated Statements of Income (Unaudited) - Southern", "R2.htm"),
    "cash_flow": ("Condensed Consolidated Statements of Cash Flows (Unaudited) - Southern", "R6.htm"),
    "balance_sheet": ("Condensed Consolidated Balance Sheets (Unaudited) - Southern", "R8.htm"),
    "equity": ("Condensed Consolidated Statements of Stockholders' Equity (Unaudited) - Southern", "R10.htm"),
}
INCOME = {
    "sales": "us-gaap:Revenues", "ebit": "us-gaap:OperatingIncomeLoss",
    "da_excluding_nuclear_fuel": "so:DepreciationAndAmortizationExcludingNuclearFuel",
    "interest": "us-gaap:InterestAndDebtExpense",
    "pretax": "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "tax": "us-gaap:IncomeTaxExpenseBenefit", "net_consolidated": "us-gaap:ProfitLoss",
    "net_parent": "us-gaap:NetIncomeLoss", "net_nci": "us-gaap:NetIncomeLossAttributableToNoncontrollingInterest",
    "eps_basic": "us-gaap:EarningsPerShareBasic", "eps_diluted": "us-gaap:EarningsPerShareDiluted",
    "weighted_shares_basic": "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
    "weighted_shares_diluted": "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
}
BALANCE = {
    "assets": "us-gaap:Assets", "liabilities": "us-gaap:Liabilities",
    "total_equity": "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    "cash": "us-gaap:CashAndCashEquivalentsAtCarryingValue", "ap": "us-gaap:AccountsPayableCurrent",
    "short_borrow": "us-gaap:ShortTermBorrowings", "debt_current": "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent",
    "debt_noncurrent": "us-gaap:LongTermDebtAndCapitalLeaseObligations",
}
CASH_FLOW = {
    "cfo": "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    "capex": "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
    "da_with_accretion": "us-gaap:DepreciationAmortizationAndAccretionNet",
    "div": "us-gaap:PaymentsOfDividendsCommonStock", "div_nci": "us-gaap:PaymentsToMinorityShareholders",
    "issuance": "us-gaap:ProceedsFromIssuanceOfCommonStock",
    "lt_issued": "us-gaap:ProceedsFromIssuanceOfLongTermDebtAndCapitalSecuritiesNet",
    "lt_repaid": "us-gaap:RepaymentsOfLongTermDebtAndCapitalSecurities",
    "st_issued": "us-gaap:ProceedsFromOtherShortTermDebt", "st_repaid": "us-gaap:RepaymentsOfOtherShortTermDebt",
    "notes_payable_net": "us-gaap:ProceedsFromNotesPayable",
}
OUTFLOWS = {"interest", "capex", "div", "div_nci", "lt_repaid", "st_repaid"}
EQUITY_COLUMNS = ["line", "concept", "Total", "Common Stock", "Treasury", "Paid-In Capital",
                  "Retained Earnings", "Accumulated Other Comprehensive Income (Loss)", "Noncontrolling Interests"]


def rendered_10q_url(cik, report):
    if cik == CIK and (report["accession"], report["form"], report["end"]) == (ACCESSION, "10-Q", END):
        return ENDPOINT
    return None


def table_url(report, section):
    return report["path"] + "/" + TABLES[section][1]


def request_bytes(report, equity):
    arguments = {"company": "SO", "period": "quarterly", "accession": report["accession"]}
    if equity:
        arguments["statement"] = "equity"
    return json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "run_tool", "arguments": {"name": "financial_statements", "arguments": arguments}},
    }, sort_keys=True).encode()


def read_tables(raw, receipt, report, sections):
    if receipt["url"] != ENDPOINT or len(raw) > 400_000:
        raise ValueError("Unexpected rendered filing response source or size")
    result = json.loads(raw)["result"]
    if result.get("isError"):
        raise ValueError("Canli could not retrieve the rendered SEC filing")
    data = result["structuredContent"]
    accession, form, filed, end, index = data["filings"]["rows"][0]
    if (data["company"]["cik"] != CIK or data["period"] != "quarterly" or len(data["filings"]["rows"]) != 1 or
            (accession, form, filed, end) != tuple(report[k] for k in ("accession", "form", "filed", "end")) or
            not index.startswith(report["path"] + "/")):
        raise ValueError("Canli response does not match Southern's exact filing")
    sources = result["_meta"]["canlicapital.com/receipt"]["sources"]
    checksums = {row["url"]: row["sha256_16"] for row in sources}
    tables = {}
    for section in sections:
        table = data[section]
        url = table_url(report, section)
        digest = checksums.get(url, "")
        share_scale = 1_000_000 if section in {"income", "equity"} else 1
        if (table["title"] != TABLES[section][0] or table["sources"] != [url] or
                (table["currency"], table["money_scale"], table["shares_scale"]) != ("USD", 1_000_000, share_scale) or
                not re.fullmatch(r"[0-9a-f]{16}", digest)):
            raise ValueError(f"Unverified Southern consolidated {section} table")
        tables[section] = {**table, "url": url, "digest": digest, "sha256": receipt["sha256"]}
    return tables


def amount(table, concept, column, label=None):
    matches = [r for r in table["rows"] if r[1] == concept and (label is None or r[0] == label)]
    if not matches or len({r[column] for r in matches}) != 1:
        raise ValueError(f"Missing or conflicting rendered fact for {concept}")
    row = matches[0]
    value = row[column]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Invalid rendered fact for {concept}")
    return value, row[0]


def periods_from_rendered_10q(cache, report, cik, kinds):
    if not rendered_10q_url(cik, report):
        raise ValueError("Rendered statements are not registered for this accession")
    tables = {}
    for equity, sections in ((False, ("income", "balance_sheet", "cash_flow")), (True, ("equity",))):
        raw, receipt = cache.get(ENDPOINT, 8760, post_json=request_bytes(report, equity))
        tables.update(read_tables(raw, receipt, report, sections))
    income, balance, cash, equity = (tables[key] for key in ("income", "balance_sheet", "cash_flow", "equity"))
    if (income["columns"] != ["line", "concept", f"3 months to {END}", "3 months to 2025-09-30",
                              f"9 months to {END}", "9 months to 2025-09-30"] or
            balance["columns"] != ["line", "concept", END, "2025-12-31"] or
            cash["columns"] != ["line", "concept", f"9 months to {END}", "9 months to 2025-09-30"] or
            equity["columns"] != EQUITY_COLUMNS):
        raise ValueError("Unexpected Southern quarterly statement periods or equity columns")

    # The SEC income table repeats the revenue concept within dimensions after
    # the consolidated face statement. Keep only the face statement rows.
    first_segment = next((i for i, row in enumerate(income["rows"]) if row[0] == "Retail electric revenues"), None)
    if first_segment is None:
        raise ValueError("Cannot distinguish Southern consolidated and dimensional income facts")
    income["rows"] = income["rows"][:first_segment]
    close = "Ending balance at Sep. 30, 2026"
    equity_concept = BALANCE["total_equity"]
    equity_total, _ = amount(equity, equity_concept, EQUITY_COLUMNS.index("Total"), close)
    minority, _ = amount(equity, equity_concept, EQUITY_COLUMNS.index("Noncontrolling Interests"), close)
    book = sum(amount(equity, equity_concept, column, close)[0] for column in range(3, 8))
    if equity_total != book + minority:
        raise ValueError("Southern parent and noncontrolling equity do not reconcile")

    def statement(kind):
        start = date(2026, 7 if kind == "quarter" else 1, 1).isoformat()
        facts = {}

        def save(table, key, concept, value, label):
            per_share = key in EPS_FIELDS
            unit = "shares" if key in SHARE_FIELDS else "USD/shares" if per_share else "USD"
            scale = table["shares_scale"] if key in SHARE_FIELDS else table["money_scale"]
            facts[key] = {
                "value": value if per_share else round(value * scale),
                "unit": unit, "start": None if key in STOCK else start, "tag": concept,
                "form": report["form"], "filed": report["filed"], "accession": report["accession"],
                "source": ENDPOINT, "url": report["url"], "sha256": table["sha256"],
                "table_url": table["url"], "table_sha256_16": table["digest"],
                "locator": f"{table['title']} · {label}",
            }

        def read(table, mapping, index):
            for key, concept in mapping.items():
                value, label = amount(table, concept, index)
                save(table, key, concept, -value if key in OUTFLOWS else value, label)

        index = 2 if kind == "quarter" else 4
        read(income, INCOME, index)
        read(balance, BALANCE, 2)
        if kind == "ytd":
            read(cash, CASH_FLOW, 2)
        save(equity, "minority", "derived:EquityStatementNoncontrollingColumn", minority, close + " · Noncontrolling interests")
        save(equity, "book", "derived:EquityStatementParentColumns", book, close + " · Sum of parent equity columns")
        facts["common_book"] = facts["book"].copy()
        facts["net"] = facts["net_parent"].copy()
        result = {"end": END, "start": start, "currency": "USD", "filing": report["accession"],
                  "period_kind": kind, "facts": facts, "conflicts": [], "accounting": "US GAAP",
                  "report": report, "route": ROUTE}
        v = {key: fact["value"] for key, fact in facts.items()}
        expenses, _ = amount(income, "us-gaap:CostsAndExpenses", index)
        check = balance_check(result)
        if (not check["reconciled"] or check["unexplained_equity_attribution"] != 0 or
                v["total_equity"] != equity_total * 1_000_000 or
                v["sales"] - expenses * 1_000_000 != v["ebit"] or
                v["pretax"] - v["tax"] != v["net_consolidated"] or
                v["net_consolidated"] - v["net_nci"] != v["net_parent"]):
            raise ValueError("Southern consolidated rendered statements do not reconcile")
        return result

    return {kind: [statement(kind)] for kind in kinds}
