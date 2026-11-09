"""Find annual cash-investment lines that warrant checking against a tagged capex value."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from equity_atlas.capex import CAPEX_TAG, cash_activity
from equity_atlas.fetch import Cache
from equity_atlas.issuer_20f import BHP_CAPEX_TAG
from equity_atlas.models import CORE
from equity_atlas.rendered_filing import ENDPOINT, decode_response, request_bytes, scaled, table_belongs_to_filing
from equity_atlas.sec_workbook import CAPEX_TAG as WORKBOOK_CAPEX_TAG

ASSET_TERMS = re.compile(
    r"capital (?:and technology )?(?:expenditure|investment|spend)|property additions|"
    r"(?:purchase|expenditure|investment|acqui[rs]|addition|payment|principal).{0,80}"
    r"(?:productive assets?|property|plant|equipment|intangible|software|nuclear fuel|exploration|evaluation)",
    re.I,
)
FINANCIAL_TERMS = re.compile(r"marketable securities|equity securities|nuclear decommissioning trust", re.I)


def audit_row(cache, row, period, fact):
    report = period["report"]
    cik = int(report["path"].split("/")[6])
    item = {"symbol": row["symbol"], "end": period["end"], "filing": report["url"], "tag": fact["tag"], "value": fact["value"]}
    try:
        if (fact["accession"], period["filing"], period["end"]) != (report["accession"], report["accession"], report["end"]):
            raise ValueError("Fact and report differ")
        raw, receipt = cache.get(ENDPOINT, 8760, post_json=request_bytes(
            f"{cik:010d}", "annual", report["accession"], "cash_flow",
        ))
        data, digests = decode_response(raw, receipt, report, cik, "annual")
        table = data["cash_flow"]
        url, = table["sources"]
        scale = table["money_scale"]
        year = "12 months to " + period["end"]
        if (not table_belongs_to_filing(url, report) or not re.fullmatch(r"[0-9a-f]{16}", digests.get(url, "")) or
                table["currency"] != period["currency"] or scale not in {1, 1_000, 1_000_000, 1_000_000_000} or
                table["columns"].count(year) != 1):
            raise ValueError("Cash-flow table receipt, currency, scale or fiscal column did not match")
        column = table["columns"].index(year)
        cfo = period["facts"]["cfo"]
        values = {scaled(row[column], scale) for row in table["rows"]
                  if row[1] == cfo["tag"] and type(row[column]) in (int, float)}
        if values != {cfo["value"]}:
            raise ValueError("Filed consolidated operating cash flow did not match")
        sections = cash_activity(table, column, cfo["tag"], financing=True)
        candidates = []
        for activity, section in zip(("investing", "financing"), sections, strict=True):
            for row in section["rows"]:
                label, tag, value = row[0], row[1], row[column]
                if tag and type(value) in (int, float) and value < 0 and ASSET_TERMS.search(label) and not FINANCIAL_TERMS.search(label):
                    candidates.append({"activity": activity, "label": label, "tag": tag, "outflow": -scaled(value, scale)})
        matched = len(candidates) == 1 and (candidates[0]["tag"], candidates[0]["outflow"]) == (fact["tag"], fact["value"])
        return {**item, "status": "matched face line" if matched else "review scope",
                "table": url, "table_sha256_16": digests[url], "candidates": candidates}
    except FileNotFoundError:
        return {**item, "status": "uncached"}
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return {**item, "status": "unverified table", "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--fetch", action="store_true", help="Retrieve missing filings from the public connector")
    args = parser.parse_args()
    cache = Cache(args.cache, offline=not args.fetch)
    snapshot = json.loads(args.snapshot.read_bytes())
    counts = Counter()
    for row in snapshot["rows"]:
        period = row["statement"]
        fact = (period or {}).get("facts", {}).get("capex")
        if not fact or fact["tag"] in {CAPEX_TAG, WORKBOOK_CAPEX_TAG, BHP_CAPEX_TAG} or not row["id"].startswith("sec:") or row["kind"] not in CORE:
            continue
        result = audit_row(cache, row, period, fact)
        print(json.dumps(result), flush=True)
        counts[result["status"]] += 1
    print(json.dumps(counts, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    main()
