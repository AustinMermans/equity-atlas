"""Reconcile annual note totals and components to facts from the same accession."""

from dataclasses import dataclass
from datetime import date
import re

from .facts import exact_sec_amount
from .fetch import SEC
from .rendered_filing import ENDPOINT, filing_tables, scaled

TAG = "disclosed:ReconciledAnnualNote"
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
    (51143, "10-K"): {
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
        OTHER: Note(
            "Management discussion · Other income and expense, rounded to $100 million",
            "Litigation Employee benefit plan Monetization royalty rights Other Income Expense Net",
            OTHER_NONOPERATING, "Total Other (Income) Expense, Net", (
                "Litigation related (1)", "Employee benefit plan related", "Changes in the fair value of securities (2)",
                "Acquisition, Integration and Divestiture related (3)", "Monetization of royalty rights", "Other",
            ), scale=1_000_000_000, date_format="{year}", rounding_increment=100_000_000,
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
            ),
        ),
    },
}
PINNED = {
    (2809, "0001104659-26-032153"),
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


def reconciles(note, total, amounts, anchor):
    rounding = note.rounding_increment
    anchored = note.anchor_sign * (amounts[note.anchor_line] if note.anchor_line else total)
    return (
        abs(anchored - anchor) <= rounding // 2 and
        abs(sum(amounts.values()) - total) <= (len(amounts) + 1) * rounding // 2 and
        (not rounding or all(value % rounding == 0 for value in (total, *amounts.values())))
    )


def note_components(cache, cik, report, note, anchor):
    tables, receipts, receipt = filing_tables(cache, cik, report, note.query, note.document)
    url = note_url(report, note)
    digest = receipts.get(url, "")
    if not re.fullmatch(r"[0-9a-f]{16}", digest):
        raise ValueError("Missing note document checksum")
    end = date.fromisoformat(report["end"])
    year = note.date_format.format(month=end.strftime("%B"), day=end.day, year=end.year)
    matches = []
    for table in tables:
        if (table["source"] != "document table" or table.get("url") != url or
                table["columns"].count(year) != 1 or
                (note.title_phrase and note.title_phrase not in (table.get("title") or "").lower())):
            continue
        index = table["columns"].index(year)
        try:
            total = amount_in_note(table["rows"], note.total, index, note.scale)
            amounts = {label: amount_in_note(table["rows"], label, index, note.scale) for label in note.lines}
        except ValueError:
            continue
        if reconciles(note, total, amounts, anchor):
            matches.append((total, amounts))
    if len(matches) != 1:
        raise ValueError(f"Missing unique reconciled full-year table for {note.heading}")
    total, amounts = matches[0]
    parts = [{"line": label, "value": abs(value), "sign": -1 if value < 0 else 1, "table_url": url}
             for label, value in amounts.items()]
    fact = {"value": total, "table_url": url, "table_sha256_16": digest, "sha256": receipt["sha256"],
            "components": parts}
    if note.rounding_increment:
        fact["rounding_increment"] = note.rounding_increment
    return fact


def enrich_notes(cache, obj, meta, cik, report, statement):
    if ((statement["period_kind"], statement["filing"], statement["end"], statement["currency"]) !=
            ("annual", report["accession"], report["end"], "USD") or meta["url"] != SEC.format(cik)):
        raise ValueError("Annual note scope does not match the selected statement")
    facts = statement["facts"].copy()
    for field, note in notes_for(cik, report).items():
        anchor = exact_sec_amount(obj, statement, report, note.anchor)
        if anchor is None:
            raise ValueError(f"Missing exact Company Facts anchor for {note.heading}")
        facts[field] = {
            **note_components(cache, cik, report, note, anchor),
            "tag": TAG, "unit": "USD", "start": statement["start"], "source": ENDPOINT,
            "form": report["form"], "filed": report["filed"], "accession": report["accession"], "url": report["url"],
            "locator": note.heading, "anchor_tag": note.anchor, "anchor_value": anchor, "anchor_sha256": meta["sha256"],
        }
    return {**statement, "facts": facts}


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
    return (
        (period["period_kind"], period["filing"], period["end"], period["currency"]) ==
        ("annual", report["accession"], report["end"], "USD") and
        (fact["accession"], fact["form"], fact["filed"], fact["url"], fact["unit"], fact["start"]) ==
        (report["accession"], report["form"], report["filed"], report["url"], "USD", period["start"]) and
        fact["source"] == ENDPOINT and fact["table_url"] == url and fact["locator"] == note.heading and
        bool(re.fullmatch(r"[0-9a-f]{16}", fact.get("table_sha256_16", ""))) and
        all(re.fullmatch(r"[0-9a-f]{64}", fact.get(k, "")) for k in ("sha256", "anchor_sha256")) and
        fact["anchor_tag"] == note.anchor and type(fact["anchor_value"]) is int and
        fact.get("rounding_increment", 0) == note.rounding_increment and
        reconciles(note, fact["value"], amounts, fact["anchor_value"])
    )
