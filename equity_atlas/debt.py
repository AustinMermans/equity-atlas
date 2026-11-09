"""Reconcile borrowing carrying amounts from the selected annual filing."""

from datetime import date
import re

from .balance_sheet import ASSETS, CLAIMS, CURRENT, NONCURRENT, TITLES, TOTAL
from .facts import annual_rule_key, exact_sec_amount, recurring_annual_rules
from .fetch import SEC
from .issuer_20f import MIRRORS
from .rendered_filing import ENDPOINT, annual_table, filing_tables, scaled, table_belongs_to_filing, valid_table_source

TAG = "derived:FiledDebtCarryingAmount"
TERM = ("us-gaap:LongTermDebtNoncurrent", "Long-term debt")
IFRS_TERM = "ifrs-full:LongtermBorrowings"
IFRS_CURRENT = "ifrs-full:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings"
CONVERTIBLE = "us-gaap:ConvertibleDebtNoncurrent"
FINANCE_CURRENT = "us-gaap:FinanceLeaseLiabilityCurrent"
FINANCE_NONCURRENT = "us-gaap:FinanceLeaseLiabilityNoncurrent"
LEASES_CURRENT = ("ifrs-full:CurrentLeaseLiabilities", "Lease liabilities")
LEASES_NONCURRENT = ("ifrs-full:NoncurrentLeaseLiabilities", "Lease liabilities")

ADP = (8670, "0000008670-26-000030")
AGNICO = (2809, "0001104659-26-032153")
ALIBABA = (1577552, "0001193125-26-231755")
ARM = (1973239, "0001973239-26-000097")
CAT = (18230, "0000018230-26-000008")
CME = (1156375, "0001156375-26-000009")
EQUINIX = (1101239, "0001101239-26-000032")
GE_VERNOVA = (1996810, "0001996810-26-000015")
VERTEX = (875320, "0000875320-26-000056")
CIBC = (1045520, "0001193125-25-307488")
HSBC = (1089113, "0001089113-26-000010")
IBKR = (1381197, "0001381197-26-000062")
RBC = (1000275, "0001193125-25-305927")
SMFG = (1022837, "0001193125-26-283871")
TD = (947263, "0001562762-25-000289")
UBS = (1610520, "0001610520-26-000023")
GEV_LONG_TERM = ("disclosed:FinanceLeaseLiabilitiesAndOtherLongTermBorrowings",
                 "Finance lease liabilities and other long-term borrowings")
FUNDING = {
    CIBC: {
        "funding_secured_borrowings": (("ifrs-full:AssociatedLiabilitiesThatEntityContinuesToRecognise", "Secured borrowings"),),
        "funding_subordinated_liabilities": (("ifrs-full:SubordinatedLiabilities", "Subordinated indebtedness (Note 14)"),),
    },
    HSBC: {
        "funding_debt_securities_face": (("ifrs-full:DebtSecurities", "Debt securities in issue"),),
        "funding_subordinated_liabilities": (("ifrs-full:SubordinatedLiabilities", "Subordinated liabilities"),),
    },
    IBKR: {"funding_short_borrowings": (("us-gaap:OtherShortTermBorrowings", "Short-term borrowings"),)},
    RBC: {"funding_subordinated_liabilities": (("ifrs-full:SubordinatedLiabilities", "Subordinated debentures (Note 18)"),)},
    SMFG: {
        "funding_borrowings": (("ifrs-full:Borrowings", "Borrowings"),),
        "funding_debt_securities_face": (("ifrs-full:DebtSecurities", "Debt securities in issue"),),
    },
    TD: {
        "funding_securitization_liabilities": (("td:SecuritizationLiabilitiesAtFairValue", "Securitization liabilities at fair value"),
                                             ("td:SecuritizationLiabilitiesAtAmortizedCost", "Securitization liabilities at amortized cost")),
        "funding_subordinated_liabilities": (("ifrs-full:SubordinatedLiabilities", "Subordinated notes and debentures"),),
    },
    UBS: {
        "funding_debt_securities_face": (
            ("ifrs-full:DebtSecurities", "Debt issued measured at amortized cost"),
            ("ubs:DebtSecuritiesIssuedAtFairValueThroughProfitOrLossDesignatedAsUponInitialRecognition",
             "Debt issued designated at fair value"),
        ),
    },
}
CAT_CURRENT = ("disclosed:CurrentMaturitiesOfLongTermDebt", "Note 14 · Consolidated long-term debt due within one year")
CAT_QUERY = "Aggregate amounts of maturities of long-term debt"
CAT_NOTE_TITLE = f"Long-term debt - {CAT_QUERY} (Details)"
CAT_NOTE_FILE = "R108.htm"
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
    **{key: tuple(line for component in fields.values() for line in component) for key, fields in FUNDING.items()},
    ADP: (("us-gaap:CommercialPaper", "Obligations under commercial paper borrowings"), TERM),
    AGNICO: ((IFRS_TERM, "Long-term debt (Note 14)"),),
    ALIBABA: (
        ("baba:BankBorrowingsCurrent", "Current bank borrowings"),
        ("us-gaap:LongTermLoansFromBank", "Non-current bank borrowings"),
        ("us-gaap:SeniorLongTermNotes", "Non-current unsecured senior notes"),
        (CONVERTIBLE, "Non-current convertible unsecured senior notes"),
    ),
    ARM: (),
    CAT: (("us-gaap:ShortTermBorrowings", "Short-term borrowings"),),
    CME: (("us-gaap:ShortTermBorrowings", "Short-term debt"), ("us-gaap:UnsecuredLongTermDebt", "Long-term debt")),
    EQUINIX: (
        ("us-gaap:SeniorNotesCurrent", "Current portion of senior notes"),
        ("us-gaap:SeniorLongTermNotes", "Senior notes, less current portion"),
        ("us-gaap:LoansPayableCurrent", "Current portion of mortgage and loans payable"),
        ("us-gaap:LongTermLoansPayable", "Mortgage and loans payable, less current portion"),
        (FINANCE_CURRENT, "Current portion of finance lease liabilities"),
        (FINANCE_NONCURRENT, "Finance lease liabilities, less current portion"),
    ),
    GE_VERNOVA: (),
    VERTEX: (),
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
# These note lines are included in other liabilities on the face or are recovered
# as consolidated amounts where the rendered face shows only the headings.
FINANCE_LEASE_NOTES = (
    (FINANCE_CURRENT, "Leases note · Current finance lease liabilities"),
    (FINANCE_NONCURRENT, "Leases note · Noncurrent finance lease liabilities"),
)
NOTES = {
    ARM: FINANCE_LEASE_NOTES,
    CAT: (TERM, CAT_CURRENT),
    GE_VERNOVA: (("us-gaap:ShortTermBorrowings", "Other liabilities note · Short-term borrowings"),
                 FINANCE_LEASE_NOTES[0], GEV_LONG_TERM),
    VERTEX: FINANCE_LEASE_NOTES,

    ADP: (("us-gaap:DebtCurrent", "Long-term debt note · Current portion of long-term debt"),),
    MODERNA: FINANCE_LEASE_NOTES[:1],
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
    mirror = MIRRORS.get((cik, report["accession"]))
    # CME’s rendered asset anchor is rounded to millions, while Company Facts retains tenths.
    anchor_tolerance = 500_000 if key == CME else 0

    def anchor(field):
        fact = facts[field]
        if mirror and fact.get("source") == mirror[2] and fact["tag"] == f"issuer_20f:{field}":
            fact = {"accession": report["accession"], **fact}
        return (tuple(fact[k] for k in keys) == scope and
                abs(fact["value"] - evidence[field]) <= anchor_tolerance)

    if ((period["period_kind"], period["filing"], period["end"]) != ("annual", report["accession"], report["end"])
            or not all(anchor(field) for field in ("assets", "liabilities"))
            or tuple((part["tag"], part["line"]) for part in parts) != FACE[key]
            or tuple((part["tag"], part["line"]) for part in notes) != NOTES.get(key, ())
            or tuple((part["tag"], part["line"]) for part in leases) != SEPARATE_LEASES.get(key, ())
            or tuple((part["tag"], part["line"]) for part in lease_notes) != LEASE_NOTES.get(key, ())):
        raise ValueError("Borrowing evidence does not match the annual balance sheet or reviewed component scopes")
    source = {k: parts[0][k] for k in ("source", "sha256", "table_url", "table_sha256_16")} if parts else evidence["balance_source"]
    for part in parts + leases + notes + lease_notes:
        if (tuple(part[k] for k in keys) != scope or part["sign"] != 1 or
                type(part["value"]) is not int or not 0 <= part["value"] <= evidence["liabilities"]
                or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])):
            raise ValueError("Borrowing component does not match the annual report")
    tagged_notes = [part for part in notes + lease_notes if part["tag"] not in {CAT_CURRENT[0], GEV_LONG_TERM[0]}]
    if key == CAT:
        current = notes[-1]
        if (not valid_table_source(current, report, CAT_NOTE_FILE if key == (cik, report["accession"]) else None)
                or sum(evidence["current_liability_components"]) + current["value"] != evidence["current_liabilities"]
                or not 0 <= evidence["current_liabilities"] <= evidence["liabilities"]):
            raise ValueError("Caterpillar current debt does not tie to the classified current liabilities")
    if key == GE_VERNOVA:
        long_term = notes[-1]
        if (long_term["source"] != ENDPOINT or long_term["table_url"] != report["url"]
                or not re.fullmatch(r"[0-9a-f]{16}", long_term["table_sha256_16"])):
            raise ValueError("GE Vernova long-term borrowings do not match the filed liabilities note")
    if (not valid_table_source(source, report) or not re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
            or any(any(part[k] != v for k, v in source.items()) for part in parts + leases)
            or any(part["source"] != SEC.format(cik) or "table_url" in part for part in tagged_notes)):
        raise ValueError("Unverified borrowing or lease source")
    value = sum(part["value"] for part in parts + notes)
    leases = leases + lease_notes
    if value + sum(part["value"] for part in leases) > evidence["liabilities"]:
        raise ValueError("Borrowing and separately reported leases exceed total liabilities")
    if key in FUNDING:
        by_line = {(part["tag"], part["line"]): part for part in parts}
        result = {}
        for field, lines in FUNDING[key].items():
            selected = [by_line[line] for line in lines]
            result[field] = {**selected[0], "tag": TAG, "value": sum(part["value"] for part in selected),
                             "components": selected, "locator": "Consolidated balance-sheet funding line"}
        return result
    result = {"debt_total": {**(parts + notes)[0], "tag": TAG, "value": value, "components": parts + notes,
                             "locator": "Consolidated borrowing at reported carrying amounts"}}
    if leases:
        result["lease_liabilities_separate"] = {
            **leases[0], "tag": TAG, "value": sum(part["value"] for part in leases),
            "components": leases, "locator": "Lease liabilities presented separately from financial debt",
        }
    return result


def caterpillar_current_debt(cache, cik, report, currency):
    tables, digests, receipt = filing_tables(cache, cik, report, CAT_QUERY)
    pinned = CAT_NOTE_FILE if (cik, report["accession"]) == CAT else None
    end = date.fromisoformat(report["end"])
    if currency != "USD" or end.strftime("%m-%d") != "12-31":
        raise ValueError("Unexpected currency or fiscal year for Caterpillar debt")
    column = f"Dec. 31, {end.year} USD ($)"
    table, = (t for t in tables if t["source"] == "xbrl report" and t["title"] == CAT_NOTE_TITLE
              and t["units"] == "$ in Millions" and t["columns"].count(column) == 1
              and table_belongs_to_filing(t["url"], report, pinned))
    index = table["columns"].index(column)
    year = str(end.year + 1)
    aggregate = {}
    section = "Consolidated"
    for row in table["rows"]:
        if row[0] in {"Machinery, Power & Energy", "Financial Products"} and row[index] is None:
            section = row[0]
        if row[0] == year and type(row[index]) in (int, float):
            if section in aggregate:
                raise ValueError("Duplicate Caterpillar current maturity in the same business scope")
            aggregate[section] = scaled(row[index], 1_000_000)
    if (aggregate.keys() != {"Consolidated", "Machinery, Power & Energy", "Financial Products"} or
            aggregate["Consolidated"] != aggregate["Machinery, Power & Energy"] + aggregate["Financial Products"]):
        raise ValueError("Caterpillar long-term debt maturity scopes do not reconcile")
    return aggregate["Consolidated"], {"source": receipt["url"], "sha256": receipt["sha256"],
                                       "table_url": table["url"], "table_sha256_16": digests.get(table["url"], "")}


def vernova_long_term_debt(cache, cik, report, currency, short_term, lease_noncurrent):
    query = GEV_LONG_TERM[1]
    tables, digests, receipt = filing_tables(cache, cik, report, query)
    year = report["end"][:4]
    if currency != "USD" or report["end"] != f"{year}-12-31":
        raise ValueError("Unexpected currency or fiscal year for GE Vernova debt")
    table, = (t for t in tables if t["source"] == "document table" and t["url"] == report["url"]
              and t["title"].endswith("CURRENT AND ALL OTHER LIABILITIES") and t["columns"].count(year) == 1)
    index = table["columns"].index(year)
    short, = (scaled(r[index], 1_000_000) for r in table["rows"] if r[0] == "Short-term borrowings")
    long, = (scaled(r[index], 1_000_000) for r in table["rows"] if r[0] == query)
    if short != short_term or lease_noncurrent is None or not 0 <= lease_noncurrent <= long:
        raise ValueError("GE Vernova borrowing and finance lease notes do not reconcile")
    return long, {"source": receipt["url"], "sha256": receipt["sha256"],
                  "table_url": table["url"], "table_sha256_16": digests.get(table["url"], "")}


def enrich_debt(cache, obj, meta, cik, report, period):
    key = rule_key(cik, report)
    table, index, receipt, table_source = annual_table(cache, cik, report, period, "balance_sheet", None)
    additional_title = {CAT: "consolidated financial position at december 31",
                        GE_VERNOVA: "consolidated and combined statement of financial position",
                        IBKR: "condensed consolidated statements of financial condition"}.get(key)
    titles = TITLES | {additional_title}
    if " ".join(table["title"].casefold().split()) not in titles:
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

    balance_source = {"source": receipt["url"], "sha256": receipt["sha256"], **table_source}

    def face_part(tag, label):
        i, = (i for i in scope if rows[i][:2] == [label, tag] and type(rows[i][index]) in (int, float))
        value = scaled(rows[i][index], scale)
        exact = exact_sec_amount(obj, stock, report, tag)
        if exact is not None and exact != value:
            raise ValueError(f"Rendered borrowing line disagrees with Company Facts for {label}")
        return component(tag, label, value, balance_source)

    disclosed = {(tag, label) for tag, label in FACE[key]}
    if key not in FUNDING and any((rows[i][1], rows[i][0]) not in disclosed and type(rows[i][index]) in (int, float)
           and BORROWING.search(rows[i][0]) for i in scope):
        raise ValueError("Annual balance sheet contains an unreviewed borrowing line")

    face = [face_part(*line) for line in FACE[key]]
    leases = [face_part(*line) for line in SEPARATE_LEASES.get(key, ())]

    def note_part(tag, label):
        if (tag, label) == CAT_CURRENT:
            value, source = caterpillar_current_debt(cache, cik, report, period["currency"])
            return component(tag, label, value, source)
        if (tag, label) == GEV_LONG_TERM:
            value, source = vernova_long_term_debt(cache, cik, report, period["currency"],
                exact_sec_amount(obj, stock, report, "us-gaap:ShortTermBorrowings"),
                exact_sec_amount(obj, stock, report, FINANCE_NONCURRENT))
            return component(tag, label, value, source)
        value = exact_sec_amount(obj, stock, report, tag)
        if value is None:
            raise ValueError(f"Missing exact note fact for {label}")
        return component(tag, label, value, {"source": meta["url"], "sha256": meta["sha256"]})

    evidence = {"assets": scaled(rows[assets][index], scale), "liabilities": liabilities,
                "face": face, "notes": [note_part(*line) for line in NOTES.get(key, ())], "leases": leases,
                "lease_notes": [note_part(*line) for line in LEASE_NOTES.get(key, ())]}
    if not face:
        evidence["balance_source"] = balance_source
    if key in {ARM, VERTEX}:
        lease_total = exact_sec_amount(obj, stock, report, "us-gaap:FinanceLeaseLiability")
        if lease_total != sum(part["value"] for part in evidence["notes"]):
            raise ValueError("Current and noncurrent finance leases do not tie to the filed total")
    if key == CAT:
        current, = find(CURRENT, scope)
        expected_tags = {"us-gaap:ShortTermBorrowings", "us-gaap:AccountsPayableCurrent", "us-gaap:AccruedLiabilitiesCurrent",
                         "us-gaap:EmployeeRelatedLiabilitiesCurrent", "us-gaap:ContractWithCustomerLiabilityCurrent",
                         "us-gaap:DividendsPayableCurrent", "us-gaap:OtherLiabilitiesCurrent"}
        current_rows = [row for row in rows[assets+1:current] if type(row[index]) in (int, float)]
        if len(current_rows) != len(expected_tags) or {row[1] for row in current_rows} != expected_tags:
            raise ValueError("Caterpillar current-liability lines changed")
        evidence["current_liabilities"] = scaled(rows[current][index], scale)
        evidence["current_liability_components"] = [scaled(row[index], scale) for row in current_rows]
    result = debt_facts(cik, report, period, evidence)
    return {**period, "facts": {**period["facts"], **result}, "annual_debt": evidence}
