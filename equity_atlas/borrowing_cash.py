"""Reconcile debt cash flows to the consolidated financing statement."""

import re

from . import borrowing_notes
from .capex import FINANCING_TOTALS, cash_activity
from .dividends import OPERATING
from .facts import exact_sec_amount
from .rendered_filing import annual_table, scaled, valid_table_source

TAG = "derived:FiledBorrowingCashFlows"
US = "us-gaap:"
IFRS = "ifrs-full:"
DRAWS = {US + name for name in (
    "ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt", "ProceedsFromShortTermDebt",
    "ProceedsFromIssuanceOfCommercialPaper", "ProceedsFromIssuanceOfLongTermDebtAndCapitalSecuritiesNet",
    "ProceedsFromIssuanceOfSeniorLongTermDebt", "ProceedsFromOtherShortTermDebt",
    "ProceedsFromDebtMaturingInMoreThanThreeMonths", "ProceedsFromShortTermDebtMaturingInMoreThanThreeMonths",
    "ProceedsFromIssuanceOfSecuredDebt", "ProceedsFromIssuanceOfUnsecuredDebt", "ProceedsFromDebtNetOfIssuanceCosts",
    "ProceedsFromIssuanceOfOtherLongTermDebt", "ProceedsFromLinesOfCredit", "ProceedsFromConvertibleDebt",
    "ProceedsFromBankDebt", "ProceedsFromNotesPayable", "ProceedsFromIssuanceOfMediumTermNotes",
    "ProceedsFromFederalHomeLoanBankBorrowings",
)} | {IFRS + name for name in (
    "ProceedsFromBorrowingsClassifiedAsFinancingActivities", "ProceedsFromNoncurrentBorrowings",
    "ProceedsFromIssueOfSubordinatedLiabilities",
)}
REPAYMENTS = {US + name for name in (
    "RepaymentsOfLongTermDebt", "RepaymentsOfDebt", "RepaymentsOfShortTermDebt", "RepaymentsOfCommercialPaper",
    "RepaymentsOfOtherShortTermDebt", "RepaymentsOfDebtMaturingInMoreThanThreeMonths",
    "RepaymentsOfShortTermDebtMaturingInMoreThanThreeMonths", "RepaymentsOfSecuredDebt", "RepaymentsOfUnsecuredDebt",
    "RepaymentsOfSeniorDebt", "RepaymentsOfOtherLongTermDebt", "RepaymentsOfConvertibleDebt",
    "RepaymentsOfNotesPayable", "RepaymentsOfBankDebt", "RepaymentsOfLinesOfCredit", "RepaymentsOfLongTermLinesOfCredit",
    "RepaymentsOfFederalHomeLoanBankBorrowings", "RepaymentsOfAssumedDebt",
)} | {IFRS + name for name in (
    "RepaymentsOfBorrowingsClassifiedAsFinancingActivities", "RepaymentsOfNoncurrentBorrowings",
    "RepaymentsOfCurrentBorrowings", "RepaymentsOfSubordinatedLiabilities",
)}
NET = {US + name for name in (
    "ProceedsFromRepaymentsOfDebt", "ProceedsFromRepaymentsOfShortTermDebt",
    "ProceedsFromRepaymentsOfShortTermDebtMaturingInThreeMonthsOrLess",
    "ProceedsFromRepaymentsOfShortTermDebtMaturingInMoreThanThreeMonths", "ProceedsFromRepaymentsOfCommercialPaper",
    "ProceedsFromRepaymentsOfLinesOfCredit", "ProceedsFromRepaymentsOfOtherDebt",
)} | {IFRS + "CashFlowsFromUsedInIncreaseDecreaseInCurrentBorrowings"}
LEASE = {US + "FinanceLeasePrincipalPayments", IFRS + "PaymentsOfLeaseLiabilitiesClassifiedAsFinancingActivities"}
COSTS = {US + "PaymentsOfDebtIssuanceCosts"}
AMAZON_PRINCIPAL = "amzn:RepaymentsOfLongTermFinancingObligations"
FUNDED_ASSET = "nvda:PaymentsForFinancedPropertyPlantAndEquipmentAndIntangibleAssetsFinancingActivities"
TAGS = DRAWS | REPAYMENTS | NET | LEASE | COSTS

# Exact issuer extensions and statement labels with an identified cash-flow scope.
REVIEWED_ROWS = {
    ("abt:ProceedsFromLongTermDebtAndDebtMaturingInMoreThanThreeMonths",
     "proceeds from issuance of long-term debt and debt with maturities over 3 months"): "draw",
    ("abt:RepaymentsOfLongTermDebtAndDebtMaturingInMoreThanThreeMonths",
     "repayments of long-term debt and debt with maturities over 3 months"): "repayment",
    ("adi:PaymentsOfCommercialPaper", "payments of commercial paper notes"): "repayment",
    ("baba:ProceedsFromExchangeableBondsNetOfDebtIssuanceCost",
     "proceeds from exchangeable bonds, net of debt issuance cost"): "draw",
    ("cnq:IssuanceRepaymentsOfLineOfCreditBorrowingsClassifiedAsFinancingActivities",
     "(repayment) issuance of bank credit facilities and commercial paper, net"): "net",
    ("cnq:IssuanceOfOtherLongTermBorrowingsClassifiedAsFinancingActivities", "issuance of other long-term debt"): "draw",
    ("cnq:RepaymentsOfOtherLongTermBorrowingsClassifiedAsFinancingActivities", "repayment of other long-term debt"): "repayment",
    ("cof:ProceedsfromIssuanceofUnsecuredDebtandLongTermFHLBAdvancesNetofIssuanceCost",
     "issuance of senior and subordinated notes and long-term fhlb advances"): "draw",
    ("cof:RepaymentsofUnsecuredDebtandLongTermFHLBAdvances",
     "maturities and paydowns of senior and subordinated notes"): "repayment",
    ("duk:OtherProceedsfromShorttermDebtMaturinginMorethanThreeMonths",
     "proceeds from the issuance of short-term debt with original maturities greater than 90 days"): "draw",
    ("duk:OtherRepaymentsofShorttermDebtMaturinginMorethanThreeMonths",
     "payments for the redemption of short-term debt with original maturities greater than 90 days"): "repayment",
    ("enb:ProceedsFromRepaymentsOfCommercialPaperAndLinesOfCredit", "net change in commercial paper and credit facility draws"): "net",
    ("gsk:ProceedsRepaymentsFromOfShortTermLoans", "net increase/(decrease) in short-term loans"): "net",
    ("gsk:IncreaseDecreaseInOtherShortTermLoans", "increase in other short-term loans"): "draw",
    ("gsk:RepaymentOfOtherShortTermLoans", "repayment of other short-term loans"): "repayment",
    ("mar:ProceedsFromRepaymentsOfCommercialPaperAndLongTermLinesOfCredit", "commercial paper/credit facility, net"): "net",
    ("ry:ChangeInShortTermBorrowingsSubsidiaries", "change in short-term borrowings of subsidiaries"): "net",
    ("ry:ProceedsFromIssuanceOfSubordinatedDebentures", "issuance of subordinated debentures"): "draw",
    ("td:ProceedsFromRepaymentsOfSubordinatedLiabilities", "redemption or repurchase of subordinated notes and debentures"): "repayment",
    ("td:RepaymentOfLeaseLiabilities", "repayment of lease liabilities"): "lease",
    ("tmus:ProceedsFromIssuanceOfLongTermDebtNet", "proceeds from issuance of long-term debt, net"): "draw",
    ("tot:ProceedsFromRepaymentsOfNonCurrentBorrowings", "net issuance (repayment) of non-current debt"): "net",
    ("vz:ProceedsFromIssuanceOfLongtermDebtExcludingAssetbackedDebt", "proceeds from long-term borrowings"): "draw",
    ("wfc:ProceedsFromRepaymentsOfShortTermDebtNet", "short-term borrowings"): "net",
}
MIXED = {US + "RepaymentsOfDebtAndCapitalLeaseObligations", US + "RepaymentsOfLongTermDebtAndCapitalSecurities",
         US + "PaymentOfFinancingAndStockIssuanceCosts", US + "PaymentsOfFinancingCosts"}
CONTINUING = {ns + tag for ns, tag in (
    (US, "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"),
    (IFRS, "CashFlowsFromUsedInFinancingActivitiesContinuingOperations"),
)}
DISCONTINUED = {US + "CashProvidedByUsedInFinancingActivitiesDiscontinuedOperations",
                IFRS + "CashFlowsFromUsedInFinancingActivitiesDiscontinuedOperations"}
TITLE = re.compile(
    r"(?:(?:condensed )?consolidated (?:and combined )?|group )?"
    r"(?:statements? of (?:consolidated )?cash flows?|cash flows? statements?)"
    r"(?: for the years ended december 31| ₨ in millions,| - southern)?"
)
DEBT_WORDS = re.compile(r"\b(?:debt|borrow\w*|loans?|bonds?|debentures?|credit facilit\w*|commercial paper|"
                        r"lines? of credit|credit lines?|"
                        r"lease\w*|financ(?:ing|e) obligations?|securiti[sz]\w*|(?:senior|term|subordinated) notes|"
                        r"principal (?:payments|repayments)|vendor financ\w*)\b")
MIXED_WORDS = re.compile(r"\band other\b(?! (?:short.term|long.term|current|senior|unsecured|secured)?\s*(?:debt|borrowings)\b)"
                         r"|\band (?:equity|stock|preferred|lease\w*)\b"
                         r"|\b(?:derivatives?|capped calls?|convertible preferred|perpetual hybrid|non.cash|"
                         r"purchase of .* (?:bonds?|notes))\b")
NOT_BORROWING = re.compile(r"\b(?:dividends?|equity instruments?|preferred stock|preference shares?|"
                           r"equity awards?|capital contribution|coupon|lease incentives?)\b")


def supported(obj, report, period):
    return (report["end"] == period["end"] and "cfo" in period["facts"] and
            any(exact_sec_amount(obj, period, report, tag) is not None for tag in TAGS | MIXED))


def role(tag, label, value):
    label = label.casefold()
    if tag in DISCONTINUED:
        return "unallocated" if value else "other"
    if tag == FUNDED_ASSET:
        return "asset" if value <= 0 else "unallocated"
    if tag == AMAZON_PRINCIPAL and label == "principal repayments of financing obligations":
        return "obligations" if value <= 0 else "unallocated"
    if scoped := REVIEWED_ROWS.get((tag, label)):
        if scoped == "draw" and value < 0 or scoped in {"repayment", "lease"} and value > 0:
            return "unallocated"
        return "lease" if scoped == "lease" else "borrowing"
    if tag in TAGS:
        if MIXED_WORDS.search(label):
            return "unallocated" if value else "other"
        if tag in DRAWS and value < 0 or tag in REPAYMENTS | LEASE | COSTS and value > 0:
            return "unallocated"
        if tag in LEASE:
            return "lease"
        if tag in COSTS:
            return "costs"
        return "borrowing"
    if value and (tag in MIXED or DEBT_WORDS.search(label) and not NOT_BORROWING.search(label)):
        return "unallocated"
    return "other"


def extract(cache, obj, cik, report, period):
    table, column, receipt, source = annual_table(cache, cik, report, period, "cash_flow", None)
    title = " ".join(table["title"].casefold().split())
    if not TITLE.fullmatch(title):
        raise ValueError("Unexpected consolidated borrowing cash-flow title")
    rows = table["rows"]
    money = table["money_scale"]
    cfo, = (row for row in rows if row[1] in OPERATING and type(row[column]) in (int, float))
    total, = (row for row in rows if row[1] in FINANCING_TOTALS and type(row[column]) in (int, float))
    _, financing = cash_activity(table, column, cfo[1], financing=True)
    activity = financing["rows"]
    headers = [i for i, row in enumerate(activity) if row[1] in {t + "Abstract" for t in FINANCING_TOTALS}
               and row[column] is None]
    if headers:
        header, = headers
        activity = activity[header + 1:]
    lines = [{"line": row[0], "tag": row[1], "value": scaled(row[column], money)}
             for row in activity if type(row[column]) in (int, float) and row[1] not in CONTINUING]
    for line in lines:
        tag, value = line["tag"], line["value"]
        kind = role(tag, line["line"], value)
        if kind not in {"borrowing", "lease", "costs"} or sum(x["tag"] == tag for x in lines) > 1:
            continue
        exact = exact_sec_amount(obj, period, report, tag)
        if exact is not None and exact != (-value if tag in REPAYMENTS | LEASE | COSTS else value):
            raise ValueError(f"Borrowing cash flow differs from Company Facts for {line['line']}")
    return {**source, "source": receipt["url"], "sha256": receipt["sha256"], "title": title,
            "operating": scaled(cfo[column], money), "financing": scaled(total[column], money), "lines": lines}


def borrowing_cash_facts(report, period, evidence):
    lines = evidence["lines"]
    cfo = period["facts"]["cfo"]
    if ((period["period_kind"], period["filing"], period["end"]) != ("annual", report["accession"], report["end"])
            or (cfo["start"], cfo["unit"], cfo["url"], cfo["filed"], cfo["value"]) != (
                period["start"], period["currency"], report["url"], report["filed"], evidence["operating"])
            or not TITLE.fullmatch(evidence["title"]) or not valid_table_source(evidence, report)
            or not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])
            or any(not line["line"] or not line["tag"] or type(line["value"]) is not int for line in lines)
            or len({(line["line"], line["tag"]) for line in lines}) != len(lines)
            or type(evidence["financing"]) is not int or sum(x["value"] for x in lines) != evidence["financing"]):
        raise ValueError("Borrowing cash flow does not reconcile to the consolidated financing subtotal")
    keys = {
        "borrowing": "debt_net", "lease": "lease_principal_paid", "costs": "debt_issuance_cost_paid",
        "asset": "financed_asset_principal_paid", "obligations": "financing_obligation_principal_paid",
        "prepayment": "finance_lease_prepayment_paid", "collateral": "financing_collateral_cash",
        "other_financing": "financing_other_balance_sheet_cash", "rounding": "financing_note_rounding_difference",
    }
    groups = {k: [] for k in (*keys, "unallocated", "other")}
    original = None
    if "allocation_note" in evidence:
        original, parts = borrowing_notes.allocate_note(report, period, evidence)
        if (role(original["tag"], original["line"], original["value"]) != "unallocated"
                or sum(part["value"] for _, part in parts) != original["value"]):
            raise ValueError("Borrowing note components do not allocate the mixed statement line")
        for kind, part in parts:
            groups[kind].append(part)
    for line in lines:
        if line is not original:
            groups[role(line["tag"], line["line"], line["value"])].append(line)
    if not any(groups[k] for k in (*keys, "unallocated")):
        raise ValueError("No classified debt or lease cash flow on the financing statement")
    facts = {}
    if groups["unallocated"]:
        keys["borrowing"] = "debt_net_identified"
    provenance = {k: evidence[k] for k in ("source", "sha256", "table_url", "table_sha256_16")}
    if "table_kind" in evidence:
        provenance["table_kind"] = evidence["table_kind"]
    for group, key in keys.items():
        if not groups[group]:
            continue
        sign = -1 if group in {"lease", "costs", "asset", "obligations", "prepayment"} else 1
        facts[key] = {**provenance, **{k: report[k] for k in ("url", "filed", "form", "accession")},
                      "start": period["start"], "unit": period["currency"], "tag": TAG,
                      "value": sign * sum(x["value"] for x in groups[group]),
                      "locator": "Consolidated financing cash flows",
                      "components": [{**x, "sign": sign} for x in groups[group]]}
    return facts, groups["unallocated"]


def enrich_borrowing_cash(cache, obj, cik, report, period):
    evidence = extract(cache, obj, cik, report, period)
    facts, pending = borrowing_cash_facts(report, period, evidence)
    gap = {}
    if borrowing_notes.candidate(cik, pending):
        try:
            scoped = {**evidence, "allocation_note": borrowing_notes.read_note(cache, cik, report)}
            facts, pending = borrowing_cash_facts(report, period, scoped)
            evidence = scoped
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            gap["borrowing_note_gap"] = str(exc)
    return {**period, **gap, "facts": {**period["facts"], **facts}, "annual_borrowing_cash": evidence,
            "borrowing_cash_pending": pending}
