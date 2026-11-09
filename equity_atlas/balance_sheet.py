"""Recover missing liabilities from the selected SEC annual balance sheet."""

import re

from .facts import exact_sec_amount, temporary_equity_fields
from .rendered_filing import annual_table, scaled, valid_table_source

TAG = "derived:FiledBalanceSheetLiabilities"
EQUITY_TAG = "disclosed:FiledBalanceSheetEquity"
TITLES = {"consolidated balance sheet", "consolidated balance sheets", "condensed consolidated balance sheets",
          "consolidated statement of financial position", "consolidated statements of financial position"}
ASSETS = {"us-gaap:Assets", "ifrs-full:Assets"}
CLAIMS = {"us-gaap:LiabilitiesAndStockholdersEquity", "ifrs-full:EquityAndLiabilities"}
EQUITY = {"us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "ifrs-full:Equity"}
PARENT = {"us-gaap:StockholdersEquity", "ifrs-full:EquityAttributableToOwnersOfParent"}
MINORITY = {"us-gaap:MinorityInterest", "us-gaap:NonredeemableNoncontrollingInterest",
            "ifrs-full:NoncontrollingInterests"}
TEMPORARY = {
    "temporary_equity_total": {"us-gaap:TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterests"},
    "temporary_equity_parent": {"us-gaap:TemporaryEquityCarryingAmountAttributableToParent"},
    "redeemable_nci": {"us-gaap:RedeemableNoncontrollingInterestEquityCarryingAmount",
                      "us-gaap:RedeemableNoncontrollingInterestEquityCommonCarryingAmount"},
}
TEMP_TAGS = set().union(*TEMPORARY.values())
TOTAL = {"us-gaap:Liabilities", "ifrs-full:Liabilities"}
CURRENT = {"us-gaap:LiabilitiesCurrent", "ifrs-full:CurrentLiabilities"}
NONCURRENT = {"us-gaap:LiabilitiesNoncurrent", "ifrs-full:NoncurrentLiabilities"}
MARRIOTT = 1048286
MAR_CONTRACT = "us-gaap:ContractWithCustomerLiabilityNoncurrent"
MAR_MEMBERS = ("Liability for guest loyalty program", "Deferred revenue")
HELD_FOR_SALE = "ifrs-full:LiabilitiesIncludedInDisposalGroupsClassifiedAsHeldForSale"
EQUITY_HEADERS = {
    "us-gaap:StockholdersEquityAbstract", "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterestAbstract",
}
SUBGROUPS = {
    "us-gaap:LiabilitiesNoncurrentAbstract": "us-gaap:DeferredCreditsAndOtherLiabilitiesNoncurrent",
    "us-gaap:OtherLiabilitiesNoncurrentAbstract": "us-gaap:LiabilitiesOtherThanLongtermDebtNoncurrent",
}
NONCURRENT_LINES = {
    "abt:PostEmploymentObligationsDeferredIncomeTaxesAndOtherLongTermLiabilities",
    "amzn:LeaseLiabilityNoncurrent", "duk:OtherOperatingLeaseLiabilityNoncurrent",
    "hca:IncomeTaxesAndOtherLiabilities", "hca:ProfessionalLiabilityRisks", "mcd:LongTermLeaseLiabilityNoncurrentNet",
} | {"us-gaap:" + name for name in (
    "AccruedIncomeTaxesNoncurrent", "AccumulatedDeferredInvestmentTaxCredit", "AssetRetirementObligationsNoncurrent",
    "DeferredCreditsAndOtherLiabilities", "DeferredCreditsAndOtherLiabilitiesNoncurrent",
    "DeferredIncomeTaxLiabilitiesNet", "DeferredIncomeTaxesAndOtherLiabilitiesNoncurrent",
    "DeferredIncomeTaxesAndOtherTaxLiabilitiesNoncurrent", "DeferredRevenueNoncurrent",
    "DeferredTaxAndOtherLiabilitiesNoncurrent", "FinanceLeaseLiabilityNoncurrent",
    "LiabilitiesOfDisposalGroupIncludingDiscontinuedOperationNoncurrent", "LiabilitiesOtherThanLongtermDebtNoncurrent",
    "LiabilityForUncertainTaxPositionsNoncurrent", "LitigationReserveNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
    "LongTermDebtNoncurrent", "OperatingLeaseLiabilityNoncurrent", "OtherLiabilitiesNoncurrent",
    "PensionAndOtherPostretirementDefinedBenefitPlansLiabilitiesNoncurrent", "PostemploymentBenefitsLiabilityNoncurrent",
    "RegulatoryLiabilityNoncurrent",
)}


def supported(report, period):
    return (report["form"] in {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
            and "liabilities" not in period["facts"] and "assets" in period["facts"]
            and "liabilities" not in period.get("conflicts", ()))


def read_balance(table, index, cik):
    scale = table["money_scale"]
    rows = table["rows"]
    # Dimensions are appended by the SEC renderer after the consolidated face.
    stop = next((i for i, row in enumerate(rows) if row[1] is None), len(rows))
    dimensions = rows[stop:]
    rows = rows[:stop]
    positions = {}

    def line(i):
        label, tag, *_ = rows[i]
        value = rows[i][index]
        if type(value) not in (int, float):
            raise ValueError(f"Missing numeric balance-sheet line {label}")
        return {"line": label, "tag": tag, "value": scaled(value, scale)}

    def locate(tags, *, required=False):
        matches = [i for i, row in enumerate(rows) if row[1] in tags and row[index] is not None]
        if len(matches) > 1 or required and not matches:
            raise ValueError(f"Missing or ambiguous balance-sheet concept: {sorted(tags)}")
        return matches[0] if matches else None

    def take(key, tags, *, required=False):
        i = locate(tags, required=required)
        if i is not None:
            positions[key] = i
            return line(i)
        return None

    assets = take("assets", ASSETS, required=True)
    combined = take("combined", CLAIMS, required=True)
    equity = take("equity", EQUITY) or take("equity", PARENT, required=True)
    if equity["tag"] in PARENT and locate(MINORITY) is not None:
        raise ValueError("Parent equity cannot stand in for total equity when the face has noncontrolling interests")
    if not positions["assets"] < positions["equity"] < positions["combined"]:
        raise ValueError("Balance-sheet anchors do not belong to the consolidated face")
    temporary = {key: item for key, tags in TEMPORARY.items() if (item := take(key, tags))}
    current = take("current", CURRENT)
    noncurrent = take("noncurrent", NONCURRENT)
    direct = take("total", TOTAL)
    if direct:
        method, parts = "reported_total", [direct]
    elif current and noncurrent:
        method, parts = "classified_subtotals", [current, noncurrent]
        held = take("held_for_sale", {HELD_FOR_SALE})
        # Some balance sheets print this line after current liabilities but
        # include it in the subtotal. Add it only if the claims require it.
        if held and max(positions["current"], positions["noncurrent"]) < positions["held_for_sale"] < positions["combined"]:
            claims = combined["value"] - equity["value"] - sum(
                temporary[key]["value"] for key in temporary_equity_fields(temporary)
            )
            if abs(claims - sum(part["value"] for part in parts)) > scale:
                parts.append(held)
    elif current:
        method, parts = "current_and_long_term_lines", [current]
        start = positions["current"]
        ends = [i for i, row in enumerate(rows) if row[1] in EQUITY_HEADERS and i > start]
        if len(ends) != 1 or ends[0] > positions["equity"]:
            raise ValueError("Missing unique equity heading after current liabilities")
        end = ends[0]
        groups = {tag: i for i, (_, tag, *_) in enumerate(rows[start + 1:end], start + 1) if tag in SUBGROUPS}
        skipped = set()
        for heading, heading_pos in groups.items():
            subtotal = locate({SUBGROUPS[heading]})
            if subtotal is None:
                continue
            if not heading_pos < subtotal < end:
                raise ValueError("Noncurrent liability subtotal is outside its section")
            children = [i for i in range(heading_pos + 1, subtotal) if rows[i][index] is not None]
            if not children or abs(sum(line(i)["value"] for i in children) - line(subtotal)["value"]) > scale:
                raise ValueError("Noncurrent liability subsection does not reconcile")
            skipped.update(children)
        for i in range(start + 1, end):
            if i in skipped or rows[i][index] is None or rows[i][1] in TEMP_TAGS:
                continue
            if rows[i][1] not in NONCURRENT_LINES:
                raise ValueError(f"Unreviewed long-term liability line {rows[i][1]}")
            parts.append(line(i))
    else:
        raise ValueError("Balance sheet has no liabilities total or current-liabilities subtotal")
    if cik == MARRIOTT and method == "current_and_long_term_lines":
        # These two lines appear on the face of the filed statement. SEC R5
        # presents them under separate dimensions sharing a single concept.
        member = None
        matches = {}
        for label, tag, *values in dimensions:
            if tag is None:
                member = label
            elif member in MAR_MEMBERS and tag == MAR_CONTRACT:
                if member in matches or type(values[index - 2]) not in (int, float):
                    raise ValueError("Missing unique Marriott noncurrent contract liability")
                matches[member] = {"line": member, "tag": tag, "value": scaled(values[index - 2], scale),
                                   "member": member}
        if matches.keys() != set(MAR_MEMBERS):
            raise ValueError("Marriott contract-liability presentation changed")
        parts.extend(matches[member] for member in MAR_MEMBERS)
    return {"method": method, "scale": scale, "assets": assets, "combined": combined, "equity": equity,
            "temporary": temporary, "parts": parts}


def balance_facts(report, period, evidence):
    """Verify both the selected liability lines and the independent claims equation."""
    if ((period["period_kind"], period["filing"], period["end"]) != ("annual", report["accession"], report["end"]) or
            not valid_table_source(evidence, report) or not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])):
        raise ValueError("Liability evidence is outside the selected SEC annual balance sheet")

    scale = evidence["scale"]
    parts = evidence["parts"]
    method = evidence["method"]
    dimensional = [part for part in parts if "member" in part]
    if dimensional and (
            not report["path"].startswith(f"https://www.sec.gov/Archives/edgar/data/{MARRIOTT}/")
            or method != "current_and_long_term_lines"
            or tuple((part["tag"], part["member"], part["line"]) for part in dimensional) !=
            tuple((MAR_CONTRACT, member, member) for member in MAR_MEMBERS)):
        raise ValueError("Unreviewed dimensional liability line")
    tags = [part["tag"] for part in parts if "member" not in part]
    if scale not in {1, 1_000, 1_000_000, 1_000_000_000} or len(set(tags)) != len(tags):
        raise ValueError("Invalid liability line scale or duplicate concept")
    if method == "reported_total":
        valid_lines = len(tags) == 1 and tags[0] in TOTAL
    elif method == "classified_subtotals":
        valid_lines = (len(tags) in {2, 3} and tags[0] in CURRENT and tags[1] in NONCURRENT and
                       (len(tags) == 2 or tags[2] == HELD_FOR_SALE))
    else:
        valid_lines = (method == "current_and_long_term_lines" and len(tags) >= 2 and tags[0] in CURRENT
                       and set(tags[1:]) <= NONCURRENT_LINES)
    if not valid_lines or any(type(part["value"]) is not int or part["value"] < 0 or not part["line"] for part in parts):
        raise ValueError("Unverified balance-sheet liability components")

    facts = period["facts"]
    amounts = {}
    for key, concepts in (("assets", ASSETS), ("combined", CLAIMS), ("equity", EQUITY | PARENT)):
        part = evidence[key]
        if part["tag"] not in concepts or type(part["value"]) is not int or not part["line"]:
            raise ValueError(f"Invalid balance-sheet {key} anchor")
        amounts[key] = part["value"]
    equity_key = "total_equity" if "total_equity" in facts and facts["total_equity"]["tag"] != EQUITY_TAG else "book"
    scope = (None, report["accession"], period["currency"], report["filed"], report["form"], report["url"])
    scope_keys = ("start", "accession", "unit", "filed", "form", "url")
    for key, expected in (("assets", amounts["assets"]), (equity_key, amounts["equity"])):
        fact = facts[key]
        if fact["value"] != expected or tuple(fact[k] for k in scope_keys) != scope:
            raise ValueError(f"Filed balance-sheet amount disagrees with annual {key}")

    temporary = evidence["temporary"]
    for key, item in temporary.items():
        if item["tag"] not in TEMPORARY[key] or type(item["value"]) is not int or item["value"] < 0 or not item["line"]:
            raise ValueError("Unverified temporary-equity balance")
        if key in period.get("conflicts", ()) or (key in facts and (
                facts[key]["value"] != item["value"] or tuple(facts[key][k] for k in scope_keys) != scope)):
            raise ValueError("Filed temporary equity disagrees with the tagged amount")
    selected = temporary_equity_fields(temporary)
    existing = temporary_equity_fields(facts)
    if not set(existing) <= temporary.keys():
        raise ValueError("Temporary equity from the annual filing is absent from the balance-sheet evidence")
    total = sum(part["value"] for part in parts)
    residual = amounts["combined"] - amounts["equity"] - sum(temporary[key]["value"] for key in selected) - total
    if amounts["assets"] != amounts["combined"] or abs(residual) > scale:
        raise ValueError("Liabilities, permanent equity and temporary equity do not reconcile to assets")

    provenance = {key: evidence[key] for key in ("source", "sha256", "table_url", "table_sha256_16")}
    provenance.update({key: report[key] for key in ("url", "accession", "filed", "form")})
    provenance.update(unit=period["currency"], start=None)
    locators = {"reported_total": "Total liabilities reported on the balance sheet",
                "classified_subtotals": "Sum of filed liability subtotals",
                "current_and_long_term_lines": "Sum of current liabilities and filed long-term liability lines"}
    result = {"liabilities": {
        **provenance, "value": total, "tag": TAG, "locator": locators[method],
        "components": [{**part, "sign": 1, "table_url": provenance["table_url"]} for part in parts],
        "balance_rounding_residual": residual,
    }}
    if equity_key == "book":
        result["total_equity"] = {**provenance, "value": amounts["equity"], "tag": EQUITY_TAG,
                                  "locator": evidence["equity"]["line"]}
    for key, item in temporary.items():
        if key not in facts or facts[key]["tag"] == EQUITY_TAG:
            result[key] = {**provenance, "value": item["value"], "tag": EQUITY_TAG, "locator": item["line"]}
    return result


def enrich_balance(cache, obj, cik, report, period):
    table, index, receipt, source = annual_table(cache, cik, report, period, "balance_sheet", None)
    if " ".join(table["title"].casefold().split()) not in TITLES:
        raise ValueError("Rendered table is not a recognized annual balance-sheet title")
    evidence = {**read_balance(table, index, cik), **source, "source": receipt["url"], "sha256": receipt["sha256"]}
    stock = {**period, "start": None}
    for part in (*evidence["parts"], evidence["equity"], *evidence["temporary"].values()):
        if "member" in part:
            continue  # Company Facts omits the separate dimensional contexts.
        exact = exact_sec_amount(obj, stock, report, part["tag"])
        if exact is not None and exact != part["value"]:
            raise ValueError(f"Balance-sheet line disagrees with SEC Company Facts for {part['line']}")
    result = balance_facts(report, period, evidence)
    return {**period, "facts": {**period["facts"], **result}, "annual_balance_sheet": evidence}
