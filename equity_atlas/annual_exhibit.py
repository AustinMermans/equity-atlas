"""Reconcile annual disclosure details from matching SEC Item 2.02 exhibits."""

from datetime import date
import json
import re

from .depreciation import TAG as DEPRECIATION_TAG
from .facts import exact_sec_amount
from .fetch import SEC
from .rendered_filing import ENDPOINT, parse_result, scaled

ADP = 8670
AMGEN = 318154
AMGEN_REVIEWED_LEASES = "0000318154-26-000010"
SALESFORCE = 1108524
GE = 40545
TAG = "disclosed:AnnualEarningsExhibit"
OPERATING_TAG = "derived:OperatingProfitIncludingClientFunds"
OTHER_INCOME = "us-gaap:NonoperatingIncomeExpense"
CORPORATE_INCOME = "us-gaap:InvestmentIncomeInterest"
ADP_OPERATING_LINES = (
    ("pretax", 1, "Annual earnings before income taxes"),
    ("corporate_interest_expense_other", 1, "Interest expense outside the client-funds strategy"),
    ("nonoperating_income_net", -1, "Annual other income, net"),
    ("client_funds_interest_income_corporate", 1, "Corporate interest income assigned to the client-funds strategy"),
)

PROFILES = {
    ADP: (
        "All other interest expense", "Twelve Months Ended {month} {day}, {year}", {
            "client_funds_interest_income_corporate": "Corporate extended interest income (B)",
            "corporate_interest_income_other": "All other interest income",
            "corporate_interest_income_total": "Total interest income on corporate funds (component of Other (income)/expense, net)",
            "client_funds_interest_expense": "Short-term financing to support Client Funds Strategy (B)",
            "corporate_interest_expense_other": "All other interest expense",
            "interest_expense_total_exhibit": "Total interest expense",
        },
    ),
    AMGEN: (
        "GAAP Net Income Depreciation and amortization Interest expense Provision EBITDA", "Twelve months ended {month} {day}, {year}", {
            "gaap_net": "GAAP Net Income",
            "interest_net": "Interest expense, net",
            "income_tax": "Provision for income taxes",
            "da_including_operating_rou": "Depreciation and amortization",
            "ebitda_exhibit": "EBITDA (a)",
        },
    ),
    GE: (
        "Total revenue Insurance revenue Adjusted revenue Adjusted costs Adjusted other income Operating profit GAAP",
        "Twelve months ended {month} {day} {year}", {
            "gaap_sales": "Total revenue (GAAP)",
            "gaap_costs": "Total costs and expenses (GAAP)",
            "gaap_other_income": "Other income (loss) (GAAP)",
            "gaap_pretax": "Profit (loss) (GAAP)",
            "insurance_revenue": "Less: Insurance revenue",
            "sales_adjusted": "Adjusted revenue (Non-GAAP)",
            "costs_adjusted": "Adjusted costs (Non-GAAP)",
            "other_income_adjusted": "Adjusted other income (loss) (Non-GAAP)",
            "ebit_adjusted": "Operating profit (loss) (Non-GAAP)",
        },
    ),
    SALESFORCE: (
        "GAAP income from operations amortization of purchased intangibles", "Fiscal Year Ended {month} {day}, {year}", {
            "gaap_ebit": "GAAP income from operations",
            "gaap_net": "GAAP net income",
            "amortization_purchased_intangibles": "Amortization of purchased intangibles (1)",
        },
    ),
}

PINNED = {
    (ADP, "0000008670-26-000030"): "0000008670-26-000025",
    (AMGEN, AMGEN_REVIEWED_LEASES): "0000318154-26-000003",
    (SALESFORCE, "0001108524-26-000060"): "0001108524-26-000056",
    (GE, "0000040545-26-000008"): "0000040545-26-000005",
}


def supported(cik, report):
    return cik in PROFILES and report["form"] == "10-K"


def exhibit_url(url, cik, filing):
    path = f"https://www.sec.gov/Archives/edgar/data/{cik}/{filing['accession'].replace('-', '')}/"
    return (
        bool(re.fullmatch(r"\d{10}-\d{2}-\d{6}", filing["accession"])) and isinstance(url, str) and url.startswith(path) and
        bool(re.fullmatch(r"[\w.-]+\.html?", url[len(path):], re.ASCII)) and
        url != filing["url"] and not url.endswith("-index.htm")
    )


def load_exhibit(cache, cik, report, filing):
    query, date_format, labels = PROFILES[cik]
    args = {"company": f"{cik:010d}", "accession": filing["accession"], "form": "8-K",
            "find": query, "max_tables": 8}
    request = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "run_tool", "arguments": {"name": "filing_tables", "arguments": args}},
    }, sort_keys=True).encode()
    raw, receipt = cache.get(ENDPOINT, 8760, post_json=request)
    result = parse_result(raw)
    payload = result["structuredContent"]
    entry, = payload["results"]
    if (receipt["url"] != ENDPOINT or payload["company"]["cik"] != cik or
            tuple(entry["filing"][key] for key in ("accession", "form", "filed", "period")) !=
            tuple(filing[key] for key in ("accession", "form", "filed", "end"))):
        raise ValueError("Exhibit response does not match the SEC registrant and accession")
    receipts = {line["url"]: line["sha256_16"]
                for line in result["_meta"]["canlicapital.com/receipt"]["sources"]}
    end = date.fromisoformat(report["end"])
    column = date_format.format(month=end.strftime("%B"), day=end.day, year=end.year)
    matches = []
    for table in entry["tables"]:
        url = table.get("url", "")
        if (table["source"] != "document table" or not exhibit_url(url, cik, filing) or
                table["columns"].count(column) != 1):
            continue
        index = table["columns"].index(column)
        values = {}
        for key, label in labels.items():
            numbers = {row[index] for row in table["rows"] if row[0] == label}
            if len(numbers) != 1 or type(value := next(iter(numbers))) not in (int, float):
                break
            values[key] = scaled(value, 1_000_000)
        if values.keys() == labels.keys() and re.fullmatch(r"[0-9a-f]{16}", receipts.get(url, "")):
            matches.append({"filing": filing, "url": url, "sha256": receipt["sha256"],
                            "table_sha256_16": receipts[url], "values": values})
    if len(matches) != 1:
        raise ValueError("Missing unique full-year exhibit reconciliation")
    return matches[0]


def adp_operating_fact(facts):
    parts = [
        {**facts[key], "line": label, "sign": sign, "table_url": facts[key]["url"]}
        for key, sign, label in ADP_OPERATING_LINES
    ]
    value = sum(part["sign"] * part["value"] for part in parts)
    return {**facts["pretax"], "value": value, "tag": OPERATING_TAG, "components": parts,
            "locator": "Operating profit including the client-funds strategy"}


def exhibit_facts(cik, report, period, evidence):
    """Return facts only when the same fiscal year and annual GAAP anchors reconcile."""
    filing = evidence["filing"]
    url = evidence["url"]
    values = evidence["values"]
    labels = PROFILES[cik][2]
    if (not supported(cik, report) or (period["period_kind"], period["filing"], period["end"], period["currency"]) !=
            ("annual", report["accession"], report["end"], "USD") or filing["form"] != "8-K" or "2.02" not in filing["items"].split(",") or
            not report["end"] < filing["end"] <= filing["filed"] <= report["filed"] or
            not exhibit_url(url, cik, filing) or
            not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"]) or
            not re.fullmatch(r"[0-9a-f]{16}", evidence["table_sha256_16"]) or values.keys() != labels.keys() or
            any(type(value) is not int for value in values.values())):
        raise ValueError("Exhibit provenance does not match the selected annual period")
    pinned = PINNED.get((cik, report["accession"]))
    if pinned and filing["accession"] != pinned:
        raise ValueError("Reviewed earnings exhibit accession changed")

    facts = period["facts"]
    anchor_keys = {
        ADP: ("pretax", "interest", "corporate_interest_income_filed", "nonoperating_income_net"),
        AMGEN: ("net", "interest", "tax", "da_with_other", "da_ppe", "da_ppe_and_rou", "amortization"),
        SALESFORCE: ("ebit", "net", "da_ppe", "da_with_rou_and_impairment"),
        GE: ("sales", "pretax"),
    }[cik]
    if any((facts[key]["accession"], facts[key]["start"], facts[key]["unit"], facts[key]["url"]) !=
           (report["accession"], period["start"], "USD", report["url"]) for key in anchor_keys):
        raise ValueError("Exhibit anchors must match the selected consolidated annual filing")
    fields = labels.keys()
    if cik == ADP:
        if (facts["corporate_interest_income_filed"]["tag"] != CORPORATE_INCOME or
                facts["nonoperating_income_net"]["tag"] != OTHER_INCOME or
                facts["interest"]["value"] != values["interest_expense_total_exhibit"] or
                facts["corporate_interest_income_filed"]["value"] != values["corporate_interest_income_total"] or
                values["client_funds_interest_expense"] + values["corporate_interest_expense_other"] !=
                values["interest_expense_total_exhibit"] or
                values["client_funds_interest_income_corporate"] + values["corporate_interest_income_other"] !=
                values["corporate_interest_income_total"] or any(value < 0 for value in values.values())):
            raise ValueError("Client-funds interest split does not reconcile to filed interest")
        fields = fields - {"corporate_interest_income_total", "interest_expense_total_exhibit"}
    elif cik == AMGEN:
        anchors = dict(zip(("gaap_net", "interest_net", "income_tax", "da_including_operating_rou"), anchor_keys[:4], strict=True))
        if (any(values[field] != facts[key]["value"] for field, key in anchors.items()) or
                sum(values[field] for field in anchors) != values["ebitda_exhibit"] or
                not 0 <= facts["da_ppe"]["value"] <= facts["da_ppe_and_rou"]["value"] <= values["da_including_operating_rou"]):
            raise ValueError("Amgen EBITDA exhibit does not reconcile to the 10-K")
        fields = ("da_including_operating_rou",)
    elif cik == GE:
        gaap_profit = values["gaap_sales"] - values["gaap_costs"] + values["gaap_other_income"]
        adjusted_sales = values["gaap_sales"] - values["insurance_revenue"]
        adjusted_profit = values["sales_adjusted"] - values["costs_adjusted"] + values["other_income_adjusted"]
        # GE prints the reconciliation in millions and calculates the totals before rounding.
        if ((facts["sales"]["value"], facts["pretax"]["value"]) != (values["gaap_sales"], values["gaap_pretax"]) or
                abs(gaap_profit - values["gaap_pretax"]) > 1_000_000 or
                abs(adjusted_sales - values["sales_adjusted"]) > 1_000_000 or
                abs(adjusted_profit - values["ebit_adjusted"]) > 1_000_000 or
                not 0 <= values["insurance_revenue"] <= values["gaap_sales"]):
            raise ValueError("GE adjusted operating profit does not reconcile to the full-year exhibit")
        fields = labels.keys() - {"gaap_sales", "gaap_costs", "gaap_other_income", "gaap_pretax"}
    else:
        if ((facts["ebit"]["value"], facts["net"]["value"]) != (values["gaap_ebit"], values["gaap_net"]) or
                facts["da_ppe"]["tag"] != DEPRECIATION_TAG or
                min(values["amortization_purchased_intangibles"], facts["da_ppe"]["value"]) < 0 or
                values["amortization_purchased_intangibles"] + facts["da_ppe"]["value"] > facts["da_with_rou_and_impairment"]["value"]):
            raise ValueError("Purchased-intangible amortization exhibit disagrees with the annual filing")
        fields = ("amortization_purchased_intangibles",)

    result = {
        key: {
            "value": values[key], "tag": TAG, "locator": labels[key], "source": ENDPOINT,
            "url": url, "sha256": evidence["sha256"], "table_sha256_16": evidence["table_sha256_16"],
            "form": "8-K", "filed": filing["filed"], "accession": filing["accession"],
            "start": period["start"], "unit": "USD",
        } for key in sorted(fields)
    }
    if cik == ADP:
        result["ebit"] = adp_operating_fact({**facts, **result})
    if cik == AMGEN and report["accession"] == AMGEN_REVIEWED_LEASES:
        # Note 14 confirms that the lease assets in the depreciation note are all operating leases.
        total = result["da_including_operating_rou"]
        ppe = facts["da_ppe"]
        ppe_and_rou = facts["da_ppe_and_rou"]
        intangible = total["value"] - ppe_and_rou["value"]
        if abs(intangible - facts["amortization"]["value"]) > 50_000_000:
            raise ValueError("Implied intangible amortization differs from the rounded 10-K disclosure")
        parts = [{**fact, "sign": sign, "line": fact["locator"], "table_url": fact["url"]}
                 for fact, sign in ((total, 1), (ppe_and_rou, -1), (ppe, 1))]
        result["da"] = {**total, "value": intangible + ppe["value"], "components": parts,
                        "locator": "Filed D&A excluding operating lease asset amortization"}
    if cik == SALESFORCE:
        amortization = result["amortization_purchased_intangibles"]
        ppe = facts["da_ppe"]
        parts = [{**fact, "sign": 1, "line": fact["locator"], "table_url": fact["url"]}
                 for fact in (ppe, amortization)]
        result["da"] = {**amortization, "value": ppe["value"] + amortization["value"], "components": parts,
                        "rounding_increment": 100_000_000,
                        "locator": "Fixed-asset D&A and acquired-intangible amortization (includes a rounded input)"}
    if cik == GE:
        result["ebit_adjusted"]["components"] = [
            {**result[key], "sign": sign, "line": labels[key], "table_url": url}
            for key, sign in (("sales_adjusted", 1), ("costs_adjusted", -1), ("other_income_adjusted", 1))
        ]
    return result


def enrich_exhibit(cache, cik, report, period, submissions, obj, meta):
    facts = period["facts"].copy()
    if cik == ADP:
        anchor = facts["pretax"]
        if anchor["accession"] != report["accession"] or meta["url"] != SEC.format(cik):
            raise ValueError("Missing exact annual filing anchor for ADP")
        for key, tag in (("nonoperating_income_net", OTHER_INCOME), ("corporate_interest_income_filed", CORPORATE_INCOME)):
            value = exact_sec_amount(obj, period, report, tag)
            if value is None:
                raise ValueError(f"Missing exact filed ADP {key}")
            facts[key] = {**anchor, "value": value, "tag": tag}
    period = {**period, "facts": facts}

    recent = submissions["filings"]["recent"]
    candidates = []
    for accession, form, filed, end, items, primary in zip(*(recent[key] for key in (
            "accessionNumber", "form", "filingDate", "reportDate", "items", "primaryDocument")), strict=True):
        if (form == "8-K" and "2.02" in items.split(",") and report["end"] < end <= filed <= report["filed"] and
                re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) and re.fullmatch(r"[\w.-]+\.html?", primary, re.ASCII)):
            path = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
            candidates.append({"accession": accession, "form": form, "filed": filed, "end": end, "items": items, "url": f"{path}/{primary}"})

    for filing in sorted(candidates, key=lambda item: (item["filed"], item["accession"]), reverse=True)[:3]:
        try:
            evidence = load_exhibit(cache, cik, report, filing)
            disclosed = exhibit_facts(cik, report, period, evidence)
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            last_error = exc
        else:
            return {**period, "facts": {**facts, **disclosed}, "annual_earnings_exhibit": evidence}
    raise ValueError("Could not reconcile a fiscal-year Item 2.02 exhibit") from (last_error if candidates else None)
