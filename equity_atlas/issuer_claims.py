"""Read reviewed claim disclosures from public copies of exact annual filings."""
import re

from .issuer_20f import column, pdf_pages, statement_page

CLAIM_COPIES = {
    (2012383, "0001193125-26-071966"): (
        "10-K", "2025-12-31", "USD",
        "https://s24.q4cdn.com/856567660/files/doc_downloads/2026/Q4-25-10-K-Final.pdf",
        frozenset({"redeemable_nci_cips", "redeemable_nci_subco", "redeemable_nci"}),
    ),
    (1303523, "0001303523-26-000017"): (
        "20-F", "2025-12-31", "GBP",
        "https://data.fca.org.uk/artefacts/NSM/DirectUpload/NI-000139233/NI-000139233.pdf",
        frozenset({"hybrid_equity", "liabilities"}),
    ),
}


def claim_copy(cik, filing):
    return CLAIM_COPIES.get((cik, filing["accession"]))


def add_claims(blob, receipt, filing, cik, statement):
    form, end, currency, source, allowed = CLAIM_COPIES[cik, filing["accession"]]
    if (filing["form"], filing["end"], statement["currency"], receipt["url"]) != (form, end, currency, source):
        raise ValueError("Claim disclosure does not match the SEC filing")
    if statement["filing"] != filing["accession"] or statement["end"] != end:
        raise ValueError("Claim disclosure and normalized statement must share the filing")
    pages = pdf_pages(blob)
    extracted = {}

    def save(key, value, locator, components=()):
        extracted[key] = {
            "value": int(round(value * 1_000_000)), "unit": currency, "start": None,
            "tag": f"filing_claims:{key}", "form": form, "filed": filing["filed"],
            "accession": filing["accession"], "source": source, "url": filing["url"],
            "sha256": receipt["sha256"], "locator": locator,
        }
        if components:
            extracted[key]["components"] = list(components)

    if cik == 2012383:
        page = statement_page(pages, "Consolidated Statements of Financial Condition", "F-4",
                              ("BlackRock, Inc.", "December 31,", "2025", "2024", "(in millions",
                               "Temporary equity", "Permanent equity"))
        cips = 'Redeemable noncontrolling interests ("NCI") - consolidated sponsored investment products ("CIPs")'
        subco = "Redeemable NCI - Subco"
        checks = {
            "assets": column(page, "Total assets", 2), "liabilities": column(page, "Total liabilities", 2),
            "total_equity": column(page, "Total permanent equity", 2),
            "book": column(page, "Total BlackRock, Inc. stockholders’ equity", 2),
            "minority": column(page, "Nonredeemable NCI - CIPs", 2),
        }
        a, b = column(page, cips, 2), column(page, subco, 2)
        if checks["assets"] != checks["liabilities"] + checks["total_equity"] + a + b:
            raise ValueError("BlackRock temporary equity lines do not reconcile to total assets")
        save("redeemable_nci_cips", a, f"F-4 · {cips}")
        save("redeemable_nci_subco", b, f"F-4 · {subco}")
        save("redeemable_nci", a+b, "F-4 · Redeemable NCI in CIPs and Subco",
             ("redeemable_nci_cips", "redeemable_nci_subco"))
    else:
        page = statement_page(pages, "Group Balance Sheet", "102",
                              ("British American Tobacco p.l.c. Form 20-F 2025", "31 December", "£m", "2024"))
        page = re.sub(r"(?m)^(Perpetual hybrid bonds|Non-controlling interests) +22\([de]\)", r"\1", page)
        checks = {
            "assets": column(page, "Total assets", 2), "total_equity": column(page, "Total equity", 2),
            "book": column(page, "Owners of the parent", 2),
            "minority": column(page, "Non-controlling interests", 2),
        }
        hybrid = column(page, "Perpetual hybrid bonds", 2)
        liabilities = sum(column(page, f"Total {term} liabilities", 2) for term in ("current", "non-current"))
        if (checks["total_equity"] != checks["book"] + checks["minority"] + hybrid
                or checks["assets"] != checks["total_equity"] + liabilities):
            raise ValueError("BAT balance sheet and hybrid equity do not reconcile")
        save("hybrid_equity", hybrid, "p. 102 · Perpetual hybrid bonds in consolidated equity")
        save("liabilities", liabilities, "p. 102 · Total current liabilities + total non-current liabilities")

    facts = statement["facts"]
    for key, value in checks.items():
        if key not in facts or facts[key]["value"] != value * 1_000_000:
            raise ValueError(f"Claim disclosure disagrees with the SEC statement on {key}")
    if set(extracted) != allowed:
        raise ValueError("Unexpected equity claim extraction")
    for key, fact in extracted.items():
        if key in facts and facts[key]["value"] != fact["value"]:
            raise ValueError(f"Claim disclosure disagrees with the SEC statement on {key}")
    return {**statement, "facts": {**extracted, **facts}}
