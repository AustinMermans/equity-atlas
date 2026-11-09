"""Compare unreviewed annual D&A inputs with the cash-flow rows of the exact filing."""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from equity_atlas.fetch import Cache
from equity_atlas.models import CORE
from equity_atlas.rendered_filing import ENDPOINT, decode_response, request_bytes, scaled, table_belongs_to_filing

EXPENSE_WORDS = re.compile(r"depreciat|deplet|amorti[sz]|accretion", re.I)
EXPENSE = r"(?:depreciation|depletion|amorti[sz]ation)"
UNQUALIFIED = re.compile(rf"^{EXPENSE}(?:, {EXPENSE})?(?:,? and | & ){EXPENSE}(?: expenses?)?$", re.I)


def audit_rows(cache, period, report, cik):
    raw, receipt = cache.get(ENDPOINT, 8760, post_json=request_bytes(
        f"{cik:010d}", "annual", report["accession"], "cash_flow",
    ))
    data, checksums = decode_response(raw, receipt, report, cik, "annual")
    table = data["cash_flow"]
    url, = table["sources"]
    scale = table["money_scale"]
    year = "12 months to " + period["end"]
    if (not table_belongs_to_filing(url, report) or not re.fullmatch(r"[0-9a-f]{16}", checksums.get(url, "")) or
            table["currency"] != period["currency"] or scale not in {1, 1_000, 1_000_000, 1_000_000_000} or
            table["columns"].count(year) != 1):
        raise ValueError("Cash-flow table receipt, currency, scale or fiscal column did not match")
    index = table["columns"].index(year)
    rows = table["rows"]
    cfo = period["facts"]["cfo"]
    totals = [i for i, row in enumerate(rows)
              if row[1] == cfo["tag"] and type(row[index]) in (int, float) and scaled(row[index], scale) == cfo["value"]]
    start = 0
    if len(totals) == 2:
        # A direct cash-flow statement can repeat CFO after its supplemental indirect reconciliation.
        supplements = [i for i in range(totals[0] + 1, totals[1])
                       if rows[i][1] == "us-gaap:SupplementalCashFlowInformationAbstract"]
        if len(supplements) == 1:
            start = supplements[0] + 1
            totals = totals[1:]
    if len(totals) != 1:
        raise ValueError("Filed consolidated operating cash flow did not match uniquely")
    amounts = [(label, tag, scaled(row[index], scale)) for row in rows[start:totals[0]]
               for label, tag in [row[:2]] if tag and type(row[index]) in (int, float) and EXPENSE_WORDS.search(label)]
    return url, checksums[url], amounts


def audit(snapshot, cache):
    for row in snapshot["rows"]:
        period = row["statement"]
        if not period or row["kind"] not in CORE or not row["id"].startswith("sec:"):
            continue
        fact = period["facts"].get("da")
        if not fact or not fact["source"].startswith("https://data.sec.gov/") or fact["tag"].startswith("derived:"):
            continue
        report = period["report"]
        cik = int(report["path"].split("/")[6])
        item = {"symbol": row["symbol"], "end": period["end"], "filing": report["url"],
                "tag": fact["tag"], "value": fact["value"]}
        try:
            if (fact["accession"], period["filing"], period["end"]) != (report["accession"], report["accession"], report["end"]):
                raise ValueError("Fact and report differ")
            url, digest, amounts = audit_rows(cache, period, report, cik)
            exact = [label for label, tag, value in amounts if (tag, value) == (fact["tag"], fact["value"])]
            result = "review scope"
            if len(exact) == 1 and UNQUALIFIED.fullmatch(exact[0]):
                result = "matched face line" if len(amounts) == 1 else "matched face line with other expense disclosures"
            yield {**item, "status": result, "table": url, "table_sha256_16": digest, "candidates": amounts}
        except FileNotFoundError:
            yield {**item, "status": "uncached"}
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            yield {**item, "status": "unverified table", "error": str(exc)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--cache", type=Path, default=Path("data/cache"))
    parser.add_argument("--fetch", action="store_true", help="Retrieve missing filings from the public connector")
    args = parser.parse_args()
    cache = Cache(args.cache, offline=not args.fetch)
    counts = Counter()
    for result in audit(json.loads(args.snapshot.read_bytes()), cache):
        print(json.dumps(result), flush=True)
        counts[result["status"]] += 1
    print(json.dumps(counts, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    main()
