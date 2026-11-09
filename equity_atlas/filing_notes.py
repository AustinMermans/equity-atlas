"""Reconcile annual note totals and components to facts from the same accession."""

from dataclasses import dataclass
from datetime import date
import re

from .facts import exact_sec_amount
from .fetch import SEC
from .rendered_filing import ENDPOINT, filing_tables, scaled

TAG = "disclosed:ReconciledAnnualNote"
LINE_TAG = "disclosed:ReconciledAnnualNoteLine"
PRETAX = "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
IBM_SEGMENT_BRIDGE = "ibm_segment_profit_bridge"
IBM_SEGMENT_NOTE = "ibm_segment_profit_note"
IBM_DEBT_NOTE = "ibm_debt_split_note"
GE_INSURANCE_NOTE = "ge_insurance_income_note"
OTHER_NONOPERATING = "us-gaap:OtherNonoperatingIncomeExpense"
OTHER = "other_income_expense_note"
DERIVATIVES = "derivative_gain_loss_note"


@dataclass(frozen=True)
class Note:
    heading: str
    query: str
    anchor: str
    total: str
    lines: tuple[str, ...]
    scale: int = 1_000_000
    date_format: str = "Year Ended {month} {day}, {year}"
    document: str | None = None
    document_filename: str | None = None
    title_phrase: str | None = None
    anchor_line: str | None = None
    anchor_sign: int = -1
    rounding_increment: int = 0
    outputs: tuple[tuple[str, str], ...] = ()
    stock: bool = False
    anchor_tags: tuple[str, ...] = ()
    headers: tuple[str, ...] = ()
    segment_row: str | None = None
    anchor_note: str | None = None
    deductions: tuple[str, ...] = ()


PROFILES = {
    (2809, "40-F"): {
        OTHER: Note(
            "Note 22 · Other income and expenses", "Total other income and expenses",
            "ifrs-full:OtherOperatingIncomeExpense", "Total other income and expenses", (
                "Loss on disposal of property, plant and mine development (Note 9)", "Interest income",
                "Environmental remediation", "Loss on sale of equity securities", "Other",
            ), scale=1_000, document="EX-99.2", document_filename="aem-{date}xex99d2.htm",
        ),
        DERIVATIVES: Note(
            "Note 21 · Gains and losses on derivative financial instruments", "Unrealized gain on warrants",
            "ifrs-full:GainsLossesOnChangeInFairValueOfDerivatives", "(Gain) loss on derivative financial instruments", (
                "Premiums realized on written foreign exchange call options", "Unrealized gain on warrants",
                "Realized loss on currency and commodity derivatives", "Unrealized (gain) loss on currency and commodity derivatives",
            ), scale=1_000, document="EX-99.2", document_filename="aem-{date}xex99d2.htm",
        ),
    },
    (14272, "10-K"): {
        OTHER: Note(
            "Note 5 · Other (income)/expense, net",
            "interest royalty investment restructuring litigation debt contingent integration acquisition other",
            OTHER_NONOPERATING, "Other (income)/expense, net", (
                "Interest expense", "Royalty income - divestitures (Note 4)", "Royalty and licensing income (Note 4)",
                "Investment income", "Provision for restructuring (Note 6)", "Litigation and other settlements (a)",
                "Loss on debt redemption (Note 10)", "Contingent consideration (Note 9)",
                "Equity investment (gains)/losses, net (Note 9)", "Integration expenses (Note 6)",
                "Acquisition expense", "Other (b)",
            ), outputs=(
                ("divestiture_royalty_expense_income", "Royalty income - divestitures (Note 4)"),
                ("royalty_licensing_expense_income", "Royalty and licensing income (Note 4)"),
                ("loss_on_debt_redemption", "Loss on debt redemption (Note 10)"),
            ),
        ),
    },
    (310158, "10-K"): {
        OTHER: Note(
            "Note 14 · Other (income) expense, net", "Other (income) expense, net",
            OTHER_NONOPERATING, "", (
                "Interest income", "Interest expense", "Exchange losses", "Income from investments in equity securities, net (1)",
                "Net periodic defined benefit plan (credit) cost other than service cost", "Other, net",
            ), date_format="{year}",
        ),
    },
    (40545, "10-K"): {
        GE_INSURANCE_NOTE: Note(
            "Management discussion · Run-off insurance net income",
            "Insurance net income (loss) (net of tax)", PRETAX,
            "Less: Insurance net income (loss) (net of tax) (Note 12)", (
                "Insurance net income (loss) (pre-tax)",
                "Tax effect on Insurance net income (loss)(a)",
            ), anchor_line="Income from continuing operations before taxes (GAAP)", anchor_sign=1,
            headers=("line", "Income", "{previous} EPS", "Income", "EPS"),
            outputs=(
                ("runoff_insurance_pretax_income", "Insurance net income (loss) (pre-tax)"),
                ("runoff_insurance_tax_effect", "Tax effect on Insurance net income (loss)(a)"),
            ),
        ),
    },
    (51143, "10-K"): {
        IBM_SEGMENT_BRIDGE: Note(
            "Note D · Reportable segment profit to pretax income",
            "Total reportable segment profit", PRETAX, "Total pre-tax income from continuing operations", (
                "Total reportable segment profit", "Amortization of acquired intangible assets",
                "Acquisition-related charges", "Non-operating retirement-related (costs)/income (2)",
                "Stock-based compensation (3)", "Net interest excluding the Financing segment",
                "Workforce rebalancing charges (3)", "Other-divested businesses (4)",
                "Unallocated corporate amounts and other (5)",
            ), date_format="{year}", document="EX-13", document_filename="ibm-{date}_d2.htm",
            anchor_sign=1, rounding_increment=1_000_000, outputs=(
                ("ibm_reportable_segment_profit", "Total reportable segment profit"),
                ("ibm_net_interest_ex_financing", "Net interest excluding the Financing segment"),
                ("ibm_nonoperating_retirement_income", "Non-operating retirement-related (costs)/income (2)"),
            ),
        ),
        IBM_SEGMENT_NOTE: Note(
            "Note D · Profit by reportable segment", "Segment profit", "Total reportable segment profit",
            "Segments", ("Software", "Consulting", "Infrastructure", "Financing (1)"),
            date_format="{year}", document="EX-13", document_filename="ibm-{date}_d2.htm",
            title_phrase="management system segment view", anchor_sign=1, rounding_increment=1_000_000,
            segment_row="Segment profit", anchor_note=IBM_SEGMENT_BRIDGE, outputs=(
                ("ibm_software_segment_profit", "Software"),
                ("ibm_consulting_segment_profit", "Consulting"),
                ("ibm_infrastructure_segment_profit", "Infrastructure"),
                ("ibm_financing_segment_profit", "Financing (1)"),
            ),
        ),
        IBM_DEBT_NOTE: Note(
            "Management discussion · Financing and non-Financing debt", "Non-Financing debt",
            "us-gaap:LongTermDebtAndCapitalLeaseObligationsCurrent", "Total debt", (
                "Financing segment debt (1)", "Non-Financing debt",
            ), date_format="{year}", document="EX-13", document_filename="ibm-{date}_d2.htm",
            anchor_sign=1, stock=True, rounding_increment=1_000_000,
            anchor_tags=("us-gaap:LongTermDebtNoncurrent",), outputs=(
                ("ibm_financing_debt", "Financing segment debt (1)"),
                ("ibm_nonfinancing_debt", "Non-Financing debt"),
            ),
        ),
        OTHER: Note(
            "Note F · Other income and expense", "Total other (income) and expense retirement-related",
            "us-gaap:InterestIncomeOther", "Total other (income) and expense", (
                "(Gains)/losses on foreign currency transactions (1)", "(Gains)/losses on derivative instruments (1)",
                "Interest income", "Net (gains)/losses from securities and investment assets",
                "Retirement-related costs/(income) (2)", "Other (3)",
            ), date_format="{year}", document="EX-13", document_filename="ibm-{date}_d2.htm",
            title_phrase="components of other (income) and expense", anchor_line="Interest income",
        ),
    },
    (200406, "10-K"): {
        "jnj_segment_pretax_bridge": Note(
            "Management discussion · Segment and worldwide income before tax",
            "not allocated to segments", PRETAX, "Worldwide income before tax", (
                "Innovative Medicine", "MedTech", "(Income) Expenses not allocated to segments (2)",
            ), date_format="Income Before Tax {year}", anchor_sign=1, title_phrase="income before tax by segment",
            deductions=("(Income) Expenses not allocated to segments (2)",), outputs=(
                ("jnj_innovative_medicine_pretax", "Innovative Medicine"),
                ("jnj_medtech_pretax", "MedTech"),
                ("jnj_unallocated_expense_income", "(Income) Expenses not allocated to segments (2)"),
            ),
        ),
        OTHER: Note(
            "Management discussion · Other income and expense, rounded to $100 million",
            "Litigation Employee benefit plan Monetization royalty rights Other Income Expense Net",
            OTHER_NONOPERATING, "Total Other (Income) Expense, Net", (
                "Litigation related (1)", "Employee benefit plan related", "Changes in the fair value of securities (2)",
                "Acquisition, Integration and Divestiture related (3)", "Monetization of royalty rights", "Other",
            ), scale=1_000_000_000, date_format="{year}", rounding_increment=100_000_000, outputs=(
                ("litigation_expense_income_rounded", "Litigation related (1)"),
                ("employee_benefit_expense_income_rounded", "Employee benefit plan related"),
                ("securities_fair_value_expense_income_rounded", "Changes in the fair value of securities (2)"),
            ),
        ),
    },
    (858877, "10-K"): {
        "amortization_purchased_intangibles_with_impairment": Note(
            "Note 5 · Amortization of purchased intangible assets, including impairment",
            "Cost of sales Operating expenses amortization of purchased intangible assets",
            "us-gaap:AmortizationOfIntangibleAssets", "Total", ("Cost of sales", "Operating expenses"),
            date_format="{month} {day}, {year}",
            title_phrase="amortization of purchased intangible assets, including impairment charges",
            anchor_line="Operating expenses", anchor_sign=1,
        ),
    },
    (78003, "10-K"): {
        OTHER: Note(
            "Note 4 · Other (income)/deductions, net", "Net periodic benefit costs",
            OTHER_NONOPERATING, "Other (income)/deductions--net", (
                "Interest income", "Interest expense (a)", "Net (gains)/losses recognized during the period on equity securities (b)",
                "Income from collaborations, out-licensing arrangements and sales of compound/product rights",
                "Net periodic benefit costs/(credits) other than service costs", "Certain legal matters, net (c)",
                "Certain asset impairments (d)", "Haleon equity method (income)/loss (e)", "Other, net (f)",
            ), outputs=(
                ("asset_impairments_in_other_expense", "Certain asset impairments (d)"),
                ("litigation_in_other_expense", "Certain legal matters, net (c)"),
                ("collaboration_licensing_expense_income",
                 "Income from collaborations, out-licensing arrangements and sales of compound/product rights"),
            ),
        ),
    },
}
PINNED = {
    (2809, "0001104659-26-032153"),
    (40545, "0000040545-26-000008"),
    (14272, "0000014272-26-000004"),
    (310158, "0000310158-26-000063"),
    (78003, "0000078003-26-000026"),
    (858877, "0000858877-26-000132"),
    (51143, "0000051143-26-000010"),
    (200406, "0000200406-26-000016"),
}


def notes_for(cik, report):
    return PROFILES.get((cik, report["form"]), {})


def note_url(report, note):
    if note.document_filename:
        filename = note.document_filename.format(date=report["end"].replace("-", ""))
        return f"{report['path']}/{filename}"
    return report["url"]


def amount_in_note(rows, label, column, scale):
    values = {row[column] for row in rows if row[0] == label}
    if len(values) != 1:
        raise ValueError(f"Missing or ambiguous note line {label}")
    value = values.pop()
    if value in ("-", "–", "—"):
        return 0
    if type(value) not in (int, float):
        raise ValueError(f"Invalid amount for note line {label}")
    return scaled(value, scale)


def reconciles(note, total, amounts, anchor, reported_anchor=None):
    rounding = note.rounding_increment
    if note.anchor_line:
        reported = amounts.get(note.anchor_line, reported_anchor)
    else:
        reported = total
    if type(reported) is not int:
        return False
    anchored = note.anchor_sign * reported
    return (
        abs(anchored - anchor) <= rounding // 2 and
        abs(sum(-amount if line in note.deductions else amount for line, amount in amounts.items()) - total)
        <= (len(amounts) + 1) * rounding // 2 and
        (not rounding or all(value % rounding == 0 for value in (total, *amounts.values())))
    )


def segment_rows(table, note, year):
    """Normalize a segment-by-column layout to the standard note rows."""
    rows = table["rows"]
    breaks = [(index, row[1]) for index, row in enumerate(rows) if not row[0] and type(row[1]) is int]
    if [value for _, value in breaks] != [year - 1, year - 2]:
        raise ValueError("Unexpected segment comparative years")
    row, = [r for r in rows[:breaks[0][0]] if r[0] == note.segment_row]
    return list(zip((*note.lines, note.total), row[2:], strict=True))


def note_components(cache, cik, report, note, anchor):
    tables, receipts, receipt = filing_tables(cache, cik, report, note.query, note.document)
    url = note_url(report, note)
    digest = receipts.get(url, "")
    if not re.fullmatch(r"[0-9a-f]{16}", digest):
        raise ValueError("Missing note document checksum")
    end = date.fromisoformat(report["end"])
    year = note.date_format.format(month=end.strftime("%B"), day=end.day, year=end.year)
    headers = [h.format(previous=end.year - 1) for h in note.headers]
    if note.segment_row:
        headers = ["line", "", *note.lines, note.total]
    matches = []
    for table in tables:
        if (table["source"] != "document table" or table.get("url") != url or
                (table["columns"] != headers if headers else table["columns"].count(year) != 1) or
                (note.title_phrase and note.title_phrase not in (table.get("title") or "").lower())):
            continue
        index = 1 if headers else table["columns"].index(year)
        try:
            rows = segment_rows(table, note, end.year) if note.segment_row else table["rows"]
            total = amount_in_note(rows, note.total, index, note.scale)
            amounts = {label: amount_in_note(rows, label, index, note.scale) for label in note.lines}
            reported_anchor = (amount_in_note(rows, note.anchor_line, index, note.scale)
                               if note.anchor_line and note.anchor_line not in amounts else None)
        except ValueError:
            continue
        if reconciles(note, total, amounts, anchor, reported_anchor):
            matches.append((total, amounts, reported_anchor))
    if len(matches) != 1:
        raise ValueError(f"Missing unique reconciled full-year table for {note.heading}")
    total, amounts, reported_anchor = matches[0]
    parts = [{"line": label, "value": abs(value), "sign": -1 if value < 0 else 1, "table_url": url}
             for label, value in amounts.items()]
    fact = {"value": total, "table_url": url, "table_sha256_16": digest, "sha256": receipt["sha256"],
            "components": parts}
    if reported_anchor is not None:
        fact["anchor_line_value"] = reported_anchor
    if note.rounding_increment:
        fact["rounding_increment"] = note.rounding_increment
    return fact


def enrich_notes(cache, obj, meta, cik, report, statement):
    if ((statement["period_kind"], statement["filing"], statement["end"], statement["currency"]) !=
            ("annual", report["accession"], report["end"], "USD") or meta["url"] != SEC.format(cik)):
        raise ValueError("Annual note scope does not match the selected statement")
    facts = statement["facts"].copy()
    for field, note in notes_for(cik, report).items():
        scope = {**statement, "start": None} if note.stock else statement
        if note.anchor_note:
            parent = facts[note.anchor_note]
            anchor = anchor_note_amount(parent, note)
            anchor_sha256 = parent["sha256"]
        else:
            tags = (note.anchor, *note.anchor_tags)
            amounts = [exact_sec_amount(obj, scope, report, tag) for tag in tags]
            if any(amount is None for amount in amounts):
                raise ValueError(f"Missing exact Company Facts anchor for {note.heading}")
            anchor = sum(amounts)
            anchor_sha256 = meta["sha256"]
        facts[field] = {
            **note_components(cache, cik, report, note, anchor),
            "tag": TAG, "unit": "USD", "start": scope["start"], "source": ENDPOINT,
            "form": report["form"], "filed": report["filed"], "accession": report["accession"], "url": report["url"],
            "locator": note.heading, "anchor_tag": note_anchor_label(note),
            "anchor_value": anchor, "anchor_sha256": anchor_sha256,
        }
    facts.update(note_line_facts(cik, report, facts))
    return {**statement, "facts": facts}


def note_line_facts(cik, report, facts):
    result = {}
    for key, note in notes_for(cik, report).items():
        if key not in facts or not note.outputs:
            continue
        parent = facts[key]
        lines = {part["line"]: part for part in parent["components"]}
        for field, line in note.outputs:
            part = lines[line]
            result[field] = {
                **{k: parent[k] for k in ("unit", "start", "source", "form", "filed", "accession", "url",
                                           "table_url", "table_sha256_16", "sha256")},
                "tag": LINE_TAG, "value": part["sign"] * part["value"],
                "locator": f"{parent['locator']} · {line}", "components": [part],
            }
            if note.rounding_increment >= 100_000_000:
                result[field]["rounding_increment"] = note.rounding_increment
    return result


def note_anchor_label(note):
    if note.anchor_note:
        return f"{note.anchor_note} · {note.anchor}"
    return " + ".join((note.anchor, *note.anchor_tags))


def anchor_note_amount(parent, note):
    part, = [part for part in parent["components"] if part["line"] == note.anchor]
    return part["sign"] * part["value"]


def valid_note(period, report, cik, field, fact):
    note = notes_for(cik, report).get(field)
    if not note:
        return False
    parts = fact.get("components", [])
    url = note_url(report, note)
    if (tuple(part["line"] for part in parts) != note.lines or
            any(part["table_url"] != url or type(part["value"]) is not int or part["value"] < 0 or
                part["sign"] not in (-1, 1) for part in parts)):
        return False
    amounts = {part["line"]: part["sign"] * part["value"] for part in parts}
    facts = period["facts"]
    if note.anchor_note:
        parent = facts.get(note.anchor_note)
        if (not parent or parent["tag"] != TAG or fact["anchor_sha256"] != parent["sha256"]
                or fact["anchor_value"] != anchor_note_amount(parent, note)):
            return False
    elif note.anchor == PRETAX and facts.get("pretax", {}).get("value") != fact["anchor_value"]:
        return False
    elif field == IBM_DEBT_NOTE and fact["anchor_value"] != sum(facts[k]["value"] for k in ("debt_current", "debt_noncurrent")):
        return False
    return (
        (period["period_kind"], period["filing"], period["end"], period["currency"]) ==
        ("annual", report["accession"], report["end"], "USD") and
        (fact["accession"], fact["form"], fact["filed"], fact["url"], fact["unit"], fact["start"]) ==
        (report["accession"], report["form"], report["filed"], report["url"], "USD",
         None if note.stock else period["start"]) and
        fact["source"] == ENDPOINT and fact["table_url"] == url and fact["locator"] == note.heading and
        bool(re.fullmatch(r"[0-9a-f]{16}", fact.get("table_sha256_16", ""))) and
        all(re.fullmatch(r"[0-9a-f]{64}", fact.get(k, "")) for k in ("sha256", "anchor_sha256")) and
        fact["anchor_tag"] == note_anchor_label(note) and
        type(fact["anchor_value"]) is int and
        fact.get("rounding_increment", 0) == note.rounding_increment and
        reconciles(note, fact["value"], amounts, fact["anchor_value"], fact.get("anchor_line_value"))
    )
