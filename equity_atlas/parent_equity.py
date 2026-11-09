"""Recover parent equity by reconciling the balance sheet and equity statement."""

from datetime import datetime
import re

from .balance_sheet import EQUITY, MINORITY, TITLES
from .rendered_filing import ENDPOINT, annual_table, decode_response, request_bytes, scaled, valid_table_source
from .sec_rendered import rendered_number

TAG = "derived:FiledParentEquity"
AEM = 2809
CNQ = 1017413
TD = 947263
VISA = 1403161
TD_NONCOMMON = ("Preferred shares and other equity instruments [member]",
                "Preferred shares and other equity instruments [member] Treasury shares [member]")
VISA_NONCOMMON = ("Preferred Stock and Additional Paid-in Capital",)
# Use the monetary equity columns, omitting nested duplicates and share counts.
COLUMNS = {
    AEM: ("Common Shares Outstanding", "Stock Options", "Contributed Surplus", "Retained Earnings (Deficit)", "Other Reserves"),
    1730168: ("Common Stock", "Additional Paid-in Capital", "Retained Earnings", "Accumulated Other Comprehensive Income (Loss)"),
    CNQ: ("Share capital", "Retained earnings", "Accumulated other comprehensive income"),
    200406: ("Retained Earnings and Additional paid-in capital", "Accumulated Other Comprehensive Income (Loss)",
             "Common Stock Issued Amount", "Treasury Stock Amount"),
    353278: ("Share capital", "Treasury shares", "Retained earnings", "Other reserves"),
    804328: ("Common Stock and Paid-in Capital [Member]", "Retained Earnings [Member]", "Accumulated Other Comprehensive Income"),
    310764: ("Common Stock", "Additional Paid-In Capital", "Retained Earnings", "Accumulated Other Comprehensive Income (Loss)"),
    TD: ("Contributed surplus [member]", "Retained earnings [member]", "Accumulated other comprehensive income (loss) [member]",
         "Common shares [member]", "Common shares [member] Treasury shares [member]", *TD_NONCOMMON),
    VISA: (*VISA_NONCOMMON, "Common Stock and Additional Paid-in Capital", "Right to Recover for Covered Losses",
           "Accumulated Income", "Accumulated Other Comprehensive Income (Loss)"),
}
NONCOMMON = {TD: TD_NONCOMMON, VISA: VISA_NONCOMMON}
NCI = re.compile(r"non[\s-]*controlling|minority", re.I)


def supported(cik, report, period):
    return (cik in COLUMNS and report["form"] in {"10-K", "20-F", "40-F"} and
            "book" not in period["facts"] and "total_equity" in period["facts"] and
            not {"book", "minority"} & set(period.get("conflicts", ())))


def money(value, currency, scale):
    if currency == "DKK" and isinstance(value, str) and value.startswith("kr "):
        value = rendered_number(value.removeprefix("kr "))
    if type(value) not in (int, float):
        raise ValueError("Missing numeric equity amount")
    return scaled(value, scale)


def closing_label(label, end):
    match = re.search(r" at ([A-Za-z]{3,4}\.? \d{1,2}, \d{4})$", label)
    if not match:
        return False
    stamp = match[1].replace(".", "").replace("Sept ", "Sep ")
    return datetime.strptime(stamp, "%b %d, %Y").date().isoformat() == end


def read_equity(cache, cik, report, period):
    balance, idx, receipt, source = annual_table(cache, cik, report, period, "balance_sheet", None)
    if " ".join(balance["title"].casefold().split()) not in TITLES | {"balance sheet"}:
        raise ValueError("Unexpected balance-sheet title")
    rows = balance["rows"]
    face = rows[:next((i for i, row in enumerate(rows) if row[1] is None), len(rows))]
    matches = [row for row in face if row[1] in EQUITY and row[idx] is not None]
    row, = matches
    if any(r[idx] is not None and (r[1] in MINORITY or NCI.search(r[0])) for r in face):
        raise ValueError("Balance sheet displays a separate noncontrolling interest")
    currency = period["currency"]
    balance_total = money(row[idx], currency, balance["money_scale"])
    face_evidence = {**source, "source": receipt["url"], "sha256": receipt["sha256"],
                     "value": balance_total, "line": row[0], "tag": row[1]}

    raw, receipt = cache.get(ENDPOINT, 8760, post_json=request_bytes(f"{cik:010d}", "annual", report["accession"], "equity"))
    data, digests = decode_response(raw, receipt, report, cik, "annual")
    equity = data["equity"]
    url, = equity["sources"]
    columns = equity["columns"]
    needed = ("Total", *COLUMNS[cik])
    if (currency != equity["currency"] or any(columns.count(col) != 1 for col in needed)
            or any(NCI.search(col) for col in columns)
            or not re.search(r"equity", equity["title"], re.I)):
        raise ValueError("Unexpected equity-statement columns or currency")
    row, = [r for r in equity["rows"] if r[1] in EQUITY and closing_label(r[0], report["end"])]
    scale = equity["money_scale"]
    return {
        "balance": face_evidence, "table_url": url, "table_sha256_16": digests.get(url, ""),
        "source": receipt["url"], "sha256": receipt["sha256"], "scale": scale,
        "total": money(row[columns.index("Total")], currency, scale), "line": row[0], "tag": row[1],
        "parts": [{"line": col, "value": money(row[columns.index(col)], currency, scale)} for col in COLUMNS[cik]],
    }


def equity_facts(cik, report, period, evidence):
    facts = period["facts"]
    if ((period["period_kind"], period["filing"], period["end"]) != ("annual", report["accession"], report["end"])
            or cik not in COLUMNS or facts.get("minority", {}).get("value", 0)
            or not all(valid_table_source(e, report) and re.fullmatch(r"[0-9a-f]{64}", e["sha256"])
                       for e in (evidence, evidence["balance"]))
            or evidence["balance"]["table_url"] == evidence["table_url"]):
        raise ValueError("Parent equity evidence is outside the selected SEC annual statement")
    scale = evidence["scale"]
    total = evidence["total"]
    face = evidence["balance"]
    parts = evidence["parts"]
    anchor = facts["total_equity"]
    if (scale not in {1, 1_000, 1_000_000, 1_000_000_000} or type(total) is not int
            or evidence["tag"] not in EQUITY or not closing_label(evidence["line"], report["end"])
            or face["tag"] not in EQUITY or not face["line"] or face["value"] != total
            or tuple(part["line"] for part in parts) != COLUMNS[cik]
            or any(type(part["value"]) is not int for part in parts)
            or sum(part["value"] for part in parts) != total
            or (anchor["value"], anchor["start"], anchor["accession"], anchor["unit"], anchor["url"]) !=
            (total, None, report["accession"], period["currency"], report["url"])):
        raise ValueError("Parent equity columns do not reconcile to filed total equity")
    if "common_book" in facts and facts["common_book"]["tag"] != TAG:
        filed_common = facts["common_book"]["value"]
    else:
        filed_common = None
    noncommon_cols = NONCOMMON.get(cik, ())
    noncommon = sum(part["value"] for part in parts if part["line"] in noncommon_cols)
    if (noncommon < 0 or ("preferred" in facts and facts["preferred"]["value"] != noncommon)
            or (filed_common is not None and filed_common != total - noncommon)):
        raise ValueError("Preferred equity columns disagree with the balance sheet")

    provenance = {k: evidence[k] for k in ("source", "sha256", "table_url", "table_sha256_16")}
    provenance.update({k: report[k] for k in ("url", "accession", "filed", "form")})
    provenance.update(unit=period["currency"], start=None, tag=TAG)
    terms = [{**part, "sign": 1, "table_url": evidence["table_url"]} for part in parts]
    result = {"book": {**provenance, "value": total, "components": terms,
                       "locator": "Parent equity reconciled to the balance sheet and closing equity columns"},
              "common_book": {**provenance, "value": total - noncommon,
                              "components": [part for part in terms if part["line"] not in noncommon_cols],
                              "locator": "Sum of common-equity columns"}}
    if cik == TD:
        result["preferred_and_other_equity"] = {
            **provenance, "value": noncommon, "components": [part for part in terms if part["line"] in noncommon_cols],
            "locator": "Preferred shares and other equity instruments, net of related treasury shares",
        }
    return result


def enrich_parent_equity(cache, cik, report, period):
    evidence = read_equity(cache, cik, report, period)
    found = equity_facts(cik, report, period, evidence)
    return {**period, "facts": {**period["facts"], **found}, "annual_parent_equity": evidence}
