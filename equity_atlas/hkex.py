"""Discover and reconcile audited HKEX reports for former SEC registrants."""

from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
import math
import re
from urllib.parse import urljoin

from .facts import EPS_FIELDS, STOCK
from .issuer_20f import column, pdf_pages

@dataclass(frozen=True)
class Listing:
    cik: int
    stock_code: str
    stock_id: int
    symbol: str
    name: str
    suspended: str
    form_15f: str
    sales_basis: str

    @property
    def row_id(self):
        return f"hkex:{self.stock_code}"

    def provenance(self):
        return {"former_cik": self.cik, "sec_reporting_suspended": self.suspended, "sec_exit_url": self.form_15f}


CHINA_MOBILE = Listing(
    1117795, "00941", 2247, "0941.HK", "China Mobile Limited", "2022-09-14",
    "https://www.sec.gov/Archives/edgar/data/1117795/000119312522244231/d403146d15f15d.htm",
    "china_mobile_hkex_operating_revenue",
)
PETROCHINA = Listing(
    1108329, "00857", 2038, "0857.HK", "PetroChina Company Limited", "2024-02-05",
    "https://www.sec.gov/Archives/edgar/data/1108329/000094787124000089/ss2990214_15f12b.htm",
    "petrochina_hkex_ifrs_revenue",
)
LISTINGS = {listing.cik: listing for listing in (CHINA_MOBILE, PETROCHINA)}
HOST = "https://www1.hkexnews.hk"
SOURCE = "HKEX annual report"
ROUTE = "hkex_annual"
FORM = "HKEX Annual Report"
DOCUMENT = re.compile(r"/listedco/listconews/sehk/(\d{4})/(\d{4})/(\d{13})\.pdf")
MILLION = 1_000_000
STOCK_FIELDS = STOCK | {"lease_liabilities_separate", "cash_beginning", "debt_beginning", "asset_retirement_obligations"}
INVESTMENT_LABEL = "Payment for property, plant and equipment, other intangible assets and non-current assets"
BORROWING_LABEL = "Bank and other borrowings"
PROCEEDS_LABEL = "Proceeds received from bank and other borrowings"
REPAYMENTS_LABEL = "Repayment of bank and other borrowings"
MOBILE_FIELDS = {
    "sales": "Consolidated income · Revenue from principal and other businesses",
    "ebit": "Consolidated income · Profit from operations",
    "pretax": "Consolidated income · Profit before taxation",
    "tax": "Consolidated income · Taxation",
    "net_consolidated": "Consolidated income · Profit for the year",
    "net_nci": "Consolidated income · Profit attributable to non-controlling interests",
    "net_parent": "Consolidated income · Profit attributable to equity shareholders",
    "net": "Consolidated income · Profit attributable to equity shareholders",
    "eps_basic": "Consolidated income · Basic earnings per share",
    "eps_diluted": "Consolidated income · Diluted earnings per share",
    "da": "Consolidated cash flows · Depreciation and amortisation",
    "assets": "Consolidated balance sheet · Total assets",
    "liabilities": "Consolidated balance sheet · Total liabilities",
    "total_equity": "Consolidated balance sheet · Total equity",
    "book": "Consolidated balance sheet · Equity attributable to equity shareholders",
    "minority": "Consolidated balance sheet · Non-controlling interests",
    "cash": "Consolidated balance sheet · Cash and cash equivalents",
    "lease_liabilities_separate": "Consolidated balance sheet · Current and non-current lease liabilities",
    "debt_total": "Consolidated balance sheet and debt note · Bank and other borrowings",
    "cfo": "Consolidated cash flows · Net cash generated from operating activities",
    "cash_investing": "Consolidated cash flows · Net cash used in investing activities",
    "cash_financing": "Consolidated cash flows · Net cash used in financing activities",
    "cash_beginning": "Consolidated cash flows · Cash and cash equivalents at beginning of year",
    "cash_fx_effect": "Consolidated cash flows · Effect of changes in foreign exchange rate",
    "capex_mixed_outflow": f"Consolidated cash flows · {INVESTMENT_LABEL}",
    "div": "Consolidated cash flows · Dividends paid to equity shareholders",
    "div_nci": "Consolidated cash flows · Dividends paid to non-controlling shareholders",
    "bank_borrowings_proceeds": f"Consolidated cash flows · {PROCEEDS_LABEL}",
    "bank_borrowings_repayments": f"Consolidated cash flows · {REPAYMENTS_LABEL}",
    "debt_net": "Consolidated cash flows · Bank borrowing proceeds less repayments",
}
DEBT_MOVEMENT_FIELDS = {
    "debt_beginning": "Financing liabilities note · Opening bank debt",
    "debt_acquired": "Financing liabilities note · Bank debt added through business combinations",
    "debt_other_noncash": "Financing liabilities note · Other noncash bank debt movements",
}


PETRO_INCOME = {
    "sales": "REVENUE",
    "ebit": "PROFIT FROM OPERATIONS",
    "pretax": "PROFIT BEFORE INCOME TAX EXPENSE",
    "tax": "INCOME TAX EXPENSE",
    "net_consolidated": "PROFIT FOR THE YEAR",
}
PETRO_POSITION = {
    "cash": "Cash and cash equivalents",
    "book": "TOTAL EQUITY ATTRIBUTABLE TO OWNERS OF THE COMPANY",
    "minority": "NON-CONTROLLING INTERESTS",
    "total_equity": "TOTAL EQUITY",
    "debt_current_total": "Short-term borrowings",
    "debt_noncurrent": "Long-term borrowings",
    "asset_retirement_obligations": "Asset retirement obligations",
}
PETRO_OPERATIONS = {
    "cfo": "NET CASH FLOWS FROM OPERATING ACTIVITIES",
    "da_with_impairment": "Depreciation, depletion and amortisation",
}
PETRO_CASH_FLOWS = {
    "capex": "Capital expenditures",
    "capex_mixed_outflow": "Acquisition of intangible assets and other non-current assets",
    "cash_investing": "NET CASH FLOWS USED FOR INVESTING ACTIVITIES",
    "cash_financing": "NET CASH FLOWS USED FOR FINANCING ACTIVITIES",
    "cash_fx_effect": "TRANSLATION OF FOREIGN CURRENCY",
    "cash_beginning": "Cash and cash equivalents at the beginning of the year",
    "div": "Dividends paid to owners of the Company",
    "div_nci": "Dividends paid to non-controlling interests",
    "st_issued": "Increase in short-term borrowings",
    "lt_issued": "Increase in long-term borrowings",
    "st_repaid": "Repayments of short-term borrowings",
    "lt_repaid": "Repayments of long-term borrowings",
}
PETRO_FIELDS = {
    **{key: f"IFRS consolidated income · {label}" for key, label in PETRO_INCOME.items()},
    **{key: f"IFRS consolidated financial position · {label}" for key, label in PETRO_POSITION.items()},
    **{key: f"IFRS consolidated cash flows · {label}" for key, label in (PETRO_OPERATIONS | PETRO_CASH_FLOWS).items()},
    "net": "IFRS consolidated income · Profit attributable to owners",
    "net_parent": "IFRS consolidated income · Profit attributable to owners",
    "net_nci": "IFRS consolidated income · Profit attributable to non-controlling interests",
    "eps_basic": "IFRS consolidated income · Basic and diluted earnings per share",
    "eps_diluted": "IFRS consolidated income · Basic and diluted earnings per share",
    "assets": "IFRS consolidated financial position · Current and non-current assets",
    "liabilities": "IFRS consolidated financial position · Current and non-current liabilities",
    "lease_liabilities_separate": "IFRS consolidated financial position · Current and non-current lease liabilities",
    "debt_current": "IFRS borrowing note · Current portion of long-term borrowings",
    "short_borrow": "IFRS borrowing note · Short-term borrowings excluding current maturities of long-term debt",
    "debt_total": "IFRS consolidated financial position and borrowing note · Total borrowings",
    "bank_borrowings_proceeds": "IFRS consolidated cash flows · Short- and long-term borrowing proceeds",
    "bank_borrowings_repayments": "IFRS consolidated cash flows · Short- and long-term borrowing repayments",
    "debt_net": "IFRS consolidated cash flows · Borrowing proceeds less repayments",
    "segment_capital_expenditures": "IFRS operating segments note · Capital expenditures",
    "impairment_ppe": "IFRS operating segments note · Impairment losses of property, plant and equipment",
    "da": "IFRS consolidated cash flows · Depreciation, depletion and amortisation less disclosed PP&E impairment",
}


def listing_for(cik, day):
    listing = LISTINGS.get(cik)
    if listing and day >= date.fromisoformat(listing.suspended):
        return listing
    return None


def index_url(listing, asof):
    start = date.fromisoformat(listing.suspended)
    return (f"{HOST}/search/titlesearch.xhtml?category=0&lang=EN&market=SEHK&stockId={listing.stock_id}"
            f"&t1code=40000&t2Gcode=-1&t2code=40100&from={start:%Y%m%d}&to={asof:%Y%m%d}")


def document_day(url):
    if not isinstance(url, str) or not url.startswith(HOST + "/"):
        return None
    match = DOCUMENT.fullmatch(url.removeprefix(HOST))
    if match and match[3].startswith(match[1] + match[2]):
        return datetime.strptime(match[1] + match[2], "%Y%m%d").date()
    return None


class AnnualIndex(HTMLParser):
    def __init__(self, listing, asof):
        super().__init__()
        self.asof = asof
        self.stock_code = listing.stock_code
        self.filings = set()
        self.row = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = ([], [])
        if tag == "a" and self.row is not None:
            path = dict(attrs).get("href", "")
            if DOCUMENT.fullmatch(path):
                self.row[1].append(urljoin(HOST, path))

    def handle_data(self, data):
        if self.row is not None:
            self.row[0].append(data)

    def handle_endtag(self, tag):
        if tag != "tr" or self.row is None:
            return
        chunks, links = self.row
        self.row = None
        text = " ".join(" ".join(chunks).split())
        title = re.search(r"\[Annual Report\]\s+(?:Annual Report (\d{4})|(\d{4}) Annual Report)\b", text, re.I)
        if not title or not re.search(rf"Stock Code:\s+{self.stock_code}\b", text):
            return
        release = re.search(r"Release Time:\s+(\d{2}/\d{2}/\d{4})", text)
        if release is None or len(links) != 1:
            raise ValueError("Missing unique HKEX annual report URL or release date")
        url, = links
        filed = datetime.strptime(release[1], "%d/%m/%Y").date()
        year = int(title[1] or title[2])
        if document_day(url) != filed or filed <= date(year, 12, 31):
            raise ValueError("Inconsistent HKEX annual report date")
        if filed <= self.asof:
            self.filings.add((year, filed, url))


def annual_document(raw, listing, asof):
    index = AnnualIndex(listing, asof)
    index.feed(raw.decode("utf-8"))
    index.close()
    if not index.filings:
        raise ValueError("No dated annual report in HKEX's issuer results")
    latest = max((year, filed) for year, filed, _ in index.filings)
    report, = (entry for entry in index.filings if entry[:2] == latest)
    return report


def statement_page(pages, year, heading, marker):
    matches = [p for p in pages if heading in map(str.casefold, map(str.strip, p.splitlines()))
               and (f"31 December {year} (Expressed in RMB)" in p
                    or f"31 December {year} (Expressed in Renminbi (“RMB”))" in p)
               and re.search(rf"(?m)^ *{year} +{year - 1} *\n +(?:Note +)?Million +Million", p)
               and marker in p]
    page, = matches
    return re.sub(r"(?m)(?<=  )\d+\([a-z]+\)(?= {2,})|(?<=\s)RMB(?=\d)", "", page)


def note_table(pages, heading, year, following=None):
    matches = [p for p in pages if re.search(rf"(?m)^ *\d+ +{heading} *$", p) and "Expressed in RMB" in p]
    page, = matches
    if following:
        page = re.split(rf"(?m)^ *\d+ +{following} *$", page, maxsplit=1)[0]
    if not re.search(rf"(?m)^ *{year} +{year - 1} *\n +(?:Note +)?Million +Million", page):
        raise ValueError("Unexpected HKEX notes period columns")
    return re.sub(r"(?m)(?<=  )\([a-z]+\)(?= {2,})", "", page)


def borrowing_rollforward(pages, year):
    page, = (p for p in pages if re.search(r"(?m)^ *\d+ +CASH AND CASH EQUIVALENTS AND OTHER CASH FLOW INFORMATION *$", p)
             and "Reconciliation of liabilities arising from financing activities" in p)
    section = page.split("Reconciliation of liabilities arising from financing activities", 1)[1]
    if not re.search(r"Bank and +.*deposits in\n +other +Lease +China Mobile\n +borrowings +liabilities +Finance Group",
                     section):
        raise ValueError("Missing distinct HKEX bank borrowing column")
    acquisition_line = "Business combination other than common control"
    acquired = column(section, acquisition_line, 5) if acquisition_line in section else 0
    total_noncash = column(section, "Total other changes", 5)
    return {
        "opening": column(section, f"As at 1 January {year}", 5),
        "proceeds": column(section, PROCEEDS_LABEL, 5),
        "repayments": -column(section, REPAYMENTS_LABEL, 5),
        "acquired": acquired,
        "other_noncash": total_noncash - acquired,
        "closing": column(section, f"As at 31 December {year}", 5),
    }


def reconciles(facts):
    v = {key: fact["value"] for key, fact in facts.items()}
    if "debt_current_total" in v and (
            v["short_borrow"] + v["debt_current"] != v["debt_current_total"]
            or v["debt_current_total"] + v["debt_noncurrent"] != v["debt_total"]
            or v["st_issued"] + v["lt_issued"] != v["bank_borrowings_proceeds"]
            or v["st_repaid"] + v["lt_repaid"] != v["bank_borrowings_repayments"]
            or v["da"] + v["impairment_ppe"] != v["da_with_impairment"]
            or any(v[key] < 0 for key in ("capex", "asset_retirement_obligations", "segment_capital_expenditures",
                                          "impairment_ppe", "da", "short_borrow", "debt_current", "debt_noncurrent",
                                          "st_issued", "lt_issued", "st_repaid", "lt_repaid"))):
        return False
    return (
        v["assets"] == v["liabilities"] + v["total_equity"]
        and v["total_equity"] == v["book"] + v["minority"]
        and v["net"] == v["net_parent"]
        and v["net_consolidated"] == v["net_parent"] + v["net_nci"] == v["pretax"] - v["tax"]
        and v["cash"] == sum(v[key] for key in ("cash_beginning", "cfo", "cash_investing", "cash_financing", "cash_fx_effect"))
        and v["debt_net"] == v["bank_borrowings_proceeds"] - v["bank_borrowings_repayments"]
        and ("debt_beginning" not in v or v["debt_beginning"] + v["debt_net"] + v["debt_acquired"]
             + v["debt_other_noncash"] == v["debt_total"])
        and 0 <= v["debt_total"] + v["lease_liabilities_separate"] <= v["liabilities"]
        and all(v[key] >= 0 for key in ("assets", "cash", "sales", "debt_total", "lease_liabilities_separate",
                                       "bank_borrowings_proceeds", "bank_borrowings_repayments", "capex_mixed_outflow"))
    )


def china_mobile_amounts(pages, year):
    cover = " ".join(pages[0].split())
    if not all(k in cover for k in (f"Annual Report {year}", CHINA_MOBILE.name, "941 (HKD Counter)")):
        raise ValueError("HKEX PDF cover does not match China Mobile and the selected year")

    income_title = "consolidated statement of comprehensive income"
    cash_title = "consolidated statement of cash flows"
    income = statement_page(pages, year, income_title, "Profit before taxation")
    attribution = statement_page(pages, year, income_title, "Profit attributable to:")
    profit = attribution.split("Profit attributable to:", 1)[1].split("PROFIT FOR THE YEAR", 1)[0]
    assets = statement_page(pages, year, "consolidated balance sheet", "Total assets")
    claims = statement_page(pages, year, "consolidated balance sheet", "Total equity and liabilities")
    operations = statement_page(pages, year, cash_title, "Net cash generated from operating activities")
    investments = statement_page(pages, year, cash_title, "Net cash used in investing activities")
    investments = re.sub(r"(other intangible assets)\s*\n\s*(and non-current assets)", r"\1 \2", investments)
    financing = statement_page(pages, year, cash_title, "Cash and cash equivalents at end of year")
    borrowings = note_table(pages, "BANK AND OTHER BORROWINGS", year, "ACCOUNTS PAYABLE AND ACCRUED EXPENSES")
    movement = borrowing_rollforward(pages, year)

    revenue_section = income.split("Revenue from other businesses", 1)[1].split("Operating expenses", 1)[0]
    subtotal, = re.findall(r"(?m)^ +(\d[\d,]* +\d[\d,]*) *$", revenue_section.partition("\n")[2])

    def amounts(index):
        def read(table, label):
            return column(table, label, 2, column_index=index)

        principal = read(income, "Revenue from principal businesses")
        other = read(income, "Revenue from other businesses")
        if principal + other != read("Total  " + subtotal, "Total"):
            raise ValueError("HKEX revenue components do not match operating revenue")
        parent = read(profit, "Equity shareholders of the Company")
        cash = read(assets, "Cash and cash equivalents")
        total_assets = read(assets, "Total assets")
        if total_assets != read(claims, "Total equity and liabilities") or cash != read(financing, "Cash and cash equivalents at end of year"):
            raise ValueError("HKEX assets or ending cash disagree across audited statements")
        debt = read(claims, BORROWING_LABEL)
        if debt != read(borrowings, "Unsecured Loans"):
            raise ValueError("HKEX borrowing note does not match the balance sheet")
        return {
            "sales": principal + other, "ebit": read(income, "Profit from operations"),
            "pretax": read(income, "Profit before taxation"), "tax": -read(income, "Taxation"),
            "net_consolidated": read(income, "PROFIT FOR THE YEAR"), "net_parent": parent, "net": parent,
            "net_nci": read(profit, "Non-controlling interests"),
            "eps_basic": read(attribution, "Earnings per share – Basic"),
            "eps_diluted": read(attribution, "Earnings per share – Diluted"),
            "assets": total_assets, "liabilities": read(claims, "Total liabilities"),
            "total_equity": read(claims, "Total equity"), "minority": read(claims, "Non-controlling interests"),
            "book": read(claims, "Total equity attributable to equity shareholders of the Company"),
            "cash": cash, "debt_total": debt,
            "lease_liabilities_separate": sum(column(claims, "Lease liabilities", 2, i, index) for i in range(2)),
            "da": read(operations, "– Depreciation and amortisation"),
            "cfo": read(operations, "Net cash generated from operating activities"),
            "cash_investing": read(investments, "Net cash used in investing activities"),
            "capex_mixed_outflow": -read(investments, INVESTMENT_LABEL),
            "cash_financing": read(financing, "Net cash used in financing activities"),
            "cash_beginning": read(financing, "Cash and cash equivalents at beginning of year"),
            "cash_fx_effect": read(financing, "Effect of changes in foreign exchange rate"),
            "div": -read(financing, "Dividends paid to the Company’s equity shareholders"),
            "div_nci": -read(financing, "Dividends paid to non-controlling shareholders of subsidiaries"),
            "bank_borrowings_proceeds": read(financing, PROCEEDS_LABEL),
            "bank_borrowings_repayments": -read(financing, REPAYMENTS_LABEL),
        }

    prior, current = amounts(1), amounts(0)
    if (movement["opening"], movement["proceeds"], movement["repayments"], movement["closing"]) != (
            prior["debt_total"], current["bank_borrowings_proceeds"], current["bank_borrowings_repayments"], current["debt_total"]):
        raise ValueError("HKEX financing note differs from the borrowing and cash-flow statements")
    current.update(debt_beginning=movement["opening"], debt_acquired=movement["acquired"],
                   debt_other_noncash=movement["other_noncash"])
    return prior, current


def petrochina_amounts(pages, year):
    if "PETROCHINA COMPANY LIMITED" not in pages[0] or "ANNUAL REPORT" not in pages[0]:
        raise ValueError("HKEX PDF cover does not identify PetroChina")
    opinion, = (i for i, p in enumerate(pages) if f"as at December 31, {year}" in p and
                "to the shareholders of PetroChina Company Limited" in p and
                "in accordance with IFRS Accounting Standards as issued by the International Accounting Standards" in p)
    ifrs = pages[opinion + 1:]

    def page(heading, date_pattern):
        result, = (p for p in ifrs if heading in map(str.strip, p.splitlines()) and
                   "(All amounts in RMB millions unless otherwise stated)" in p and date_pattern in p
                   and re.search(rf"(?m)^ *(?:Notes +)?{year} +{year - 1} *\n +RMB +RMB|"
                                 rf"^ *(?:Notes +)?31, {year} +31, {year - 1} *\n +RMB +RMB", p))
        return result

    date_marker = f"December 31, {year}"
    income = page("CONSOLIDATED STATEMENT OF COMPREHENSIVE INCOME", date_marker)
    position = page("CONSOLIDATED STATEMENT OF FINANCIAL POSITION", date_marker)
    operations = page("CONSOLIDATED STATEMENT OF CASH FLOWS", date_marker)
    financing = page("CONSOLIDATED STATEMENT OF CASH FLOWS (CONTINUED)", date_marker)
    attribution = income.split("PROFIT FOR THE YEAR ATTRIBUTABLE TO:", 1)[1].split(
        "TOTAL COMPREHENSIVE INCOME FOR THE YEAR ATTRIBUTABLE TO:", 1)[0]
    eps = re.sub(r"PER SHARE ATTRIBUTABLE TO OWNERS\s*\n\s*OF THE COMPANY \(RMB\)",
                 "PER SHARE ATTRIBUTABLE TO OWNERS OF THE COMPANY (RMB)", income)
    note, = (p for p in ifrs if re.search(r"(?m)^ *\d+ +BORROWINGS *$", p)
             and "NOTES TO THE CONSOLIDATED FINANCIAL STATEMENTS" in p)
    note = re.split(r"(?m)^ *\d+ +BORROWINGS *$", note, maxsplit=1)[1]
    note = re.sub(r"(excluding current portion of long-term)\s*\n\s*borrowings", r"\1 borrowings", note)
    note_period = rf"(?m)^ +December 31, {year} +December 31, {year - 1} *\n +RMB +RMB"
    if len(re.findall(note_period, note)) != 2:
        raise ValueError("Unexpected PetroChina borrowing note dates or units")

    def segment_amounts(fiscal_year):
        segment, = (p for p in ifrs if re.search(rf"(?m)^ *31, {fiscal_year} +Energy", p)
                    and "Profit/(loss) from operations" in p and "Capital expenditures" in p)
        segment = re.sub(r"Including: Impairment\s*\n\s*losses of property, plant\s*\n\s*and equipment",
                         "Impairment losses of property, plant and equipment", segment)

        def total(label):
            parts = [column(segment, label, 6, column_index=i) for i in range(6)]
            if sum(parts[:-1]) != parts[-1]:
                raise ValueError(f"PetroChina segment amounts do not reconcile for {label}")
            return parts[-1]

        return total("Capital expenditures"), -total("Impairment losses of property, plant and equipment")

    def amounts(index):
        def read(table, label):
            return column(table, label, 2, column_index=index)

        v = {key: read(table, label) for table, fields in (
            (income, PETRO_INCOME), (position, PETRO_POSITION),
            (operations, PETRO_OPERATIONS), (financing, PETRO_CASH_FLOWS),
        ) for key, label in fields.items()}
        for key in ("tax", "capex", "capex_mixed_outflow", "div", "div_nci", "st_repaid", "lt_repaid"):
            v[key] = -v[key]
        v["net"] = v["net_parent"] = read(attribution, "Owners of the Company")
        v["net_nci"] = read(attribution, "Non-controlling interests")
        v["eps_basic"] = v["eps_diluted"] = read(eps, "BASIC AND DILUTED EARNINGS PER SHARE ATTRIBUTABLE TO OWNERS OF THE COMPANY (RMB)")
        v["assets"] = read(position, "TOTAL CURRENT ASSETS") + read(position, "TOTAL NON-CURRENT ASSETS")
        v["liabilities"] = read(position, "TOTAL CURRENT LIABILITIES") + read(position, "TOTAL NON-CURRENT LIABILITIES")
        v["lease_liabilities_separate"] = sum(column(position, "Lease liabilities", 2, i, index) for i in range(2))
        v["short_borrow"] = read(note, "Short-term borrowings excluding current portion of long-term borrowings")
        v["debt_current"] = read(note, "Current portion of long-term borrowings")
        v["debt_total"] = v["debt_current_total"] + v["debt_noncurrent"]
        v["bank_borrowings_proceeds"] = v["st_issued"] + v["lt_issued"]
        v["bank_borrowings_repayments"] = v["st_repaid"] + v["lt_repaid"]
        v["segment_capital_expenditures"], v["impairment_ppe"] = segment_amounts(year - index)
        v["da"] = v["da_with_impairment"] - v["impairment_ppe"]
        categories = ("Bank loans", "Corporate debentures", "Medium-term notes", "Other loans")
        if (v["debt_total"] != sum(read(note, label) for label in categories)
                or v["debt_noncurrent"] != read(note, "Long-term borrowings")
                or v["cash"] != read(financing, "Cash and cash equivalents at the end of the year")
                or v["da_with_impairment"] != -read(income, "Depreciation, depletion and amortisation")):
            raise ValueError("PetroChina borrowing, cash or depreciation differs between audited statements")
        return v

    return amounts(1), amounts(0)


def field_labels(listing, latest):
    if listing == PETROCHINA:
        return PETRO_FIELDS
    return (MOBILE_FIELDS | DEBT_MOVEMENT_FIELDS) if latest else MOBILE_FIELDS


def read_annual(blob, receipt, report, listing):
    year, filed, url = report
    if receipt["url"] != url or document_day(url) != filed:
        raise ValueError("HKEX annual report receipt does not match the discovered filing")
    pages = pdf_pages(blob)
    parse = {CHINA_MOBILE: china_mobile_amounts, PETROCHINA: petrochina_amounts}[listing]
    prior, current = parse(pages, year)
    if current["cash_beginning"] != prior["cash"]:
        raise ValueError("HKEX opening cash does not match the comparative balance sheet")

    history = []
    for fiscal_year, values in ((year - 1, prior), (year, current)):
        start, end = f"{fiscal_year}-01-01", f"{fiscal_year}-12-31"
        values["debt_net"] = values["bank_borrowings_proceeds"] - values["bank_borrowings_repayments"]
        labels = field_labels(listing, fiscal_year == year)
        facts = {
            key: {"value": value if key in EPS_FIELDS else round(value * MILLION),
                  "unit": "CNY/shares" if key in EPS_FIELDS else "CNY",
                  "start": None if key in STOCK_FIELDS else start, "filed": str(filed), "form": FORM,
                  "source": url, "url": url, "sha256": receipt["sha256"],
                  "tag": f"{ROUTE}:{key}", "locator": labels[key]}
            for key, value in values.items()
        }
        if not reconciles(facts):
            raise ValueError("HKEX consolidated statements do not reconcile")
        history.append({
            "period_kind": "annual", "end": end, "start": start, "currency": "CNY", "accounting": "IFRS",
            "filing": url, "route": ROUTE, "sales_basis": listing.sales_basis, "facts": facts, "conflicts": [],
        })
    return history


def load_annual(cache, listing, asof):
    index, index_receipt = cache.get(index_url(listing, asof), 24)
    report = annual_document(index, listing, asof)
    blob, receipt = cache.get(report[2], 8760)
    return read_annual(blob, receipt, report, listing), {"index": index_receipt, "report": receipt}


def verified_statement(period, exchange, listing, asof):
    """Check published scope, freshness, receipts and cross-statement identities."""
    if any(exchange.get(k) != value for k, value in listing.provenance().items()):
        return False
    index = exchange["index"]
    receipt = exchange["report"]
    url = period["filing"]
    filed = document_day(url)
    end = date.fromisoformat(period["end"])
    if (period["route"], period["period_kind"], period["accounting"], period["currency"], period["sales_basis"]) != (
            ROUTE, "annual", "IFRS", "CNY", listing.sales_basis):
        return False
    if (not filed or not end < filed <= asof or end != date(end.year, 12, 31)
            or (asof - end).days > 465 or period["start"] != f"{end.year}-01-01"
            or index["url"] != index_url(listing, asof) or receipt["url"] != url):
        return False
    if any(not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in (index, receipt)):
        return False
    facts = period["facts"]
    labels = field_labels(listing, latest=True)
    if facts.keys() != labels.keys():
        return False
    for key, fact in facts.items():
        start = None if key in STOCK_FIELDS else period["start"]
        unit = "CNY/shares" if key in EPS_FIELDS else "CNY"
        if ((fact["tag"], fact["locator"], fact["start"], fact["unit"], fact["filed"], fact["form"]) !=
                (f"{ROUTE}:{key}", labels[key], start, unit, str(filed), FORM)
                or fact["source"] != url or fact["url"] != url or fact["sha256"] != receipt["sha256"]
                or type(fact["value"]) not in (int, float) or not math.isfinite(fact["value"])
                or (key not in EPS_FIELDS and (type(fact["value"]) is not int or fact["value"] % MILLION))):
            return False
    return reconciles(facts)
