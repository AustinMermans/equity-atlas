"""Read annual cash balances with the scope stated in the selected filing."""

import re

from .balance_sheet import ASSETS, TITLES
from .facts import annual_rule_key, exact_sec_amount, recurring_annual_rules
from .fetch import SEC
from .issuer_20f import column, pdf_pages
from .rendered_filing import ENDPOINT, annual_table, filing_tables, scaled, table_belongs_to_filing, valid_table_source

TAG = "derived:FiledCashBalance"
TOTAL = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
RESTRICTED = "us-gaap:RestrictedCashAndCashEquivalents"
BROAD = "cash_including_restricted"
AIRBNB = (1559720, "0001559720-26-000004")
GOLDMAN = (886982, "0000886982-26-000091")
MORGAN = (895421, "0000895421-26-000086")
VISA = (1403161, "0001403161-26-000134")
CORRECT_EXISTING = {GOLDMAN, MORGAN}
REVIEW_EXISTING = CORRECT_EXISTING | {AIRBNB, VISA}
AXP = (4962, "0000004962-26-000080")
BAC = (70858, "0000070858-26-000157")
BRK = (1067983, "0001193125-26-083899")
CITI = (831001, "0000831001-26-000011")
CHUBB = (896159, "0000896159-26-000005")
GE = (40545, "0000040545-26-000008")
GEV = (1996810, "0001996810-26-000015")
HDFC = (1144967, "0001193125-26-322004")
JPM = (19617, "0001628280-26-008131")
MIZUHO = (1335730, "0001193125-26-283791")
MUFG = (67088, "0001628280-26-047095")
PGR = (80661, "0000080661-26-000086")
SBUX = (829224, "0000829224-25-000114")
WFC = (72971, "0000072971-26-000133")

# Match the printed cash captions within the consolidated asset section.
FACE = {
    (927628, "0000927628-26-000024"): {
        "cash": ("us-gaap:CashCashEquivalentsAndFederalFundsSold", "Total cash and cash equivalents"),
        "restricted_cash": (RESTRICTED, "Restricted cash for securitization investors"),
    },
    (93410, "0000093410-26-000078"): {
        "cash": ("cvx:CashAndCashEquivalentsExcludingTimeDeposits", "Cash and cash equivalents"),
    },
    (313616, "0000313616-26-000062"): {"cash": (TOTAL, "Cash and equivalents")},
    (882095, "0000882095-26-000006"): {"cash": (TOTAL, "Cash and cash equivalents")},
    (66740, "0000066740-26-000014"): {
        "cash": (TOTAL + "IncludingDisposalGroupAndDiscontinuedOperations", "Cash and cash equivalents"),
    },
    (80424, "0000080424-26-000103"): {"cash": (TOTAL, "Cash and cash equivalents")},
    GE: {BROAD: (TOTAL, "Cash, cash equivalents and restricted cash")},
    GEV: {BROAD: (TOTAL, "Cash, cash equivalents, and restricted cash")},
    MUFG: {
        "cash_and_bank_deposits": ("mufg:CashDueFromBanksAndInterestBearingDepositsInBanks",
                                   "Cash, due from banks and interest-earning deposits in other banks"),
        "cash_due_from_banks": ("mufg:CashAndDueFromBanksIncludingSpecificRestrictedCash", "Cash and due from banks (Note 9)"),
        "interest_bearing_deposits_at_banks": ("mufg:InterestBearingDepositsInBanksIncludingSpecificRestrictedCash",
                                               "Interest-earning deposits in other banks (Note 9)"),
    },
    PGR: {
        "cash": ("us-gaap:Cash", "Cash and cash equivalents"),
        "restricted_cash": (RESTRICTED, "Restricted cash and cash equivalents"),
        BROAD: (TOTAL, "Total cash, cash equivalents, restricted cash, and restricted cash equivalents"),
    },
}

# These exact balance-date facts have reviewed scopes in the selected filing.
# A subtotal published in billions carries that precision through the split.
RESTRICTED_ROUNDING = {BAC: 100_000_000, JPM: 100_000_000}
TAGGED = {
    AIRBNB: {BROAD: (TOTAL, "Note 3 · Cash-flow total including customer balances and restricted cash"),
             "restricted_cash": (RESTRICTED, "Note 3 · Restricted cash in prepaids and other current assets")},
    GOLDMAN: {BROAD: (TOTAL, "Balance sheet · Cash and equivalents including segregated cash"),
              "restricted_cash_reported": (RESTRICTED, "Credit exposure · Cash segregated for regulatory and other purposes")},
    MORGAN: {BROAD: (TOTAL, "Note 3 · Cash and cash equivalents including restricted cash"),
             "restricted_cash": (RESTRICTED, "Note 3 · Restricted cash included in the total")},
    VISA: {BROAD: (TOTAL, "Note 4 · Total cash, cash equivalents and restricted cash")},
    AXP: {BROAD: (TOTAL, "Balance sheet · Total cash and cash equivalents including restricted cash"),
          "restricted_cash": (RESTRICTED, "Balance sheet · Restricted cash included in the total")},
    BAC: {BROAD: (TOTAL, "Balance sheet · Cash and cash equivalents including restricted cash"),
          "restricted_cash": ("us-gaap:RestrictedCash", "Note 10 · Restricted cash included in the balance-sheet total")},
    BRK: {BROAD: (TOTAL, "Cash flow · Cash and restricted cash across both business groups"),
          "restricted_cash": (RESTRICTED, "Cash flow · Restricted cash included in other assets")},
    CITI: {BROAD: (TOTAL, "Cash flow · Cash and due from banks plus deposits with banks, net of allowance"),
           "restricted_cash": ("us-gaap:RestrictedCash", "Restricted cash included in cash and deposits with banks")},
    CHUBB: {BROAD: (TOTAL, "Balance sheet · Cash including restricted cash"),
            "restricted_cash": (RESTRICTED, "Balance sheet · Restricted cash included in the total")},
    GE: {"insurance_cash": ("us-gaap:RestrictedCashAndCashEquivalentsNoncurrent",
                            "Note 9 · Run-off insurance cash and equivalents in other assets")},
    GEV: {"restricted_cash": ("us-gaap:RestrictedCash", "Cash accounting policy · Restricted cash included in the balance-sheet total")},
    JPM: {BROAD: (TOTAL, "Cash flow · Cash and due from banks plus deposits with banks"),
          "restricted_cash": (RESTRICTED, "Note 26 · Restricted cash included in the two balance-sheet lines")},
    MIZUHO: {"cash": (TOTAL, "Consolidated cash flow · Cash and cash equivalents at end of fiscal year")},
    MUFG: {BROAD: (TOTAL, "Consolidated cash flow · Cash, bank deposits and restricted cash")},
    SBUX: {"cash": (TOTAL, "Consolidated balance sheet · Cash and cash equivalents")},
    WFC: {BROAD: (TOTAL, "Consolidated cash flow · Cash, cash equivalents, and restricted cash at end of period")},
}
HDFC_TITLE = "Cash and Due From Banks, and Restricted Cash - Additional Information (Detail)"
HDFC_NOTE = ("disclosed:RestrictedReserveCash", "Note 4 · Restricted reserve cash")
GOLDMAN_UNRESTRICTED = ("disclosed:UnrestrictedCashAndEquivalents", "Credit exposure · Unrestricted cash and equivalents")
AIRBNB_TITLE = "Supplemental Financial Statement Information - Schedule of Cash, Cash Equivalents and Restricted Cash (Details)"
AIRBNB_QUERY = "Cash cash equivalents restricted cash funds held on behalf of customers"
VISA_QUERY = "U.S. litigation escrow Customer collateral Prepaid expenses and other current assets"
VISA_NOTE_END = (
    "The Company reconciles cash, cash equivalents, restricted cash and restricted cash equivalents reported on the "
    "consolidated balance sheets that aggregate to the beginning and ending balances shown in the consolidated statements "
    "of cash flows as follows:"
)
NOTE_FIELDS = {
    HDFC: {"restricted_cash": HDFC_NOTE},
    GOLDMAN: {"cash": GOLDMAN_UNRESTRICTED},
    AIRBNB: {"cash_held_for_customers": ("disclosed:CashHeldForCustomers",
                                       "Cash and cash equivalents included in funds receivable and amounts held on behalf of customers")},
    VISA: {
        "restricted_cash_litigation": ("disclosed:LitigationEscrowCash", "U.S. litigation escrow"),
        "cash_held_for_customers": ("disclosed:CustomerCollateralCash", "Customer collateral"),
        "restricted_cash_in_other_assets": ("disclosed:RestrictedCashInOtherCurrentAssets", "Prepaid expenses and other current assets"),
    },
}
NET = {AXP, BAC, BRK, CITI, CHUBB, GEV, HDFC, JPM, MORGAN}
GAPS = {
    GE: "The balance-sheet cash line includes restricted cash. The separately reported run-off insurance cash sits in other assets.",
    MUFG: "The cash-flow total includes restricted amounts held both in bank deposits and in other assets.",
    WFC: "The filing reports cash and restricted cash together. The cash-flow total and the bank balance-sheet lines have different scopes.",
}
PROFILED = FACE.keys() | TAGGED.keys() | NOTE_FIELDS.keys()
PINNED = PROFILED | GAPS.keys()
RECURRING = recurring_annual_rules(PINNED - {HDFC, SBUX})
BALANCE_TITLES = TITLES | {"statement of financial position", "consolidated and combined statement of financial position"}


def rule_key(cik, report):
    return annual_rule_key(cik, report, PINNED, RECURRING)


def cash_requires_scope_review(cik, report):
    return rule_key(cik, report) in CORRECT_EXISTING


def goldman_pdf(report):
    year = report["end"][:4]
    return f"https://www.goldmansachs.com/investor-relations/financials/10k/{year}/{year}-10-k.pdf"


def note_source(key, cik, report, part):
    if key == GOLDMAN:
        return part["source"] == goldman_pdf(report) and "table_url" not in part
    if key == VISA:
        return (part["source"] == ENDPOINT and part.get("table_url") == report["url"] and
                bool(re.fullmatch(r"[0-9a-f]{16}", part.get("table_sha256_16", ""))))
    filename = {HDFC: "R86.htm", AIRBNB: "R45.htm"}.get((cik, report["accession"]))
    return valid_table_source(part, report, filename)


def cash_gap(cik, report, facts):
    return None if "cash" in facts else GAPS.get(rule_key(cik, report))


def cash_facts(cik, report, period, evidence):
    """Reconstruct the published amounts from reviewed, same-accession evidence."""
    key = rule_key(cik, report)
    face, tagged = FACE.get(key, {}), TAGGED.get(key, {})
    note = NOTE_FIELDS.get(key, {})
    inputs = evidence["lines"]
    if ((period["period_kind"], period["filing"], period["end"]) != ("annual", report["accession"], report["end"])
            or not inputs or inputs.keys() != (face.keys() | tagged.keys() | note.keys())):
        raise ValueError("Cash evidence is outside the selected annual filing")
    facts = period["facts"]
    assets = facts["assets"]
    scope = (None, report["accession"], period["currency"], report["filed"], report["form"], report["url"])
    keys = ("start", "accession", "unit", "filed", "form", "url")
    if tuple(assets[k] for k in keys) != scope or (face and evidence["asset_anchor"] != assets["value"]):
        raise ValueError("Cash evidence and annual asset anchor have different filing scopes")

    result = {}
    for field, part in inputs.items():
        tag, label = (face if field in face else tagged if field in tagged else note)[field]
        if ((part["tag"], part["line"], part["sign"]) != (tag, label, 1)
                or type(part["value"]) is not int or not 0 <= part["value"] <= assets["value"]
                or tuple(part[k] for k in keys) != scope or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
                or (field in face and not valid_table_source(part, report))
                or (field in note and not note_source(key, cik, report, part))
                or (field in tagged and (part["source"] != SEC.format(cik) or "table_url" in part))):
            raise ValueError(f"Unverified cash balance for {field}")
        result[field] = {**part, "tag": TAG, "locator": label, "components": [part]}
    if key in RESTRICTED_ROUNDING:
        increment = RESTRICTED_ROUNDING[key]
        if result["restricted_cash"]["value"] % increment:
            raise ValueError("Cash restriction value conflicts with the filed precision")
        result["restricted_cash"]["rounding_increment"] = increment
    if key in NET:
        restricted = inputs["restricted_cash"]
        if key == HDFC:
            filed = facts[BROAD]
            if tuple(filed[k] for k in keys) != scope or type(filed["value"]) is not int or not 0 <= filed["value"] <= assets["value"]:
                raise ValueError("HDFC inclusive cash balance is outside the annual filing scope")
            combined = {**filed, "line": filed["locator"], "sign": 1}
        else:
            combined = inputs[BROAD]
        value = combined["value"] - restricted["value"]
        if value < 0:
            raise ValueError("Restricted cash exceeds the reported inclusive balance")
        result["cash"] = {**combined, "tag": TAG, "value": value,
                          "locator": "Cash and cash equivalents after removing the disclosed restricted amount",
                          "components": [combined, {**restricted, "sign": -1}]}
        if key in RESTRICTED_ROUNDING:
            result["cash"]["rounding_increment"] = RESTRICTED_ROUNDING[key]
    if key == GOLDMAN:
        inclusive, unrestricted = inputs[BROAD], inputs["cash"]
        restricted = inclusive["value"] - unrestricted["value"]
        rounded = inputs["restricted_cash_reported"]["value"]
        if restricted < 0 or rounded % 10_000_000 or abs(restricted - rounded) > 5_000_000:
            raise ValueError("Goldman unrestricted cash and the rounded segregation disclosure do not reconcile")
        result["restricted_cash_reported"]["rounding_increment"] = 10_000_000
        result["restricted_cash"] = {
            **inclusive, "tag": TAG, "value": restricted,
            "locator": "Total cash and equivalents less the separately reported unrestricted balance",
            "components": [inclusive, {**unrestricted, "sign": -1}],
        }
    if key in {AIRBNB, VISA}:
        operating = facts["cash"]
        outside = ["cash_held_for_customers", "restricted_cash"] if key == AIRBNB else list(note)
        parts = [inputs[field] for field in outside]
        total = sum(part["value"] for part in parts)
        if tuple(operating[k] for k in keys) != scope or operating["value"] + total != inputs[BROAD]["value"]:
            raise ValueError("Operating, customer and restricted cash do not reconcile to cash-flow total")
        if key == VISA:
            result["restricted_cash"] = {
                **parts[0], "tag": TAG, "value": total, "components": parts,
                "locator": "Note 4 · Sum of litigation escrow, customer collateral and other restricted cash",
            }
    if key == PGR and result["cash"]["value"] + result["restricted_cash"]["value"] != result[BROAD]["value"]:
        raise ValueError("Progressive cash lines do not reconcile")
    if key in {BAC, CITI, JPM, MIZUHO, MUFG, MORGAN}:
        deposits = [result.get(field) or facts[field]
                    for field in ("cash_due_from_banks", "interest_bearing_deposits_at_banks")]
        total_field = "cash_and_bank_deposits" if key == MUFG else "cash" if key == MIZUHO else BROAD
        if (any(tuple(part[k] for k in keys) != scope for part in deposits)
                or sum(part["value"] for part in deposits) != result[total_field]["value"]):
            raise ValueError("Cash and bank deposit lines do not reconcile")
    if key == MUFG:
        combined, deposits = inputs[BROAD], inputs["cash_and_bank_deposits"]
        other = combined["value"] - deposits["value"]
        if other < 0:
            raise ValueError("MUFG cash-flow total is below the balance-sheet bank deposits")
        result["restricted_cash_in_other_assets"] = {
            **combined, "tag": TAG, "value": other,
            "locator": "Consolidated cash flow · Restricted cash included in other assets",
            "components": [combined, {**deposits, "sign": -1}],
        }
    return result


def enrich_cash(cache, obj, meta, cik, report, period):
    key = rule_key(cik, report)
    face, tagged = FACE.get(key, {}), TAGGED.get(key, {})
    if key not in PROFILED or ("cash" in period["facts"] and key not in REVIEW_EXISTING):
        return period
    stock = {**period, "start": None}
    evidence = {"lines": {}}
    parts = evidence["lines"]

    def part(tag, line, value, receipt, **evidence):
        return {**evidence, "value": value, "line": line, "tag": tag, "sign": 1, "source": receipt["url"],
                "sha256": receipt["sha256"], "unit": period["currency"], "start": None,
                **{k: report[k] for k in ("accession", "filed", "form", "url")}}

    if face:
        table, index, receipt, table_source = annual_table(cache, cik, report, period, "balance_sheet", None)
        if " ".join(table["title"].casefold().split()) not in BALANCE_TITLES:
            raise ValueError("Cash is outside a recognized consolidated balance sheet")
        scale = table["money_scale"]
        rows = table["rows"]
        dimension = next((i for i, row in enumerate(rows) if row[1] is None), len(rows))
        consolidated = rows[:dimension]
        end, = (i for i, row in enumerate(consolidated) if row[1] in ASSETS and row[index] is not None)
        evidence["asset_anchor"] = scaled(consolidated[end][index], scale)
        for field, (tag, label) in face.items():
            value, = (scaled(row[index], scale) for row in consolidated[:end] if row[:2] == [label, tag])
            exact = exact_sec_amount(obj, stock, report, tag)
            if exact is not None and exact != value:
                raise ValueError(f"Cash line disagrees with SEC Company Facts for {label}")
            parts[field] = part(tag, label, value, receipt, **table_source)
    if key == HDFC:
        year = report["end"][:4]
        tables, digests, receipt = filing_tables(cache, cik, report, "Restricted Cash")
        url = report["path"] + "/R86.htm"
        table, = (t for t in tables if t["source"] == "xbrl report" and t["title"] == HDFC_TITLE and t["url"] == url)
        expected = ["line", f"Mar. 31, {year} INR (₨)", f"Mar. 31, {year} USD ($)", f"Mar. 31, {int(year)-1} INR (₨)"]
        if period["currency"] != "INR" or report["end"] != f"{year}-03-31" or table["columns"] != expected:
            raise ValueError("Unexpected HDFC restricted-cash period or currency")
        line, = (r for r in table["rows"] if r[0] == "Restricted cash")
        amount = re.fullmatch(r"₨ ([0-9,]+\.[0-9]+)", str(line[1]))
        if not amount or table["units"] != "$ in Millions":
            raise ValueError("Missing INR restricted cash amount")
        parts["restricted_cash"] = part(*HDFC_NOTE, scaled(amount[1].replace(",", ""), 1_000_000), receipt,
                                        table_url=url, table_sha256_16=digests.get(url, ""))
    for field, (tag, label) in tagged.items():
        value = exact_sec_amount(obj, stock, report, tag)
        if value is None:
            raise ValueError(f"Missing exact SEC Company Facts cash balance for {label}")
        parts[field] = part(tag, label, value, meta)

    if key in CORRECT_EXISTING and "cash" in period["facts"]:
        reported = period["facts"]["cash"]
        inclusive = parts[BROAD]
        if (reported["value"], reported["unit"]) != (inclusive["value"], inclusive["unit"]):
            raise ValueError("Existing tagged cash disagrees with the reviewed inclusive balance")
    if key == GOLDMAN:
        year = int(report["end"][:4])
        url = goldman_pdf(report)
        raw, receipt = cache.get(url, 8760)
        pages = pdf_pages(raw)
        if (receipt["url"] != url or period["currency"] != "USD" or report["end"] != f"{year}-12-31"
                or f"For the fiscal year ended December 31, {year}" not in pages[0]):
            raise ValueError("Goldman issuer 10-K does not match the selected fiscal year")
        statements, = (page for page in pages if re.search(r"^Consolidated Balance Sheets *$", page, re.M)
                       and re.search(rf"^\$ in millions +{year} +{year-1}\b", page, re.M))
        if scaled(column(statements, "Cash and cash equivalents", 2), 1_000_000) != parts[BROAD]["value"]:
            raise ValueError("Goldman PDF cash and EDGAR cash total disagree")
        risk, = (page for page in pages if "unrestricted cash and cash equivalents, and the concentration" in page
                 and "The table above excludes cash segregated for regulatory and" in page
                 and re.search(rf"^\$ in millions +{year} +{year-1}\b", page, re.M))
        match, = re.findall(r"^Cash and Cash Equivalents +\$([\d,]+) +\$[\d,]+\b", risk, re.M)
        parts["cash"] = part(*GOLDMAN_UNRESTRICTED, scaled(match.replace(",", ""), 1_000_000), receipt)
    if key in {AIRBNB, VISA}:
        query = AIRBNB_QUERY if key == AIRBNB else VISA_QUERY
        tables, digests, receipt = filing_tables(cache, cik, report, query)
        year = report["end"][:4]
        if key == AIRBNB:
            pinned = "R45.htm" if key == (cik, report["accession"]) else None
            table, = (t for t in tables if t["source"] == "xbrl report" and t["title"] == AIRBNB_TITLE
                      and t["units"] == "USD ($) $ in Millions" and table_belongs_to_filing(t["url"], report, pinned))
            heading, expected_end = f"Dec. 31, {year}", f"{year}-12-31"
        else:
            table, = (t for t in tables if t["source"] == "document table" and t["url"] == report["url"]
                      and t["title"].endswith(VISA_NOTE_END))
            heading, expected_end = f"September 30, {year} (in millions)", f"{year}-09-30"
        if period["currency"] != "USD" or report["end"] != expected_end or table["columns"].count(heading) != 1:
            raise ValueError("Cash note does not match the filing currency and fiscal year")
        index = table["columns"].index(heading)
        for field, (tag, label) in NOTE_FIELDS[key].items():
            amount, = (r[index] for r in table["rows"] if r[0] == label and type(r[index]) in (int, float))
            parts[field] = part(tag, label, scaled(amount, 1_000_000), receipt,
                                table_url=table["url"], table_sha256_16=digests.get(table["url"], ""))
    result = cash_facts(cik, report, period, evidence)
    return {**period, "facts": {**period["facts"], **result}, "annual_cash_balance": evidence}
