"""Allocate a mixed financing line using the selected annual filing's note."""

from datetime import date
import re

from .rendered_filing import ENDPOINT, filing_tables, scaled, table_belongs_to_filing

MILLION = 1_000_000
LEASE_TAG = "us-gaap:FinanceLeasePrincipalPayments"
ALPHABET, COSTCO, EQUINOR, AMGEN, TOTAL = 1652044, 909832, 1140625, 318154, 879764
TOTAL_CURRENT = ("Increase (decrease) in current borrowings", "ifrs-full:CashFlowsFromUsedInIncreaseDecreaseInCurrentBorrowings")
RULES = {
    ALPHABET: ("Repayments of debt", "us-gaap:RepaymentsOfDebtAndCapitalLeaseObligations",
               "Financing cash flows used for financing leases", "Leases - Supplemental Cash Flow Information (Details)"),
    COSTCO: ("Financing lease payments and other financing activities, net",
             "cost:FinancingLeasePaymentsAndOtherFinancingActivitiesNet", "Financing cash flows — finance leases",
             "Leases, Supplemental Cash Flow Information (Details)"),
    TOTAL: (*TOTAL_CURRENT, "Variations of financial debt",
            "Financial structure and financial costs - Variations of financial debt (Details)"),
    AMGEN: ("Extinguishment of debt", "us-gaap:PaymentsOfDebtExtinguishmentCosts",
            "Extinguishment of debt", "Financing arrangements - Debt Extinguishment (Details)"),
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
    elif cik == TOTAL:
        document, = (t for t in tables if t["source"] == "document table" and t["url"] == report["url"]
                     and (t["title"] or "").endswith("The variations of financial debt are detailed as follows:")
                     and t["columns"].count(f"As of December 31, {end.year}") == 1
                     and t["columns"].count("Cash changes") == 1)
        cash = document["columns"].index("Cash changes")
        note.update(document_sha256_16=digests.get(report["url"]), values={
            field: note_amount(document["rows"], row, cash) for field, row in {
                "current": "Current borrowings", "current_assets": "Current financial instruments - assets (a)",
                "current_total": "Current financial debt and related financial instruments",
                "noncurrent": "Non-current financial debt", "noncurrent_total": "Non-current financial debt and related financial instruments",
                "total": "NET FINANCIAL DEBT",
            }.items()
        })
        group_end, = (i for i, r in enumerate(rows) if r[0] == "Non-current financial debt and related financial instruments"
                      and r[index] is None)
        note["values"]["rendered_total"] = note_amount(rows[:group_end], "Cash changes", index)
    elif cik == AMGEN:
        detail, = (i for i, r in enumerate(rows) if r[0] == "Notes" and r[index] is None)
        consolidated = rows[:detail]
        note["values"] = {
            "extinguishment": note_amount(consolidated, label, index),
            "other_repayment": note_amount(consolidated, "Repayments of debt", index),
        }
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
            or (cik in {ALPHABET, EQUINOR, TOTAL} and not re.fullmatch(r"[0-9a-f]{16}", note.get("document_sha256_16") or ""))):
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
    if cik == TOTAL:
        noncurrent, = (r["value"] for r in evidence["lines"]
                       if r["tag"] == "tot:ProceedsFromRepaymentsOfNonCurrentBorrowings"
                       and r["line"] == "Net issuance (repayment) of non-current debt")
        if (values["current_total"] != total or values["current"] + values["current_assets"] != total
                or values["noncurrent"] != noncurrent or values["total"] != values["rendered_total"]
                or values["noncurrent_total"] + total != values["total"]):
            raise ValueError("TotalEnergies borrowing and asset cash changes do not match its roll-forward")
        return original, [
            ("borrowing", part("Current borrowings in the financing note", values["current"], report["url"])),
            ("current_borrowing_assets", part("Financial assets within the current borrowing line", values["current_assets"], report["url"])),
        ]
    if cik == AMGEN:
        other, = (r["value"] for r in evidence["lines"]
                  if r["tag"] == "us-gaap:RepaymentsOfLongTermDebt" and r["line"] == "Repayment of debt")
        if total >= 0 or values["extinguishment"] != -total or values["other_repayment"] != -other:
            raise ValueError("Amgen's debt repurchases and separate repayments do not match the filed note")
        return original, [("debt_repurchase", part("Cash paid to repurchase and extinguish debt", total))]

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

# These instruments are classified in shareholders' equity in the selected filing.
BAT = 1303523
HYBRIDS = {
    BAT: ("GBP", "Perpetual hybrid bonds", {
        ("Proceeds from the issue of perpetual hybrid bonds, net of issuance costs",
         "ifrs-full:ProceedsFromIssueOfBondsNotesAndDebentures"): "hybrid_draw",
        ("Redemption of perpetual hybrid bonds, net of costs",
         "ifrs-full:RepaymentsOfBondsNotesAndDebentures"): "hybrid_repayment",
    }),
    TOTAL: ("USD", "Perpetual subordinated notes", {
        ("Net issuance of perpetual subordinated notes",
         "tot:ProceedsFromIssueRepaymentOfSubordinatedNotes"): "hybrid_net",
        ("Payments on perpetual subordinated notes",
         "tot:PaymentForCouponsOnSubordinatedNotes"): "other",
    }),
}


def hybrid_candidate(cik, lines):
    return cik in HYBRIDS and any((x["line"], x["tag"]) in HYBRIDS[cik][2] for x in lines)


def read_hybrid_note(cache, cik, report):
    currency, query, _ = HYBRIDS[cik]
    tables, digests, receipt = filing_tables(cache, cik, report, query)
    end = date.fromisoformat(report["end"])
    if cik == BAT:
        table, = (t for t in tables if t["source"] == "document table" and t["url"] == report["url"]
                  and (t["title"] or "").endswith(" / Group Balance Sheet")
                  and t["columns"][1:2] == [f"{end.year} £m"]
                  and any(r[0] == "Equity - capital and reserves" for r in t["rows"]))
        # The source preserves the note marker as an unheaded column.
        row, = (r for r in table["rows"] if r[0] == query and re.fullmatch(r"\d+\([a-z]\)", str(r[1])))
        amount = scaled(row[2], MILLION)
    else:
        column = f"12 Months Ended {end:%b. %d, %Y} USD ($)"
        table, = (t for t in tables if t["source"] == "xbrl report"
                  and t["title"] == "Shareholders' equity and share-based payments - Perpetual subordinated notes (Details)"
                  and t["units"] == "€ in Millions, $ in Millions" and t["columns"].count(column) == 1
                  and table_belongs_to_filing(t["url"], report))
        amount = note_amount(table["rows"], "Amount of perpetual deeply subordinated notes recorded in equity | $",
                             table["columns"].index(column))
    return {"source": receipt["url"], "sha256": receipt["sha256"], "table_url": table["url"],
            "table_sha256_16": digests.get(table["url"]), "currency": currency, "equity_amount": amount}


def hybrid_roles(report, period, note):
    cik = int(report["path"].split("/")[-2])
    currency, _, scoped = HYBRIDS[cik]
    amount = note["equity_amount"]
    balance = period["facts"].get("hybrid_equity")
    if (note["currency"] != currency or period["currency"] != currency or
            note["source"] != ENDPOINT or not re.fullmatch(r"[0-9a-f]{64}", note["sha256"])
            or not re.fullmatch(r"[0-9a-f]{16}", note["table_sha256_16"] or "")
            or (note["table_url"] != report["url"] if cik == BAT else not table_belongs_to_filing(note["table_url"], report))
            or type(amount) is not int or amount <= 0 or amount % MILLION
            or amount >= period["facts"]["total_equity"]["value"]
            or (balance and (balance["value"], balance["url"]) != (amount, report["url"]))):
        raise ValueError("Unverified classification of perpetual instruments in equity")
    return scoped


EMBEDDED_LEASE = {
    ("Repayments of long-term borrowings and finance lease obligations",
     "vz:RepaymentsOfLongTermBorrowingsAndFinanceLeaseObligations"),
    ("Repayments of long-term debt and finance lease obligations",
     "us-gaap:RepaymentsOfLongTermDebtAndCapitalSecurities"),
    ("Repayment of debt and finance lease obligations", "us-gaap:RepaymentsOfDebtAndCapitalLeaseObligations"),
}


def split_explicit_lease(report, period, groups):
    """A combined repayment explicitly names both debt and finance leases."""
    if groups["lease"]:
        return
    mentions = [line for line in groups["unallocated"] if "lease" in line["line"].casefold()]
    if len(mentions) != 1:
        return
    line = mentions[0]
    if (line["line"], line["tag"]) not in EMBEDDED_LEASE:
        return
    fact = period["facts"].get("finance_lease_principal_note", {})
    lease = fact.get("value")
    if (tuple(fact.get(k) for k in ("tag", "unit", "accession", "start", "url", "filed")) !=
            (LEASE_TAG, period["currency"], report["accession"], period["start"], report["url"], report["filed"])
            or type(lease) is not int or not 0 <= lease <= -line["value"]):
        return
    groups["unallocated"].remove(line)
    groups["borrowing"].append({**line, "line": "Debt repayment excluding finance lease principal",
                                 "value": line["value"] + lease})
    groups["lease"].append({**line, "line": "Finance lease principal in combined repayment",
                             "value": -lease, "table_url": fact["url"]})
