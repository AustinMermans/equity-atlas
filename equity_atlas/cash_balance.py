"""Read annual cash balances with the scope stated in the selected filing."""

import re

from .balance_sheet import ASSETS, TITLES
from .facts import annual_rule_key, exact_sec_amount, recurring_annual_rules
from .fetch import SEC
from .rendered_filing import annual_table, scaled, valid_table_source

TAG = "derived:FiledCashBalance"
TOTAL = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
RESTRICTED = "us-gaap:RestrictedCashAndCashEquivalents"
BROAD = "cash_including_restricted"
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
NET = {AXP, BAC, BRK, CITI, CHUBB, GEV, JPM}
GAPS = {
    GE: "The balance-sheet cash line includes restricted cash. The separately reported run-off insurance cash sits in other assets.",
    HDFC: "The filed cash and due from banks balance includes restricted reserve cash.",
    MUFG: "The cash-flow total includes restricted amounts held both in bank deposits and in other assets.",
    WFC: "The filing reports cash and restricted cash together. The cash-flow total and the bank balance-sheet lines have different scopes.",
}
PROFILED = FACE.keys() | TAGGED.keys()
PINNED = PROFILED | GAPS.keys()
RECURRING = recurring_annual_rules(PINNED - {HDFC, SBUX})
BALANCE_TITLES = TITLES | {"statement of financial position", "consolidated and combined statement of financial position"}


def rule_key(cik, report):
    return annual_rule_key(cik, report, PINNED, RECURRING)


def cash_gap(cik, report, facts):
    return None if "cash" in facts else GAPS.get(rule_key(cik, report))


def cash_facts(cik, report, period, evidence):
    """Reconstruct the published amounts from reviewed, same-accession evidence."""
    key = rule_key(cik, report)
    face, tagged = FACE.get(key, {}), TAGGED.get(key, {})
    inputs = evidence["lines"]
    if ((period["period_kind"], period["filing"], period["end"]) != ("annual", report["accession"], report["end"])
            or not inputs or inputs.keys() != (face.keys() | tagged.keys())):
        raise ValueError("Cash evidence is outside the selected annual filing")
    facts = period["facts"]
    assets = facts["assets"]
    scope = (None, report["accession"], period["currency"], report["filed"], report["form"], report["url"])
    keys = ("start", "accession", "unit", "filed", "form", "url")
    if tuple(assets[k] for k in keys) != scope or (face and evidence["asset_anchor"] != assets["value"]):
        raise ValueError("Cash evidence and annual asset anchor have different filing scopes")

    result = {}
    for field, part in inputs.items():
        tag, label = (face if field in face else tagged)[field]
        if ((part["tag"], part["line"], part["sign"]) != (tag, label, 1)
                or type(part["value"]) is not int or not 0 <= part["value"] <= assets["value"]
                or tuple(part[k] for k in keys) != scope or not re.fullmatch(r"[0-9a-f]{64}", part["sha256"])
                or (field in face and not valid_table_source(part, report))
                or (field in tagged and (part["source"] != SEC.format(cik) or "table_url" in part))):
            raise ValueError(f"Unverified cash balance for {field}")
        result[field] = {**part, "tag": TAG, "locator": label, "components": [part]}
    if key in RESTRICTED_ROUNDING:
        increment = RESTRICTED_ROUNDING[key]
        if result["restricted_cash"]["value"] % increment:
            raise ValueError("Cash restriction value conflicts with the filed precision")
        result["restricted_cash"]["rounding_increment"] = increment
    if key in NET:
        combined, restricted = inputs[BROAD], inputs["restricted_cash"]
        value = combined["value"] - restricted["value"]
        if value < 0:
            raise ValueError("Restricted cash exceeds the reported inclusive balance")
        result["cash"] = {**combined, "tag": TAG, "value": value,
                          "locator": "Cash and cash equivalents after removing the disclosed restricted amount",
                          "components": [combined, {**restricted, "sign": -1}]}
        if key in RESTRICTED_ROUNDING:
            result["cash"]["rounding_increment"] = RESTRICTED_ROUNDING[key]
    if key == PGR and result["cash"]["value"] + result["restricted_cash"]["value"] != result[BROAD]["value"]:
        raise ValueError("Progressive cash lines do not reconcile")
    if key in {BAC, CITI, JPM, MIZUHO, MUFG}:
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
    if not (face or tagged) or "cash" in period["facts"]:
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
    for field, (tag, label) in tagged.items():
        value = exact_sec_amount(obj, stock, report, tag)
        if value is None:
            raise ValueError(f"Missing exact SEC Company Facts cash balance for {label}")
        parts[field] = part(tag, label, value, meta)

    result = cash_facts(cik, report, period, evidence)
    return {**period, "facts": {**period["facts"], **result}, "annual_cash_balance": evidence}
