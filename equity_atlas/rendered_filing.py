"""Retrieve SEC-rendered statements through the public Canli connector."""

from decimal import Decimal, InvalidOperation
import json
import math
import re

from .sec_rendered import read_cash_flow

ENDPOINT = "https://canlicapital.com/mcp/canli"


def request_bytes(company, period, accession, statement=None):
    arguments = {"company": company, "period": period, "accession": accession}
    if statement:
        arguments["statement"] = statement
    return json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "run_tool", "arguments": {"name": "financial_statements", "arguments": arguments}},
    }, sort_keys=True).encode()


def parse_result(raw):
    if len(raw) > 400_000:
        raise ValueError("Unexpected rendered filing response size")
    payload = json.loads(raw)
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict) or result.get("isError") or not isinstance(result.get("structuredContent"), dict):
        raise ValueError("Canli could not retrieve the rendered SEC filing")
    return result


def decode_response(raw, receipt, report, cik, period):
    if receipt["url"] != ENDPOINT:
        raise ValueError("Unexpected rendered filing response source")
    result = parse_result(raw)
    data = result["structuredContent"]
    rows = data["filings"]["rows"]
    if data["company"]["cik"] != cik or data["period"] != period or len(rows) != 1:
        raise ValueError("Rendered response does not match the SEC registrant or reporting period")
    accession, form, filed, end, index = rows[0]
    if ((accession, form, filed, end) != tuple(report[k] for k in ("accession", "form", "filed", "end")) or
            not index.startswith(report["path"] + "/")):
        raise ValueError("Rendered response does not match the exact SEC filing")
    sources = result["_meta"]["canlicapital.com/receipt"]["sources"]
    return data, {row["url"]: row["sha256_16"] for row in sources}


def table_belongs_to_filing(table_url, report, pinned_filename=None):
    path = report["path"] + "/"
    if not isinstance(table_url, str) or not table_url.startswith(path):
        return False
    filename = table_url[len(path):]
    return filename == pinned_filename if pinned_filename else bool(re.fullmatch(r"R[1-9]\d*\.htm", filename))


def valid_table_source(part, report, pinned_filename=None):
    url = part.get("table_url")
    digest = part.get("table_sha256_16", "")
    source = part["source"]
    return (
        table_belongs_to_filing(url, report, pinned_filename) and bool(re.fullmatch(r"[0-9a-f]{16}", digest)) and
        (source == ENDPOINT or (source == url and part["sha256"][:16] == digest))
    )


def annual_table(cache, cik, report, statement, kind, title, pinned_filename=None, pinned_scale=None):
    if (statement["filing"], statement["end"], statement["period_kind"]) != (
            report["accession"], report["end"], "annual"):
        raise ValueError("Rendered table does not match the selected annual statement")
    request = request_bytes(f"{cik:010d}", "annual", report["accession"], kind)
    raw, receipt = cache.get(ENDPOINT, 8760, post_json=request)
    data, checksums = decode_response(raw, receipt, report, cik, "annual")
    table = data[kind]
    sources = table["sources"]
    url = sources[0] if len(sources) == 1 else None
    digest = checksums.get(url, "")
    scale = table["money_scale"]
    year = "12 months to " + statement["end"]
    if (" ".join(table["title"].casefold().split()) != " ".join(title.casefold().split()) or
            not table_belongs_to_filing(url, report, pinned_filename) or
            table["currency"] != statement["currency"] or table["columns"].count(year) != 1 or
            scale not in {1, 1_000, 1_000_000, 1_000_000_000} or
            (pinned_scale is not None and scale != pinned_scale)):
        raise ValueError(f"Unverified annual {kind.replace('_', ' ')} table")
    if re.fullmatch(r"[0-9a-f]{16}", digest):
        return table, table["columns"].index(year), receipt, {"table_url": url, "table_sha256_16": digest}
    if kind != "cash_flow":
        raise ValueError("Missing rendered statement source checksum")
    # Archived submissions can fill the connector's receipt before it records the statement.
    raw, receipt = cache.get(url, 8760)
    if receipt["url"] != url:
        raise ValueError("Unexpected source for SEC-rendered cash-flow document")
    table, column = read_cash_flow(raw, title, statement["currency"], statement["end"], scale)
    return table, column, receipt, {"table_url": url, "table_sha256_16": receipt["sha256"][:16]}


def amount(table, concept, column, label=None):
    matches = [row for row in table["rows"] if row[1] == concept and (label is None or row[0] == label)]
    if not matches or len({row[column] for row in matches}) != 1:
        raise ValueError(f"Missing or conflicting rendered fact for {concept}")
    row = matches[0]
    value = row[column]
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"Invalid rendered fact for {concept}")
    return value, row[0]


def scaled(value, scale):
    try:
        exact = Decimal(str(value)) * scale
        if not exact.is_finite() or exact != exact.to_integral_value():
            raise ValueError("Unexpected fractional or nonfinite base unit in filing")
        return int(exact)
    except InvalidOperation as exc:
        raise ValueError("Invalid numeric filing amount") from exc
