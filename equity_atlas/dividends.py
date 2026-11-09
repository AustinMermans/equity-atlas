"""Read annual cash distributions without collapsing distinct recipients."""

from datetime import date, datetime
import re

from .capex import FINANCING_TOTALS
from .facts import annual_rule_key, exact_sec_amount, recurring_annual_rules
from .parent_equity import closing_label
from .rendered_filing import (ENDPOINT, annual_table, decode_response, filing_tables, request_bytes,
                              scaled, table_belongs_to_filing, valid_table_source)

COMMON = "derived:PaymentsOfOrdinaryShareDividends"
TAG = "derived:FiledCashDistributions"
PARENT = "ifrs-full:DividendsPaidToEquityHoldersOfParentClassifiedAsFinancingActivities"
NCI = "ifrs-full:DividendsPaidToNoncontrollingInterestsClassifiedAsFinancingActivities"
IFRS = "ifrs-full:"
US = "us-gaap:"
OPERATING = {IFRS + "CashFlowsFromUsedInOperatingActivities", US + "NetCashProvidedByUsedInOperatingActivities"}
FINANCING_START = {tag + "Abstract" for tag in FINANCING_TOTALS}
CIBC = (1045520, "0001193125-25-307488")
HDFC = (1144967, "0001193125-26-322004")
SONY = (313838, "0001193125-26-274893")
BTI = (1303523, "0001303523-26-000017")
SNY = (1121404, "0001628280-26-008403")
UBS = (1610520, "0001610520-26-000023")
BLK = (2012383, "0001193125-26-071966")
RY = (1000275, "0001193125-25-305927")
MILLION = 1_000_000
PROFILES = {
    BTI: ("GBP", "Group Cash Flow Statement", (
        ("div", PARENT, "Dividends paid to owners of the parent"),
        ("div_nci", NCI, "Dividends paid to non-controlling interests"),
        ("div_hybrid_paid", "bti:PaymentOfCoupons", "Coupon paid on perpetual hybrid bonds"),
    )),
    SNY: ("EUR", "Consolidated statements of cash flows", (
        ("div", PARENT, "to shareholders of Sanofi"),
        ("div_nci_excluding_bms", NCI, "to non-controlling interests, excluding BMS"),
    )),
    UBS: ("USD", "Consolidated Statement of Cash Flows", (
        ("div", PARENT, "Distributions paid on UBS shares"),
    )),
    CIBC: ("CAD", "Consolidated statement of cash flows", (
        ("div_mixed_distributions", PARENT, "Dividends and distributions paid"),
    )),
    RY: ("CAD", "Consolidated Statements of Cash Flows", (
        ("div_mixed_distributions", "ry:DividendsPaidOnSharesAndDistributionsPaidOnOtherEquityInstrumentsClassifiedAsFinancingActivities",
         "Dividends paid on shares and distributions paid on other equity instruments"),
        ("div_nci", NCI, "Dividends/distributions paid to non-controlling interests"),
    )),
    BLK: ("USD", "Consolidated Statements of Cash Flows", (
        ("div_mixed_distributions", "blk:DividendsOrSubcoDistributionsPaid", "Dividends/Subco distributions paid"),
    )),
    HDFC: ("INR", "CONSOLIDATED STATEMENTS OF CASH FLOWS ₨ in Millions,", (
        ("div_total", US + "PaymentsOfDividends", "Payment of dividends"),
    )),
    SONY: ("JPY", "Consolidated Statements of Cash Flows", (
        ("div_total", IFRS + "DividendsPaidClassifiedAsFinancingActivities", "Dividends paid"),
    )),
}
RECURRING = recurring_annual_rules(PROFILES)
CIBC_NOTE = "Common and preferred shares and other equity instruments - Summary of Outstanding Shares and Dividends Paid (Detail)"
CIBC_MEMBERS = {
    "div": "Common shares [member]",
    "div_preferred_paid": "Preference shares [member]",
    "div_hybrid_paid": "Other equity Instruments [member]",
}
SONY_QUERY = "Total amount of dividends"
SONY_NOTE = "SONY GROUP CORPORATION AND CONSOLIDATED SUBSIDIARIES / For the fiscal year ended "
SONY_COLUMNS = ["line", "Type of shares", "Total amount of dividends (Yen in millions)", "Source of dividends",
                "Dividends per share (Yen)", "Record date", "Effective date"]
HDFC_EQUITY = ("INR (₨) shares", "Total HDFC Bank Limited Shareholders' Equity INR (₨)", "Noncontrolling Interest INR (₨)")


def rule_key(cik, report):
    return annual_rule_key(cik, report, PROFILES, RECURRING)


def supported(cik, report):
    return rule_key(cik, report) in PROFILES


def source_evidence(receipt, url, digest):
    return {"source": receipt["url"], "sha256": receipt["sha256"], "table_url": url, "table_sha256_16": digest}


def valid_source(source, report, document=False):
    return bool(re.fullmatch(r"[0-9a-f]{64}", source["sha256"]) and
                (source["source"] == ENDPOINT and source["table_url"] == report["url"]
                 and re.fullmatch(r"[0-9a-f]{16}", source["table_sha256_16"])
                 if document else valid_table_source(source, report)))


def extract_cash(cache, cik, report, period, key, obj):
    currency, title, fields = PROFILES[key]
    table, index, receipt, source = annual_table(cache, cik, report, period, "cash_flow", title, pinned_scale=MILLION)
    if period["currency"] != currency:
        raise ValueError("Unexpected dividend reporting currency")
    rows = table["rows"]
    headers = {"sny:DividendsPaidAbstract"} if key == SNY else FINANCING_START
    begin, = (i for i, r in enumerate(rows) if r[1] in headers and r[index] is None)
    ends = FINANCING_TOTALS | {IFRS + "CashFlowsFromUsedInFinancingActivitiesContinuingOperations"}
    end = next((i for i, r in enumerate(rows) if i > begin and r[1] in ends and type(r[index]) in (int, float)), None)
    if end is None:
        raise ValueError("Missing financing cash-flow subtotal")
    operating, = (scaled(r[index], MILLION) for r in rows[:begin] if r[1] in OPERATING and type(r[index]) in (int, float))
    payments = {}
    for field, tag, label in fields:
        outflow, = (r[index] for r in rows[begin+1:end] if r[:2] == [label, tag] and type(r[index]) in (int, float))
        value = -scaled(outflow, MILLION)
        exact = exact_sec_amount(obj, period, report, tag)
        if exact is not None and exact != value:
            raise ValueError(f"Dividend differs between Company Facts and the financing line {label}")
        payments[field] = value
    return {**source, "source": receipt["url"], "sha256": receipt["sha256"], "operating": operating,
            "payments": payments}


def cibc_note(cache, cik, report):
    query = "Dividends and distributions paid"
    tables, digests, receipt = filing_tables(cache, cik, report, query)
    end = date.fromisoformat(report["end"])
    column = f"12 Months Ended {end:%b}. {end.day}, {end.year} CAD ($) $ / shares shares"
    table, = (t for t in tables if t["source"] == "xbrl report" and t["title"] == CIBC_NOTE
              and t["units"] == "$ in Millions" and t["columns"].count(column) == 2
              and table_belongs_to_filing(t["url"], report))
    first = table["columns"].index(column)
    column_indices = [i for i, c in enumerate(table["columns"]) if c == column]
    if column_indices != [first, first + 1]:
        raise ValueError("Unexpected CIBC paired dividend note columns")
    amounts = {}
    scope = None
    for row in table["rows"]:
        if "[member]" in row[0].casefold() and row[first] is None:
            scope = row[0]
        if row[0] == query and scope in CIBC_MEMBERS.values():
            if scope in amounts or row[first + 1] is not None:
                raise ValueError("Ambiguous CIBC dividend scope")
            amounts[scope] = scaled(row[first], MILLION)
    payments = {field: amounts[member] for field, member in CIBC_MEMBERS.items()}
    return {**source_evidence(receipt, table["url"], digests.get(table["url"], "")), "payments": payments}


def sony_note(cache, cik, report):
    tables, digests, receipt = filing_tables(cache, cik, report, SONY_QUERY)
    end = date.fromisoformat(report["end"])
    title = SONY_NOTE + f"{end:%B} {end.day}, {end.year}"
    table, = (t for t in tables if t["source"] == "document table" and t["url"] == report["url"]
              and t["title"] == title and t["columns"] == SONY_COLUMNS)
    payments = []
    for row in table["rows"]:
        if row[1] != "Common stock" or row[3] != "Retained earnings" or not row[0].startswith("Board of Directors "):
            raise ValueError("Unreviewed Sony dividend payment scope")
        paid = datetime.strptime(row[6], "%B %d, %Y").date().isoformat()
        payments.append({"paid": paid, "value": scaled(row[2], MILLION)})
    return {**source_evidence(receipt, report["url"], digests.get(report["url"], "")), "payments": payments}


def hdfc_equity(cache, cik, report):
    req = request_bytes(f"{cik:010d}", "annual", report["accession"], "equity")
    raw, receipt = cache.get(ENDPOINT, 8760, post_json=req)
    data, digests = decode_response(raw, receipt, report, cik, "annual")
    table = data["equity"]
    url, = table["sources"]
    cols = table["columns"]
    if (table["title"] != "CONSOLIDATED STATEMENTS OF SHAREHOLDERS' EQUITY ₨ in Millions,"
            or (table["currency"], table["money_scale"]) != ("INR", MILLION)
            or any(cols.count(col) != 1 for col in HDFC_EQUITY)):
        raise ValueError("Unexpected HDFC equity statement units or columns")
    rows = table["rows"]
    i, = (i for i, row in enumerate(rows) if closing_label(row[0], report["end"]) and
          row[1] == US + "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
    preceding = max(j for j, row in enumerate(rows[:i]) if row[1] == rows[i][1])
    payment, = (row for row in rows[preceding+1:i] if row[:2] == ["Dividends", US + "DividendsCommonStock"])
    indices = [cols.index(col) for col in HDFC_EQUITY]
    if "" in cols:
        # The rendered FY2026 header includes a spacer after statutory reserves.
        spacer, = (j for j, col in enumerate(cols) if col == "")
        if (cols[spacer-1:spacer+2] != ["Statutory Reserve USD ($) (USD)", "",
                                       "Accumulated Other Comprehensive Income/ (Loss) INR (₨)"]
                or any(len(row) != len(cols) or row[-1] is not None for row in (rows[i], payment))):
            raise ValueError("Unexpected spacer in HDFC currency columns")
        indices = [j - (j > spacer) for j in indices]
    if any(not isinstance(rows[i][j], str) or not rows[i][j].startswith("₨ ") for j in indices):
        raise ValueError("Missing HDFC closing INR equity cells")
    return {**source_evidence(receipt, url, digests.get(url, "")),
            "closing": [money_inr(rows[i][j]) for j in indices], "payments": [-money_inr(payment[j]) for j in indices]}


def money_inr(value):
    if isinstance(value, str) and value.startswith("₨ "):
        value = value.removeprefix("₨ ").replace(",", "")
    return scaled(value, MILLION)


def dividend_facts(cik, report, period, evidence):
    key = rule_key(cik, report)
    currency, _, fields = PROFILES[key]
    cash = evidence["cash"]
    note = evidence.get("note")
    payments = cash["payments"]
    tolerance = MILLION // 2 if key == HDFC else 0
    facts = period["facts"]
    cfo = facts["cfo"]
    if ((period["period_kind"], period["filing"], period["end"], period["currency"]) !=
            ("annual", report["accession"], report["end"], currency)
            or (cfo["filed"], cfo["url"], cfo["start"], cfo["unit"]) !=
            (report["filed"], report["url"], period["start"], currency)
            or abs(cfo["value"] - cash["operating"]) > tolerance or not valid_source(cash, report)
            or payments.keys() != {field for field, _, _ in fields}
            or any(type(v) is not int or v < 0 for v in payments.values())):
        raise ValueError("Unverified annual dividend statement or cash-flow anchor")
    result = {}

    def save(field, value, source, label, parts=None):
        if type(value) is not int or value < 0:
            raise ValueError("Invalid dividend amount")
        fact = {k: source[k] for k in ("source", "sha256", "table_url", "table_sha256_16")}
        fact.update(value=value, unit=currency, start=period["start"], locator=label,
                    tag=COMMON if field == "div" else TAG, **{k: report[k] for k in ("url", "filed", "form", "accession")})
        if parts:
            fact["components"] = parts
        result[field] = fact

    for field, _, label in fields:
        if field == "div_total":
            if "div_total" in facts and facts["div_total"]["tag"] != TAG:
                total = facts["div_total"]
                if (total["url"] != report["url"] or total["filed"] != report["filed"] or total["unit"] != currency
                        or total["start"] != period["start"] or abs(total["value"] - payments[field]) > tolerance):
                    raise ValueError("Cash-flow dividend disagrees with the exact annual total")
            else:
                save(field, payments[field], cash, label)
        else:
            if field == "div" and any(facts.get(k, {}).get("value", 0) > 0 for k in ("preferred", "preferred_and_other_equity")):
                raise ValueError("Parent dividend line needs a separate preferred allocation")
            save(field, payments[field], cash, label)

    if key in {CIBC, SONY, HDFC} and (not note or not valid_source(note, report, document=key == SONY)):
        raise ValueError("Unverified annual dividend note")
    if key == CIBC:
        if note["payments"].keys() != CIBC_MEMBERS.keys() or sum(note["payments"].values()) != payments["div_mixed_distributions"]:
            raise ValueError("CIBC common, preferred and capital note distributions do not sum to financing cash flow")
        for field, scope in CIBC_MEMBERS.items():
            save(field, note["payments"][field], note, "Paid distributions note · " + scope.removesuffix(" [member]"))
    elif key == SONY:
        schedule = note["payments"]
        if not schedule or len({part["paid"] for part in schedule}) != len(schedule) or any(
                not period["start"] <= part["paid"] <= period["end"] or type(part["value"]) is not int or part["value"] < 0
                for part in schedule):
            raise ValueError("Sony paid dividends are outside the fiscal year or duplicate")
        common = sum(part["value"] for part in schedule)
        save("div", common, note, "Common stock cash dividends in the fiscal-year payment schedule",
             [{"line": f"Effective {part['paid']}", "value": part["value"], "sign": 1,
               "table_url": note["table_url"]} for part in schedule])
        save("div_unallocated_cash_difference", payments["div_total"] - common, cash,
             "Consolidated dividend cash outflow less the common stock payment schedule")
    elif key == HDFC:
        closing = [facts[field]["value"] for field in ("total_equity", "book", "minority")]
        if note["closing"] != closing or closing[0] != closing[1] + closing[2]:
            raise ValueError("HDFC closing parent and noncontrolling equity columns do not reconcile")
        consolidated, parent_displayed, minority_paid = note["payments"]
        cash_total = facts.get("div_total", result.get("div_total"))["value"]
        common = cash_total - minority_paid
        if abs(consolidated - cash_total) > tolerance or abs(parent_displayed - common) > tolerance:
            raise ValueError("HDFC equity dividend split does not match cash dividends paid")
        # Require the independently recovered precision of the selected workbook for this split.
        if facts.get("div_total", {}).get("tag") != "sec_workbook:PaymentsOfDividends":
            raise ValueError("Exact consolidated HDFC dividend cash payment unavailable")
        save("div_nci", minority_paid, note, "Noncontrolling interest dividend column")
        save("div", common, note, "Consolidated cash dividends less noncontrolling interest dividends",
             [{"line": "Consolidated cash dividends paid", "value": cash_total, "sign": 1, "table_url": facts["div_total"]["url"]},
              {"line": "Cash dividends paid to noncontrolling interests", "value": minority_paid, "sign": -1,
               "table_url": note["table_url"]}])
    return result


def enrich_dividends(cache, obj, cik, report, period):
    key = rule_key(cik, report)
    evidence = {"cash": extract_cash(cache, cik, report, period, key, obj)}
    parser = {CIBC: cibc_note, SONY: sony_note, HDFC: hdfc_equity}.get(key)
    if parser:
        evidence["note"] = parser(cache, cik, report)
    recovered = dividend_facts(cik, report, period, evidence)
    return {**period, "facts": {**period["facts"], **recovered}, "annual_dividends": evidence}
