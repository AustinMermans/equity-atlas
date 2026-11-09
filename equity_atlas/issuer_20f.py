"""Extract reviewed consolidated tables from issuer-hosted copies of filed 20-Fs."""
from datetime import date, timedelta
import re
import subprocess

from .facts import EPS_FIELDS, STOCK

# Bind each public document and table layout to the matching SEC accession.
# A later filing requires a reviewed profile, even if an issuer reuses a URL.
MIRRORS = {
    (1119639, "0001292814-26-002168"): (
        "2025-12-31", "USD",
        "https://petrobras.com.br/documents/2677942/17808296/FORM%2B20F%2B2025%2BEN.pdf/"
        "3b6371b3-900d-ae05-294d-f9acd9d8b26e?download=true&t=1777312960000&version=1.0",
    ),
    (1022837, "0001193125-26-283871"): (
        "2026-03-31", "JPY",
        "https://www.smfg.co.jp/english/investor/library/annual/2026_pdf/fy2026_form20f_e_00.pdf",
    ),
}

AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
CELL = re.compile(rf"(?:{AMOUNT}|\({AMOUNT}\)|[−–—-])")


def statement_page(pages, title, footer, markers):
    matches = [page for page in pages if title in page.splitlines() and page.rstrip().endswith(footer)]
    if len(matches) != 1 or any(marker not in matches[0] for marker in markers):
        raise ValueError(f"Missing expected layout for {title} ({footer})")
    return matches[0]


def column(table, label, count, occurrence=None):
    # The last columns are the reported fiscal years. A leading number may
    # instead be a note reference. Dotted leaders occur in the SMFG layout.
    lines = re.findall(rf"^ *{re.escape(label)}(?: {{2,}}| \. \.)(.*)$", table, re.M)
    if len(lines) != (2 if occurrence is not None else 1):
        raise ValueError(f"Unexpected number of rows for {label}")
    line = lines[occurrence or 0].replace("¥", " ")
    cells = re.sub(r"\. +(?=\.|\s)", " ", line).split()
    # The row matcher has already consumed the first two leader dots.
    cells = [cell for cell in cells if cell != "."]
    if len(cells) == count + 1 and re.fullmatch(r"[0-9]{1,2}", cells[0]):
        cells = cells[1:]
    if len(cells) != count or not all(CELL.fullmatch(cell) for cell in cells):
        raise ValueError(f"Unexpected number of fiscal columns for {label}")
    value = cells[0].replace(",", "")
    if value in {"−", "–", "—", "-"}:
        return 0
    return float(value.replace("(", "-").replace(")", ""))


def read_mirror(blob, receipt, report, cik):
    end, currency, url = MIRRORS[cik, report["accession"]]
    if report["end"] != end or report["form"] != "20-F" or receipt["url"] != url:
        raise ValueError("Issuer copy does not match SEC metadata")
    if not blob.startswith(b"%PDF-") or len(blob) > 32_000_000:
        raise ValueError("Unexpected 20-F document type or size")
    try:
        output = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=blob,
            capture_output=True, check=True, timeout=25,
        ).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError("Cannot extract text from issuer 20-F") from exc
    pages = output.decode("utf-8").split("\f")
    day = date.fromisoformat(end)
    start = str(day.replace(year=day.year - 1) + timedelta(days=1))
    facts = {}

    def read(page, footer, count, rows, outflows=()):
        for key, label in rows.items():
            amount = column(page, label, count)
            if key in outflows:
                amount = -amount
            save(key, amount, f"{footer} · {label}")

    def save(key, amount, locator, concept=None):
        facts[key] = {
            "value": amount if key in EPS_FIELDS else int(round(amount * 1_000_000)),
            "unit": f"{currency}/shares" if key in EPS_FIELDS else currency,
            "start": None if key in STOCK else start,
            "filed": report["filed"], "form": report["form"],
            "tag": f"issuer20f:{concept or key}", "source": url, "url": report["url"],
            "sha256": receipt["sha256"], "locator": locator,
        }

    if cik == 1119639:
        basis = "Expressed in millions of US Dollars"
        bs = statement_page(pages, "Consolidated Statements of Financial Position", "F-3",
                            ("PETROBRAS", basis, "12.31.2025", "12.31.2024"))
        income = statement_page(pages, "Consolidated Statements of Income", "F-4",
                                ("PETROBRAS", basis, "December 31, 2025, 2024 and 2023"))
        cf = statement_page(pages, "Consolidated Statements of Cash Flows", "F-6",
                            ("PETROBRAS", basis, "December 31, 2025 and 2024 and 2023"))
        read(bs, "F-3", 2, {
            "assets": "Total assets", "liabilities": "Current and non-current liabilities",
            "book": "Attributable to the shareholders of Petrobras", "total_equity": "Equity",
            "minority": "Non-controlling interests", "cash": "Cash and cash equivalents",
            "inventory": "Inventories", "ap": "Trade payables",
        })
        for key, label in [("ar", "Trade and other receivables"), ("st_investments", "Financial investments")]:
            save(key, column(bs, label, 2, 0), f"F-3 · Current assets · {label}")
        for index, key in enumerate(("debt_current_total", "debt_noncurrent")):
            debt = column(bs, "Finance debt", 2, index) + column(bs, "Lease liability", 2, index)
            save(key, debt, f"F-3 · {'Current' if index == 0 else 'Non-current'} finance debt plus lease liability")
        read(income, "F-4", 3, {
            "sales": "Sales revenues", "net_consolidated": "Net income for the year",
            "net_parent": "Net income attributable to shareholders of Petrobras",
            "ebit": "Income before net finance income, results of equity-accounted investments and income taxes",
            "pretax": "Net income before income taxes", "tax": "Income taxes",
            "eps_basic": "Basic and diluted earnings per common and preferred share - in U.S. dollars",
        }, outflows={"tax"})
        facts["eps_diluted"] = {**facts["eps_basic"], "tag": "issuer20f:eps_diluted"}
        read(cf, "F-6", 3, {
            "cfo": "Net cash provided by operating activities",
            "capex": "Acquisition of PP&E and intangible assets",
            "da": "Depreciation, depletion and amortization",
            "div": "Dividends paid to Shareholders of Petrobras",
            "buybacks": "Share repurchase program",
        }, outflows={"capex", "div", "buybacks"})
        facts["net"] = facts["net_parent"].copy()
    else:
        bs = statement_page(pages, "Consolidated Statements of Financial Position", "F-8",
                            ("At March 31,", "2026", "2025", "(In millions)", "¥"))
        income = statement_page(pages, "Consolidated Income Statements", "F-9",
                                ("March 31,", "2026", "2025", "2024", "(In millions, except per share data)", "¥"))
        cf = statement_page(pages, "Consolidated Statements of Cash Flows", "F-13",
                            ("March 31,", "2026", "2025", "2024", "(In millions)", "¥"))
        bs = re.sub(r"(Equity attributable to shareholders of Sumitomo Mitsui) *\n +Financial Group, Inc\.",
                    r"\1 Financial Group, Inc.", bs)
        read(bs, "F-8", 2, {
            "assets": "Total assets", "liabilities": "Total liabilities",
            "common_book": "Equity attributable to shareholders of Sumitomo Mitsui Financial Group, Inc.",
            "total_equity": "Total equity", "minority": "Non-controlling interests",
            "customer_deposits": "Deposits", "loans_net": "Loans and advances",
        })
        # The issuer reports perpetual instruments in equity, separately from shareholders.
        instruments = "Equity attributable to other equity instruments holders"
        other_equity = column(bs, instruments, 2)
        save("book", facts["common_book"]["value"] / 1_000_000 + other_equity,
             f"F-8 · Shareholders' equity plus {instruments.lower()}")
        read(income, "F-9", 3, {
            "net_common": "Shareholders of Sumitomo Mitsui Financial Group, Inc.",
            "net_consolidated": "Net profit", "net_interest_income": "Net interest income",
            "pretax": "Profit before tax", "tax": "Income tax expense",
            "eps_basic": "Basic", "eps_diluted": "Diluted",
        })
        save("net_parent", facts["net_common"]["value"] / 1_000_000 +
             column(income, "Other equity instruments holders", 3),
             "F-9 · Profit attributable to shareholders plus other equity instruments holders")
        read(cf, "F-13", 3, {
            "cfo": "Net cash and cash equivalents provided by (used in) operating activities",
            "cash": "Cash and cash equivalents at end of period",
            "div": "Dividends paid to shareholders of Sumitomo Mitsui Financial Group, Inc.",
            "da": "Depreciation and amortization",
        }, outflows={"div"})
        # The cash-flow statement's ending cash is a point-in-time balance.
        facts["div"]["tag"] = "issuer20f:PaymentsOfOrdinaryShareDividends"
        facts["net"] = facts["net_common"].copy()

    values = {k: v["value"] for k, v in facts.items()}
    checks = [
        values["assets"] - values["liabilities"] - values["total_equity"],
        values["total_equity"] - values["minority"] - values["book"],
        values["pretax"] - values["tax"] - values["net_consolidated"],
    ]
    if any(abs(diff) > 1_000_000 for diff in checks) or min(values["assets"], values["cash"]) <= 0:
        raise ValueError("Issuer 20-F statement totals do not reconcile")
    return {"end": end, "start": start, "currency": currency, "filing": report["accession"],
            "period_kind": "annual", "facts": facts, "conflicts": [],
            "accounting": "IFRS", "report": report, "route": "issuer_20f"}
