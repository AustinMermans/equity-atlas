"""Reconcile borrowing carrying amounts from the selected annual filing."""

import re

from .balance_sheet import ASSETS, CLAIMS, CURRENT, NONCURRENT, TITLES, TOTAL
from .facts import annual_rule_key, exact_sec_amount, recurring_annual_rules
from .fetch import SEC
from .rendered_filing import annual_table, scaled, valid_table_source

TAG = "derived:FiledDebtCarryingAmount"
TERM = ("us-gaap:LongTermDebtNoncurrent", "Long-term debt")
IFRS_TERM = "ifrs-full:LongtermBorrowings"
IFRS_CURRENT = "ifrs-full:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"
CONVERTIBLE = "us-gaap:ConvertibleDebtNoncurrent"
FINANCE_NONCURRENT = "us-gaap:FinanceLeaseLiabilityNoncurrent"
LEASES_CURRENT = ("ifrs-full:CurrentLeaseLiabilities", "Lease liabilities")
LEASES_NONCURRENT = ("ifrs-full:NoncurrentLeaseLiabilities", "Lease liabilities")

ADP = (8670, "0000008670-26-000030")
AGNICO = (2809, "0001104659-26-032153")
ALIBABA = (1577552, "0001193125-26-231755")
CROWDSTRIKE = (1535527, "0001535527-26-000009")
DEERE = (315189, "0001104659-25-122321")
EQUINOR = (1140625, "0001140625-26-000013")
MODERNA = (1682852, "0001682852-26-000033")
CLOUDFLARE = (1477333, "0001477333-26-000016")
NETFLIX = (1065280, "0001065280-26-000034")
SERVICENOW = (1373715, "0001373715-26-000007")
PALO_ALTO = (1327567, "0001327567-26-000023")
REGENERON = (872589, "0000872589-26-000008")
SHOPIFY = (1594805, "0001594805-26-000007")
SNOWFLAKE = (1640147, "0001640147-26-000008")
SPOTIFY = (1639920, "0001628280-26-006874")
TOTALENERGIES = (879764, "0001104659-26-035876")

# The face profiles name disjoint borrowing lines and exclude operating leases
# and commitments. US GAAP finance leases are included when separately identified.
FACE = {
    ADP: (("us-gaap:CommercialPaper", "Obligations under commercial paper borrowings"), TERM),
    AGNICO: ((IFRS_TERM, "Long-term debt (Note 14)"),),
    ALIBABA: (
        ("baba:BankBorrowingsCurrent", "Current bank borrowings"),
        ("us-gaap:LongTermLoansFromBank", "Non-current bank borrowings"),
        ("us-gaap:SeniorLongTermNotes", "Non-current unsecured senior notes"),
        (CONVERTIBLE, "Non-current convertible unsecured senior notes"),
    ),
    CROWDSTRIKE: (TERM,),
    DEERE: (
        ("us-gaap:DebtCurrent", "Short-term borrowings"),
        ("us-gaap:SecuredDebt", "Short-term securitization borrowings"),
        ("de:LongTermDebtAndFinanceLeasesNoncurrent", "Long-term borrowings"),
    ),
    EQUINOR: (
        ("ifrs-full:CurrentPortionOfLongtermBorrowings", "Finance debt"),
        (IFRS_TERM, "Finance debt"),
    ),
    MODERNA: (TERM, (FINANCE_NONCURRENT, "Financing lease liabilities, non-current")),
    CLOUDFLARE: (
        ("us-gaap:ConvertibleDebtCurrent", "Current portion of convertible senior notes, net"),
        (CONVERTIBLE, "Convertible senior notes, net"),
    ),
    NETFLIX: (("us-gaap:ShortTermBorrowings", "Short-term debt"), TERM),
    SERVICENOW: (("us-gaap:ConvertibleLongTermNotesPayable", "Long-term debt, net"),),
    PALO_ALTO: ((CONVERTIBLE, "Long-term convertible senior notes"),),
    REGENERON: (TERM, (FINANCE_NONCURRENT, "Finance lease liabilities")),
    SHOPIFY: (("us-gaap:ConvertibleDebtCurrent", "Convertible senior notes"),),
    SNOWFLAKE: ((CONVERTIBLE, "Convertible senior notes, net"),),
    SPOTIFY: ((IFRS_CURRENT, "Exchangeable Notes"), (IFRS_TERM, "Exchangeable Notes")),
    TOTALENERGIES: ((IFRS_CURRENT, "Current borrowings"), (IFRS_TERM, "Non-current financial debt")),
}
# These note lines are embedded in other current liabilities on the face.
NOTES = {
    ADP: (("us-gaap:DebtCurrent", "Long-term debt note · Current portion of long-term debt"),),
    MODERNA: (("us-gaap:FinanceLeaseLiabilityCurrent", "Leases note · Current finance lease liabilities"),),
}
SEPARATE_LEASES = {AGNICO: (("ifrs-full:CurrentLeaseLiabilities", "Lease obligations (Note 13)"),
                              ("ifrs-full:NoncurrentLeaseLiabilities", "Lease obligations (Note 13)")),
                   EQUINOR: (LEASES_CURRENT, LEASES_NONCURRENT), SPOTIFY: (LEASES_NONCURRENT,)}
LEASE_NOTES = {SPOTIFY: (("ifrs-full:CurrentLeaseLiabilities", "Leases note · Current lease liabilities"),)}
RECURRING = recurring_annual_rules(FACE)
BORROWING = re.compile(r"\b(debt|borrowings?|commercial paper|(?:convertible|exchangeable|senior) (?:senior )?notes|"
                       r"financ(?:e|ing) lease liabilities|securitization borrowings)\b", re.I)


def rule_key(cik, report):
    return annual_rule_key(cik, report, FACE, RECURRING)


def supported(cik, report):
    return rule_key(cik, report) in FACE


def debt_facts(cik, report, period, evidence):
    key = rule_key(cik, report)
    parts = evidence["face"]
    notes = evidence["notes"]
    leases = evidence["leases"]
    lease_notes = evidence["lease_notes"]
    scope = (None, report["accession"], period["currency"], report["filed"], report["form"], report["url"])
    keys = ("start", "accession", "unit", "filed", "form", "url")
    facts = period["facts"]
    if ((period["period_kind"], period["filing"], period["end"]) != ("annual", report["accession"], report["end"])
            or any(tuple(facts[field][k] for k in keys) != scope or facts[field]["value"] != evidence[field]
                   for field in ("assets", "liabilities"))
            or tuple((part["tag"], part["line"]) for part in parts) != FACE[key]
            or tuple((part["tag"], part["line"]) for part in notes) != NOTES.get(key, ())
            or tuple((part["tag"], part["line"]) for part in leases) != SEPARATE_LEASES.get(key, ())
            or tuple((part["tag"], part["line"]) for part in lease_notes) != LEASE_NOTES.get(key, ())):
        raise ValueError("Borrowing evidence does not match the annual balance sheet or reviewed component scopes")
    source = {k: parts[0][k] for k in ("source", "sha256", "table_url", "table_sha256_16")}
    for part in parts + leases + notes + lease_notes:
        if (tuple(part[k] for k in keys) != scope or part["sign"] != 1 or
                type(part["value"]) is not int or not 0 <= part["value"] <= evidence["liabilities"]
                or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])):
            raise ValueError("Borrowing component does not match the annual report")
    if (not valid_table_source(source, report)
            or any(any(part[k] != v for k, v in source.items()) for part in parts + leases)
            or any(part["source"] != SEC.format(cik) or "table_url" in part for part in notes + lease_notes)):
        raise ValueError("Unverified borrowing or lease source")
    value = sum(part["value"] for part in parts + notes)
    leases = leases + lease_notes
    if value + sum(part["value"] for part in leases) > evidence["liabilities"]:
        raise ValueError("Borrowing and separately reported leases exceed total liabilities")
    result = {"debt_total": {**parts[0], "tag": TAG, "value": value, "components": parts + notes,
                             "locator": "Consolidated borrowing at reported carrying amounts"}}
    if leases:
        result["lease_liabilities_separate"] = {
            **leases[0], "tag": TAG, "value": sum(part["value"] for part in leases),
            "components": leases, "locator": "Lease liabilities presented separately from financial debt",
        }
    return result


def enrich_debt(cache, obj, meta, cik, report, period):
    key = rule_key(cik, report)
    table, index, receipt, table_source = annual_table(cache, cik, report, period, "balance_sheet", None)
    if " ".join(table["title"].casefold().split()) not in TITLES:
        raise ValueError("Borrowing is outside a recognized consolidated balance sheet")
    rows = table["rows"]
    stop = next((i for i, row in enumerate(rows) if row[1] is None), len(rows))
    rows = rows[:stop]
    scale = table["money_scale"]
    stock = {**period, "start": None}

    def find(tags, pool):
        return [i for i in pool if rows[i][1] in tags and type(rows[i][index]) in (int, float)]

    assets, = find(ASSETS, range(len(rows)))
    combined, = find(CLAIMS, range(assets + 1, len(rows)))
    if scaled(rows[assets][index], scale) != scaled(rows[combined][index], scale):
        raise ValueError("Assets do not match total equity and liabilities")
    candidates = range(assets + 1, combined)
    total = find(TOTAL, candidates)
    if not total:
        current, = find(CURRENT, candidates)
        noncurrent, = find(NONCURRENT, candidates)
        total = [current, noncurrent]
    liabilities = sum(scaled(rows[i][index], scale) for i in total)
    scope = range(assets + 1, max(total))

    def component(tag, label, value, evidence_source):
        return {**evidence_source, "tag": tag, "line": label, "value": value, "sign": 1,
                "unit": period["currency"], "start": None, **{k: report[k] for k in ("accession", "filed", "form", "url")}}

    def face_part(tag, label):
        i, = (i for i in scope if rows[i][:2] == [label, tag] and type(rows[i][index]) in (int, float))
        value = scaled(rows[i][index], scale)
        exact = exact_sec_amount(obj, stock, report, tag)
        if exact is not None and exact != value:
            raise ValueError(f"Rendered borrowing line disagrees with Company Facts for {label}")
        return component(tag, label, value, {"source": receipt["url"], "sha256": receipt["sha256"], **table_source})

    disclosed = {(tag, label) for tag, label in FACE[key]}
    if any((rows[i][1], rows[i][0]) not in disclosed and type(rows[i][index]) in (int, float)
           and BORROWING.search(rows[i][0]) for i in scope):
        raise ValueError("Annual balance sheet contains an unreviewed borrowing line")

    face = [face_part(*line) for line in FACE[key]]
    leases = [face_part(*line) for line in SEPARATE_LEASES.get(key, ())]
    def note_part(tag, label):
        value = exact_sec_amount(obj, stock, report, tag)
        if value is None:
            raise ValueError(f"Missing exact note fact for {label}")
        return component(tag, label, value, {"source": meta["url"], "sha256": meta["sha256"]})

    evidence = {"assets": scaled(rows[assets][index], scale), "liabilities": liabilities,
                "face": face, "notes": [note_part(*line) for line in NOTES.get(key, ())], "leases": leases,
                "lease_notes": [note_part(*line) for line in LEASE_NOTES.get(key, ())]}
    result = debt_facts(cik, report, period, evidence)
    return {**period, "facts": {**period["facts"], **result}, "annual_debt": evidence}
