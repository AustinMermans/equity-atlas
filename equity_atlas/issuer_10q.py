"""Extract selected consolidated fields from reviewed public copies of filed 10-Qs."""
from datetime import date
import re

from .facts import EPS_FIELDS, SHARE_FIELDS, STOCK
from .issuer_20f import column, pdf_pages

QUARTER_COPIES = {
    (831001, "0000831001-26-000056"): "https://www.citigroup.com/rcs/citigpa/storage/public/citi-3q26-10-q.pdf",
    (1326160, "0001326160-26-000051"): (
        "https://d18rn0p25nwr6d.cloudfront.net/CIK-0001326160/dd98210d-a239-4ce5-96d0-4c5d646f585d.pdf"
    ),
}
ROUTE = "issuer_10q"


def quarter_copy_url(cik, report):
    return QUARTER_COPIES.get((cik, report["accession"]))


def page_at(pages, number, *markers):
    page = pages[number-1]
    lines = page.rstrip().splitlines()
    if not lines or lines[-1].strip() != str(number) or any(marker not in page for marker in markers):
        raise ValueError(f"Unexpected layout on filed 10-Q page {number}")
    return page


def load_citi(pages, read, save, kind):
    title = "Citigroup Inc. and Subsidiaries"
    income = page_at(pages, 92, title, "CONSOLIDATED STATEMENT OF INCOME", "Three Months Ended September 30,",
                     "Nine Months Ended September 30,", "In millions of dollars", "2026")
    assets = page_at(pages, 94, title, "CONSOLIDATED BALANCE SHEET", "September 30,", "2026",
                     "In millions of dollars")
    claims = page_at(pages, 95, title, "CONSOLIDATED BALANCE SHEET", "September 30,", "2026",
                     "In millions of dollars")
    equity = page_at(pages, 96, title, "CONSOLIDATED STATEMENT OF CHANGES IN STOCKHOLDERS’ EQUITY", "2026",
                     "In millions of dollars")
    note = page_at(pages, 111, "9. EARNINGS PER SHARE", "Three Months Ended", "Nine Months Ended", "September 30,",
                   "In millions of dollars", "2026")
    read(income, 92, 4, {
        "sales": "Total revenues, net of interest expense", "net_interest_income": "Net interest income (NII)",
        "interest": "Interest expense", "pretax": "Income from continuing operations before income taxes",
        "tax": "Provision for income taxes", "net_parent": "Citigroup’s net income",
        "net_consolidated": "Net income before attribution to noncontrolling interests",
        "net_nci": "Noncontrolling interests (NCI)",
        "net_discontinued": "Income (loss) from discontinued operations, net of taxes",
    })
    read(note, 111, 4, {
        "net_common": "Net income available to common shareholders",
        "net_eps_diluted": "Net income allocated to common shareholders for diluted EPS",
        "preferred_earnings_adjustment": "Less: Preferred dividends",
        "eps_basic": "Net income per share—basic(2)", "eps_diluted": "Net income per share—diluted(2)",
    })
    basic_note = note.split("Basic earnings per share", 1)[0]
    read(basic_note, 111, 4, {
        "net_eps_basic": "Net income allocated to common shareholders for basic EPS",
        "weighted_shares_basic": "Weighted-average common shares outstanding applicable to basic EPS (in millions)",
    })
    read(assets, 94, 2, {
        "assets": "Total assets", "loans_net": "Total loans, net",
        "cash_due_from_banks": "Cash and due from banks (including segregated cash and other deposits)",
    })
    read(claims, 95, 2, {
        "liabilities": "Total liabilities", "book": "Total Citigroup stockholders’ equity",
        "total_equity": "Total equity", "minority": "Noncontrolling interests—equity (NCI—equity)",
        "preferred_liquidation": "—722,000 and as of December 31, 2025—802,000, at aggregate liquidation value",
    })
    read(equity, 96, 4, {"common_book": "Total Citigroup common stockholders’ equity"})
    preferred = column(claims, "—722,000 and as of December 31, 2025—802,000, at aggregate liquidation value", 2)
    save("preferred", preferred, "p. 95 · Preferred stock presented in equity at aggregate liquidation value")
    if kind == "ytd":
        cashflow = page_at(pages, 98, title, "CONSOLIDATED STATEMENT OF CASH FLOWS", "Nine Months Ended",
                           "In millions of dollars", "2026")
        read(cashflow, 98, 2, {
            "cfo_continuing": "Net cash provided by (used in) operating activities of continuing operations",
        })
        cashflow = page_at(pages, 99, "CONSOLIDATED STATEMENT OF CASH FLOWS", "Nine Months Ended",
                           "In millions of dollars", "2026")
        read(cashflow, 99, 2, {"div_total": "Dividends paid", "buybacks": "Treasury stock acquired"},
             outflows={"div_total", "buybacks"})


def load_duke(pages, read, save, kind):
    title = "DUKE ENERGY CORPORATION"
    income = page_at(pages, 9, title, "Condensed Consolidated Statements of Operations", "Three Months Ended",
                     "Nine Months Ended", "September 30,", "(in millions, except per share amounts)", "2026")
    balance = page_at(pages, 11, title, "Condensed Consolidated Balance Sheets", "(in millions)",
                      "September 30, 2026")
    read(income, 9, 4, {
        "sales": "Total operating revenues", "ebit": "Operating Income", "da": "Depreciation and amortization",
        "pretax": "Income From Continuing Operations Before Income Taxes",
        "tax": "Income Tax Expense From Continuing Operations", "net_consolidated": "Net Income",
        "net_parent": "Net Income Attributable to Duke Energy Corporation",
        "net_nci": "Less: Net Income Attributable to NCI",
        "net_discontinued": "Income (Loss) From Discontinued Operations, net of tax",
        "net_common": "Net Income Available to Duke Energy Corporation Common Stockholders",
        "preferred_earnings_adjustment": "Less: Preferred Dividends", "interest": "Interest Expense",
    })
    eps = income.split("\nNet income available to Duke Energy Corporation common stockholders\n")[1]
    per_share, weights = eps.split("\nWeighted Average Shares Outstanding", 1)
    read(per_share, 9, 4, {"eps_basic": "Basic and Diluted", "eps_diluted": "Basic and Diluted"})
    read(weights, 9, 4, {"weighted_shares_basic": "Basic and Diluted", "weighted_shares_diluted": "Basic and Diluted"})
    preferred_row = re.sub(r"(?m)^Preferred stock, Series A,[^\n]*\n2025( +)", r"Preferred stock, Series A\1", balance)
    read(preferred_row, 11, 2, {
        "assets": "Total Assets", "book": "Total Duke Energy Corporation stockholders' equity",
        "total_equity": "Total equity", "minority": "Noncontrolling Interests", "cash": "Cash and cash equivalents",
        "preferred": "Preferred stock, Series A", "short_borrow": "Notes payable and commercial paper",
        "debt_noncurrent": "Long-Term Debt (includes $3,136 at 2026 and $3,308 at 2025 related to VIEs)",
        "debt_current": "Current maturities of long-term debt (includes $167 at 2026 and $118 at 2025 related to VIEs)",
    })
    liabilities = sum(column(balance, label, 2) for label in (
        "Total current liabilities", "Long-Term Debt (includes $3,136 at 2026 and $3,308 at 2025 related to VIEs)",
        "Total other noncurrent liabilities",
    ))
    save("liabilities", liabilities, "p. 11 · Current liabilities + Long-Term Debt + Other Noncurrent Liabilities")
    if kind == "ytd":
        cashflow = page_at(pages, 12, title, "Condensed Consolidated Statements of Cash Flows", "Nine Months Ended",
                           "(in millions)", "2026")
        read(cashflow, 12, 2, {
            "cfo": "Net cash provided by operating activities", "capex": "Capital expenditures",
            "lt_issued": "Issuance of long-term debt", "lt_repaid": "Payments for the redemption of long-term debt",
            "div_total": "Dividends paid",
        }, outflows={"capex", "lt_repaid", "div_total"})


def periods_from_10q(blob, receipt, report, cik, kinds):
    url = quarter_copy_url(cik, report)
    if not url or receipt["url"] != url or report["form"] != "10-Q" or report["end"] != "2026-09-30":
        raise ValueError("Issuer PDF does not match SEC filing metadata")
    pages = pdf_pages(blob)
    issuer, loader = ("Citigroup Inc.", load_citi) if cik == 831001 else ("DUKE ENERGY CORPORATION", load_duke)
    cover = pages[0].casefold()
    if issuer.casefold() not in cover or "form 10-q" not in cover or "september 30, 2026" not in cover:
        raise ValueError("10-Q cover does not match expected issuer and period")

    def statement(kind):
        start = date(2026, 7 if kind == "quarter" else 1, 1).isoformat()
        facts = {}

        def save(key, amount, locator):
            unit = "shares" if key in SHARE_FIELDS else "USD/shares" if key in EPS_FIELDS else "USD"
            facts[key] = {
                "value": amount if key in EPS_FIELDS else int(round(amount * 1_000_000)),
                "unit": unit, "start": None if key in STOCK else start,
                "tag": f"{ROUTE}:{key}", "form": report["form"], "filed": report["filed"],
                "accession": report["accession"], "source": url, "url": report["url"],
                "sha256": receipt["sha256"], "locator": locator,
            }

        def read(page, number, count, rows, outflows=()):
            # Every reviewed four-column table orders current quarter, prior
            # quarter, current YTD, and prior YTD. Stock rows retain the close.
            index = 2 if count == 4 and kind == "ytd" else 0
            for key, label in rows.items():
                amount = column(page, label, count, column_index=index)
                save(key, -amount if key in outflows else amount, f"p. {number} · {label}")

        loader(pages, read, save, kind)
        facts["net"] = facts["net_common"].copy()
        if "common_book" not in facts:
            common_book = (facts["book"]["value"] - facts["preferred"]["value"])/1_000_000
            save("common_book", common_book, "p. 11 · Parent stockholders’ equity less preferred carrying value")
        v = {k: f["value"] for k, f in facts.items()}
        checks = (
            v["assets"]-v["liabilities"]-v["total_equity"],
            v["total_equity"]-v["book"]-v["minority"],
            v["book"]-v["preferred"]-v["common_book"],
            v["net_parent"]-v["preferred_earnings_adjustment"]-v["net_common"],
            v["net_consolidated"]-v["net_nci"]-v["net_parent"],
            v["pretax"]-v["tax"]+v["net_discontinued"]-v["net_consolidated"],
        )
        if any(abs(x) > 1_000_000 for x in checks) or v["assets"] <= 0:
            raise ValueError("10-Q consolidated statement amounts do not reconcile")
        return {"end": report["end"], "start": start, "currency": "USD", "filing": report["accession"],
                "period_kind": kind, "facts": facts, "conflicts": [], "accounting": "US GAAP",
                "report": report, "route": ROUTE}

    return {kind: [statement(kind)] for kind in kinds}
