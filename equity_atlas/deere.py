"""Keep Deere's equipment and captive-finance disclosures in their filed scopes."""

from datetime import date
import re

from .capex import LEASE_EQUIPMENT, PPE
from .rendered_filing import ENDPOINT, filing_tables, scaled

CIK = 315189
PINNED = "0001104659-25-122321"
TAG = "disclosed:ReconciledBusinessScopes"
SCALE = 1_000_000
COLUMNS = ("EQUIPMENT OPERATIONS", "FINANCIAL SERVICES", "ELIMINATIONS", "CONSOLIDATED")
SEGMENTS = ("PPA", "SAT", "CF", "FS", "Total")
SEGMENT_NAMES = ("Production & Precision Agriculture", "Small Agriculture & Turf", "Construction & Forestry",
                 "Financial Services", "All reportable segments")
SEGMENT_QUERY = "Segment operating profit"
SEGMENT_LOCATOR = "Operating segments note · Segment operating profit"

# The public table search returns excerpts. One short query can recover
# multiple rows from the same table when it returns the needed captions.
TABLES = {
    "Net Income Attributable to Deere & Company": {
        "pretax": "Income before Income Taxes",
        "tax": "Provision for income taxes",
        "affiliate_income": "Equity in income (loss) of unconsolidated affiliates",
        "net_consolidated": "Net Income",
        "nci": "Less: Net loss attributable to noncontrolling interests",
        "net": "Net Income Attributable to Deere & Company",
    },
    "Depreciation and amortization": {"da": "Depreciation and amortization"},
    "Cost of equipment on operating leases acquired": {
        "cfo": "Net cash provided by operating activities",
        "ppe": "Purchases of property and equipment",
        "lease_purchases": "Cost of equipment on operating leases acquired",
        "lease_sales": "Proceeds from sales of equipment on operating leases",
    },
    "Decrease (increase) in investment in Financial Services": {
        "distributions": "Distributed earnings of Financial Services",
    },
    "Total liabilities and stockholders equity Equipment Operations Financial Services": {
        "assets": "Total Assets",
        "equity": "Adjusted total stockholders' equity",
    },
}
ROWS = {key: label for fields in TABLES.values() for key, label in fields.items()}

# Select scopes from the supplemental presentation, preserving its signed
# eliminations. CFO before distributions still includes other intercompany items.
FIELDS = {
    "pretax_equipment_operations": (("pretax", 0, 1),),
    "pretax_financial_services": (("pretax", 1, 1),),
    "net_equipment_operations": (("net", 0, 1),),
    "net_financial_services": (("net", 1, 1),),
    "cfo_equipment_operations": (("cfo", 0, 1),),
    "cfo_financial_services": (("cfo", 1, 1),),
    "distributions_from_financial_services": (("distributions", 0, 1),),
    "cfo_equipment_before_finance_distributions": (("cfo", 0, 1), ("distributions", 0, -1)),
    "da_equipment_operations": (("da", 0, 1),),
    "da_financial_services": (("da", 1, 1),),
    "capex_ppe_equipment_operations": (("ppe", 0, -1),),
    "capex_ppe_financial_services": (("ppe", 1, -1),),
    "operating_lease_equipment_purchases_financial_services": (("lease_purchases", 1, -1),),
    "operating_lease_equipment_sales_financial_services": (("lease_sales", 1, 1),),
    "assets_equipment_operations": (("assets", 0, 1),),
    "assets_financial_services": (("assets", 1, 1),),
    "equity_equipment_operations_adjusted": (("equity", 0, 1),),
    "equity_financial_services": (("equity", 1, 1),),
}


def supported(cik, report):
    return cik == CIK and report["form"] == "10-K"


def read_supplement(tables, report, year, fields):
    required = [f"{scope} {year}" for scope in COLUMNS]
    matches = []
    for table in tables:
        if (table["source"] != "document table" or table["url"] != report["url"] or
                any(table["columns"].count(column) != 1 for column in required)):
            continue
        indices = [table["columns"].index(column) for column in required]
        values = {}
        for key, label in fields.items():
            rows = [r for r in table["rows"] if r[0] == label]
            if len(rows) != 1:
                break
            raw = [rows[0][i] for i in indices]
            if all(value is None for value in raw) or any(value is not None and type(value) not in (int, float) for value in raw):
                break
            values[key] = [scaled(0 if value is None else value, SCALE) for value in raw]
        if values.keys() == fields.keys():
            matches.append(values)
    if len(matches) != 1:
        raise ValueError("Missing unique supplemental consolidating table")
    return matches[0]


def read_segments(tables, report, year):
    matches = []
    bridges = []
    end = date.fromisoformat(report["end"])
    caption = f"for the years ended {end.strftime('%B')} {end.day}, {year}"
    for table in tables:
        if table["source"] != "document table" or table["url"] != report["url"]:
            continue
        columns = table["columns"]
        rows = table["rows"]
        title = (table.get("title") or "").lower()
        if columns == ["line", "", *SEGMENTS] and caption.lower() in title:
            # The table starts with the current year's section. Its first
            # explicit year marker opens the comparative section.
            stop = next((i for i, r in enumerate(rows) if not r[0] and r[1] == year - 1), len(rows))
            profits, = [r[2:] for r in rows[:stop] if r[0] == SEGMENT_QUERY]
            if len(profits) == len(SEGMENTS) and all(type(v) in (int, float) for v in profits):
                matches.append([scaled(v, SCALE) for v in profits])
        elif columns == ["line", str(year), str(year - 1), str(year - 2)]:
            lines = ("Segment operating profit", "Interest income - excluding FS", "Interest expense - excluding FS",
                     "Pension and OPEB benefit, excluding service cost component", "Corporate other - net",
                     "Income taxes", "Net income")
            values = [[r[1] for r in rows if r[0] == line] for line in lines]
            if all(len(v) == 1 and type(v[0]) in (int, float) for v in values):
                bridges.append([scaled(v[0], SCALE) for v in values])
    if len(matches) != 1 or len(bridges) != 1:
        raise ValueError("Missing unique segment profit or consolidated net-income bridge")
    return matches[0], bridges[0]


def business_facts(cik, report, period, evidence):
    """Validate source scope and reconciliations before deriving display facts."""
    if (not supported(cik, report) or
            (period["period_kind"], period["filing"], period["end"], period["currency"]) !=
            ("annual", report["accession"], report["end"], "USD") or
            report["url"] != f"{report['path']}/{report['primary']}" or
            not report["path"].startswith(f"https://www.sec.gov/Archives/edgar/data/{CIK}/") or
            not re.fullmatch(r"[0-9a-f]{16}", evidence["table_sha256_16"])):
        raise ValueError("Business-scope evidence does not match the selected Deere 10-K")
    data = evidence["values"]
    digests = evidence["sha256"]
    lengths = {**dict.fromkeys(ROWS, 4), "segment": 5, "bridge": 7}
    if (data.keys() != lengths.keys() or digests.keys() != lengths.keys() or
            any(len(data[k]) != size or any(type(v) is not int or v % SCALE for v in data[k])
                or not re.fullmatch(r"[0-9a-f]{64}", digests[k]) for k, size in lengths.items())):
        raise ValueError("Incomplete or invalid Deere business-scope evidence")

    facts = period["facts"]
    for key in ("net", "tax", "da", "cfo", "assets", "total_equity", "net_consolidated"):
        fact = facts[key]
        start = None if key in {"assets", "total_equity"} else period["start"]
        if (fact["accession"], fact["unit"], fact["start"], fact["url"]) != (
                report["accession"], "USD", start, report["url"]):
            raise ValueError(f"Deere consolidated {key} is outside the selected scope")
    capex = {part["tag"]: part["value"] for part in facts["capex"]["components"]}
    anchors = {key: facts[key]["value"] for key in ("net", "net_consolidated", "tax", "da", "cfo", "assets")}
    anchors.update(equity=facts["total_equity"]["value"],
                   ppe=-capex[PPE], lease_purchases=-capex[LEASE_EQUIPMENT])
    if (any(sum(data[k][:3]) != data[k][3] for k in ROWS) or
            any(data[k][3] != value for k, value in anchors.items()) or
            any(data["pretax"][i] - data["tax"][i] + data["affiliate_income"][i] != data["net_consolidated"][i]
                or data["net_consolidated"][i] - data["nci"][i] != data["net"][i] for i in range(len(COLUMNS))) or
            data["distributions"][1] != 0 or data["distributions"][3] != 0 or
            data["segment"][4] != sum(data["segment"][:4]) or
            data["segment"][4] != data["bridge"][0] or
            sum(data["bridge"][:-1]) != data["bridge"][-1] or
            data["bridge"][-1] != facts["net_consolidated"]["value"] or data["bridge"][-2] != -data["tax"][3]):
        raise ValueError("Deere business scopes do not reconcile to the consolidated 10-K")

    def build(terms, locator, stock=False):
        parts = [{"value": data[key][index], "sign": sign, "line": label,
                  "sha256": digests[key], "table_url": report["url"]}
                 for key, index, sign, label in terms]
        return {
            "value": sum(part["sign"] * part["value"] for part in parts), "tag": TAG,
            "unit": "USD", "start": None if stock else period["start"], "accession": report["accession"],
            "form": report["form"], "filed": report["filed"], "url": report["url"], "source": ENDPOINT,
            "table_url": report["url"], "sha256": parts[0]["sha256"], "table_sha256_16": evidence["table_sha256_16"],
            "locator": locator, "components": parts,
        }

    scoped = {}
    for field, terms in FIELDS.items():
        scoped[field] = build([(k, i, sign, f"{COLUMNS[i].title()} · {ROWS[k]}") for k, i, sign in terms],
                              "Supplemental consolidating data", terms[0][0] in {"assets", "equity"})
    for field, indices in {
        "ebit_equipment_segments": (0, 1, 2),
        "ebit_financial_services_segment": (3,),
        "ebit_reported_segment_total": (4,),
    }.items():
        scoped[field] = build([("segment", i, 1, SEGMENT_NAMES[i]) for i in indices], SEGMENT_LOCATOR)
    return scoped


def enrich_business_scopes(cache, cik, report, period):
    evidence = {"values": {}, "sha256": {}}
    year = int(report["end"][:4])
    for query, fields in (*TABLES.items(), (SEGMENT_QUERY, None)):
        tables, checksums, receipt = filing_tables(cache, cik, report, query)
        digest = checksums.get(report["url"])
        if not digest or evidence.setdefault("table_sha256_16", digest) != digest:
            raise ValueError("Deere tables came from different filing documents")
        if fields:
            values = read_supplement(tables, report, year, fields)
        else:
            segment, bridge = read_segments(tables, report, year)
            values = {"segment": segment, "bridge": bridge}
        evidence["values"].update(values)
        evidence["sha256"].update(dict.fromkeys(values, receipt["sha256"]))
    facts = business_facts(cik, report, period, evidence)
    return {**period, "facts": {**period["facts"], **facts}, "annual_business_scopes": evidence}
