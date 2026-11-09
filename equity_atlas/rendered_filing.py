"""Retrieve SEC-rendered statements through the public Canli connector."""

from decimal import Decimal, InvalidOperation
import json
import math

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
