"""Allocate a mixed financing line using the selected annual filing's note."""

from datetime import date
import re

from .rendered_filing import ENDPOINT, filing_tables, scaled, table_belongs_to_filing

MILLION = 1_000_000
LEASE_TAG = "us-gaap:FinanceLeasePrincipalPayments"
ALPHABET, COSTCO, EQUINOR = 1652044, 909832, 1140625
RULES = {
    ALPHABET: ("Repayments of debt", "us-gaap:RepaymentsOfDebtAndCapitalLeaseObligations",
               "Financing cash flows used for financing leases", "Leases - Supplemental Cash Flow Information (Details)"),
    COSTCO: ("Financing lease payments and other financing activities, net",
             "cost:FinancingLeasePaymentsAndOtherFinancingActivitiesNet", "Financing cash flows — finance leases",
             "Leases, Supplemental Cash Flow Information (Details)"),
    EQUINOR: ("Net current finance debt and other financing activities",
              "ifrs-full:OtherInflowsOutflowsOfCashClassifiedAsFinancingActivities",
              "Net current finance debt and other finance activities",
              "Finance debt - Reconciliation of cash flow from financing activities to finance line items in balance sheet (Details)"),
}
ALPHABET_SCOPE = re.compile(
    r"financing cash flows used for financ(?:e|ing) leases are included within financing activities"
    r"(?: of the consolidated statements of cash flows)? as repayments of debt", re.I)
COSTCO_SCOPE = "Supplemental cash flow information related to leases was as follows:"
ALPHABET_LEASE = "Financing cash flows used for finance leases"
ALPHABET_PREPAY = "Prepayments for finance leases not yet commenced"
COSTCO_LEASE = "Financing cash flows - finance leases"
EQUINOR_COLUMNS = ("Current finance debt", "Collateral receivables", "Other balance sheet items", "Total")
FINANCING_TOTAL = "Net cash flow from financing activities"


def candidate(cik, lines):
    rule = RULES.get(cik)
    return bool(rule and any((p["line"], p["tag"]) == rule[:2] and p["value"] for p in lines))


def note_amount(rows, label, column):
    value, = (row[column] for row in rows if re.sub(r"\s*\(\d+\)$", "", row[0]) == label)
    if type(value) not in (int, float):
        raise ValueError(f"Non-numeric borrowing note line {label}")
    return scaled(value, MILLION)


def read_note(cache, cik, report):
    label, tag, query, title = RULES[cik]
    tables, digests, receipt = filing_tables(cache, cik, report, query)
    end = date.fromisoformat(report["end"])
    column = f"12 Months Ended {end:%b. %d, %Y}"
    units = "USD ($) $ in Millions"
    candidates = [t for t in tables if t["source"] == "xbrl report" and t["title"] == title
                  and t["units"] == units and t["columns"].count(column) == 1
                  and table_belongs_to_filing(t["url"], report)]
    if not candidates and cik == COSTCO:
        column = str(end.year)
        candidates = [t for t in tables if t["source"] == "document table" and t["url"] == report["url"]
                      and (t["title"] or "").endswith(COSTCO_SCOPE) and t["columns"].count(column) == 1]
    table, = candidates
    index = table["columns"].index(column)
    rows = table["rows"]
    source = {"source": receipt["url"], "sha256": receipt["sha256"],
              "table_url": table["url"], "table_sha256_16": digests.get(table["url"])}
    note = {"table": source, "currency": "USD"}
    if cik == EQUINOR:
        header, = (i for i, r in enumerate(rows) if r[0] == "Current finance debt" and r[index] is None)
        stop, = (i for i, r in enumerate(rows) if i > header and r[0] == "Dividend payable" and r[index] is None)
        current = note_amount(rows[header+1:stop], label, index)
        consolidated_end, = (i for i, r in enumerate(rows[:header])
                              if r[0] == "Non-current finance debt" and r[index] is None)
        aggregate = note_amount(rows[:consolidated_end], label, index)
        total = note_amount(rows[:consolidated_end], FINANCING_TOTAL, index)
        for t in tables:
            if t["source"] != "document table" or t["url"] != report["url"]:
                continue
            names = [re.sub(r" \d+\)$", "", c) for c in t["columns"]]
            if not all(names.count(c) == 1 for c in EQUINOR_COLUMNS):
                continue
            columns = [names.index(c) for c in EQUINOR_COLUMNS]
            components = [note_amount(t["rows"], query, i) for i in columns]
            if components[0] == current and components[-1] == aggregate:
                note.update(document_sha256_16=digests.get(report["url"]), values={
                    "current": current, "collateral": components[1], "other": components[2],
                    "aggregate": aggregate, "financing": total,
                    "document_total": note_amount(t["rows"], FINANCING_TOTAL, columns[-1]),
                })
                break
    else:
        lease = note_amount(rows, ALPHABET_LEASE if cik == ALPHABET else COSTCO_LEASE, index)
        note["values"] = {"lease": lease}
        if cik == ALPHABET:
            footnote, = (t["title"] for t in tables if t["source"] == "document table" and t["url"] == report["url"]
                         and ALPHABET_SCOPE.search(t.get("title") or ""))
            prepay = note_amount(rows, ALPHABET_PREPAY, index) if "prepayments" in footnote.casefold() else 0
            if not prepay and any(r[0] == ALPHABET_PREPAY and r[index] for r in rows):
                raise ValueError("Alphabet prepayments lack a filed scope statement")
            note.update(document_sha256_16=digests.get(report["url"]), scope=footnote)
            note["values"]["prepayment"] = prepay
    return note


def allocate_note(report, period, evidence):
    """Return the original row and its classified replacement components."""
    note = evidence["allocation_note"]
    cik = int(report["path"].split("/")[-2])
    label, tag, _, _ = RULES[cik]
    original, = (r for r in evidence["lines"] if (r["line"], r["tag"]) == (label, tag))
    source = note["table"]
    table_ok = table_belongs_to_filing(source["table_url"], report) or (
        cik == COSTCO and source["table_url"] == report["url"])
    if (note["currency"] != period["currency"] or period["currency"] != "USD"
            or source["source"] != ENDPOINT or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
            or not re.fullmatch(r"[0-9a-f]{16}", source["table_sha256_16"] or "")
            or not table_ok
            or (cik != COSTCO and not re.fullmatch(r"[0-9a-f]{16}", note.get("document_sha256_16") or ""))):
        raise ValueError("Invalid source for borrowing note")
    values = note["values"]
    if any(type(value) is not int or value % MILLION for value in values.values()):
        raise ValueError("Invalid USD-million borrowing note amount")

    def part(name, value, url=source["table_url"]):
        return {"line": name, "tag": tag, "value": value, "table_url": url}

    total = original["value"]
    if cik == EQUINOR:
        diff = total - sum(values[k] for k in ("current", "collateral", "other"))
        if (values["aggregate"] != total or abs(diff) > MILLION or
                values["financing"] != evidence["financing"] or values["document_total"] != values["financing"]):
            raise ValueError("Equinor borrowing note does not match the financing cash flows")
        parts = [("borrowing", part("Current finance debt within mixed line", values["current"])),
                 ("collateral", part("Collateral receivables within mixed line", values["collateral"], report["url"])),
                 ("other_financing", part("Other balance-sheet items within mixed line", values["other"], report["url"]))]
        if diff:
            parts.append(("rounding", part("Mixed financing line rounding difference", diff, report["url"])))
        return original, parts

    tagged = period["facts"].get("finance_lease_principal_note", {})
    lease = values["lease"]
    if (tuple(tagged.get(k) for k in ("tag", "unit", "accession", "start", "value", "url", "filed")) !=
            (LEASE_TAG, period["currency"], report["accession"], period["start"], lease, report["url"], report["filed"])
            or not 0 < lease <= -total):
        raise ValueError("Lease note and the mixed financing payment do not agree")
    if cik == COSTCO:
        parts = [("lease", part(COSTCO_LEASE, -lease))]
        remainder = total + lease
        if remainder:
            parts.append(("unallocated", part("Other financing cash flows after the finance lease payment", remainder)))
        return original, parts

    prepayment = values["prepayment"]
    if not ALPHABET_SCOPE.search(note["scope"]) or not 0 <= prepayment <= lease:
        raise ValueError("Alphabet lease payment scope does not match the repayment line")
    parts = [
        ("borrowing", part("Debt repayments after removing finance lease cash payments", total + lease)),
        ("lease", part("Finance lease principal within debt repayments", -(lease - prepayment))),
    ]
    if prepayment:
        parts.append(("prepayment", part(ALPHABET_PREPAY, -prepayment)))
    return original, parts
