"""Verify source provenance and date/coverage rules before publishing Pages."""
from datetime import date
import json
import math
import re
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from equity_atlas import hkex
from equity_atlas.annual_exhibit import (OPERATING_TAG as CLIENT_FUNDS_EBIT_TAG, PINNED as EXHIBIT_PINNED,
                                         TAG as EXHIBIT_TAG, exhibit_facts)
from equity_atlas.balance_sheet import EQUITY_TAG as BALANCE_EQUITY_TAG, TAG as BALANCE_LIABILITIES_TAG, balance_facts
from equity_atlas.borrowing_cash import TAG as BORROWING_CASH_TAG, borrowing_cash_facts
from equity_atlas.capex import (ADDITIONAL_FIELDS as CAPEX_ADDITIONAL_FIELDS, APPLOVIN, APP_INVESTMENT_GAP,
                                AXP, CAPEX_TAG, DISPOSAL_PROCEEDS, INTANGIBLES, NET_PURCHASES, PINNED as CAPEX_PINNED,
                                NET_FIELDS, reports_only_net_purchases, required_additional_fields, valid_capex_components)
from equity_atlas.cash_balance import (BROAD as CASH_BROAD, GAPS as CASH_GAPS, PROFILED as CASH_PROFILED,
                                        REVIEW_EXISTING as CASH_REVIEW_EXISTING, TAG as CASH_TAG, UNALLOCATED as CASH_FLOW_UNALLOCATED,
                                        cash_facts, cash_gap,
                                        rule_key as cash_rule_key)
from equity_atlas.catalog import SUCCESSIONS
from equity_atlas.debt import FACE as DEBT_PINNED, TAG as DEBT_TAG, debt_facts
from equity_atlas.dividends import (COMMON as DIVIDEND_COMMON, PROFILES as DIVIDEND_PINNED, TAG as DIVIDEND_TAG,
                                    dividend_facts, supported as dividend_supported)
from equity_atlas.deere import CIK as DEERE, PINNED as DEERE_PINNED, TAG as BUSINESS_TAG, business_facts
from equity_atlas.depreciation import (PINNED as DEPRECIATION_PINNED, TAG as DEPRECIATION_TAG, gap_reason as depreciation_gap,
                                       profile_fields as depreciation_fields, reconciles as depreciation_reconciles,
                                       rule_key as depreciation_rule_key, valid_component as valid_depreciation_component)
from equity_atlas.filing_notes import (LINE_TAG as NOTE_LINE_TAG, PINNED as NOTES_PINNED, TAG as NOTE_TAG,
                                        note_line_facts, notes_for, valid_note)
from equity_atlas.inline import inline_url
from equity_atlas.facts import balance_check
from equity_atlas.edgar import REVIEWED_AMENDMENTS, issuer_instance_url
from equity_atlas.issuer_claims import claim_copy
from equity_atlas.issuer_10q import ROUTE as QUARTER_PDF_ROUTE, quarter_copy_url
from equity_atlas.issuer_20f import BHP_CAPEX_TAG, COPY_SOURCES, FCA_BHP, MIRRORS, bhp_investment_reconciles
from equity_atlas.sec_workbook import (CAPEX_COMPONENTS as WORKBOOK_CAPEX_COMPONENTS, CAPEX_TAG as WORKBOOK_CAPEX_TAG,
                                       DA_COMPONENTS, DA_TAG as WORKBOOK_DA_TAG, PROFILES, ROUTE as WORKBOOK_ROUTE,
                                       SOURCE as WORKBOOK_SOURCE, workbook_url)
from equity_atlas.rendered_10q import ROUTE as RENDERED_ROUTE, TABLES, rendered_10q_url, table_url
from equity_atlas.operating import (INCOME_SUBTOTAL_TAG, OPERATING_TAG, PRETAX_BRIDGE_TAG,
                                    PROFILES as INCOME_PROFILES, bank_income_reconciles, gap_reason, income_tag,
                                    profile_for as income_profile_for, scoped_income_reconciles, scoped_pretax_facts)
from equity_atlas.parent_equity import TAG as PARENT_EQUITY_TAG, equity_facts
from equity_atlas.rendered_filing import ENDPOINT as RENDERED_ENDPOINT, table_belongs_to_filing
from equity_atlas.market import CBC_FX, OPEN_LICENSE, TWSE_CLOSE, TWSE_DAILY_QUOTES, TWSE_ISSUERS, TWSE_ISSUERS_CSV

snap=json.loads(Path(sys.argv[1]).read_text())
rows=snap["rows"]
open_market=snap["mode"]=="public_market"
if snap["mode"] not in {"public_fundamentals","public_market"} or "ranking" in snap or not rows:
    raise SystemExit("Wrong snapshot edition")
if [r["symbol"] for r in rows]!=sorted({r["symbol"] for r in rows}):
    raise SystemExit("Public universe must be alphabetical by unique symbol")
asof=date.fromisoformat(snap["as_of"])
fresh=0
sec_count=0
hkex_covered=set()
interim_expected=0
quarters=0
capex_profiles=0
liabilities_available=0
revenue_available=0
parent_equity_available=0
liabilities_recovered=0
note_profiles=0
business_profiles=0
income_profiles=0
operating_gaps=0
depreciation_profiles=0
depreciation_gaps=0
exhibit_profiles=0
prices=[]
market=snap.get("market_sources",{})
if open_market:
    receipts=market.get("receipts",{})
    close_url = receipts.get("close", {}).get("url")
    dated_close = TWSE_DAILY_QUOTES.format(date.fromisoformat(market["date"]).strftime("%Y%m%d"))
    if (market.get("license") != OPEN_LICENSE or close_url not in {TWSE_CLOSE, dated_close} or
            receipts.get("shares", {}).get("url") not in {TWSE_ISSUERS, TWSE_ISSUERS_CSV}):
        raise SystemExit("Unverified public market sources")
    fx=market.get("fx")
    if fx and (fx["date"]!=market["date"] or fx["source"]["url"]!=CBC_FX or not 15<=fx["rate"]<=60):
        raise SystemExit("Unverified same-date FX")

def annual_cik(row, report):
    cik = int(row["id"].removeprefix("sec:"))
    succession = SUCCESSIONS.get(cik)
    if succession and row["edgar"].get("succession") == succession:
        predecessor = succession["predecessor_cik"]
        if report["path"].startswith(f"https://www.sec.gov/Archives/edgar/data/{predecessor}/"):
            return predecessor
    return cik


def verify_income_fact(period, report, cik, profile, key, fact):
    parts = fact.get("components", [])
    terms = profile.fields[key]
    tags = dict(profile.line_tags)
    filename = profile.table if (cik, report["accession"]) in INCOME_PROFILES else None
    return (
        period["period_kind"] == "annual" and
        period["filing"] == report["accession"] == fact["accession"] and
        period["end"] == report["end"] and fact["url"] == report["url"] and
        fact["filed"] == report["filed"] and fact["form"] == report["form"] and
        fact["start"] == period["start"] and fact["unit"] == period["currency"] and
        fact["source"] == RENDERED_ENDPOINT and
        table_belongs_to_filing(fact.get("table_url"), report, filename) and
        re.fullmatch(r"[0-9a-f]{64}", fact["sha256"]) and
        re.fullmatch(r"[0-9a-f]{16}", fact.get("table_sha256_16", "")) and
        bool(fact.get("locator")) and len(parts) == len(terms) and
        all(part["sign"] == (-1 if term.startswith("-") else 1) and
            part["line"] == term.removeprefix("-") and bool(part["tag"]) and
            part["tag"] == tags.get(part["line"], part["tag"]) and
            math.isfinite(part["value"]) for part, term in zip(parts, terms)) and
        fact["value"] == sum(part["sign"] * part["value"] for part in parts) and
        fact["tag"] == income_tag(key, parts)
    )


def verify_depreciation_fact(period, report, cik, field, fact):
    terms = depreciation_fields(cik, report).get(field)
    parts = fact.get("components", [])
    keys = ("url", "accession", "filed", "form", "start", "unit")
    expected = (report["url"], report["accession"], report["filed"], report["form"], period["start"], period["currency"])
    return (
        terms and len(parts) == len(terms) and period["period_kind"] == "annual" and
        period["filing"] == report["accession"] and period["end"] == report["end"] and
        tuple(fact[k] for k in keys) == expected and fact["source"] == parts[0]["source"] and
        fact["sha256"] == parts[0]["sha256"] and bool(fact.get("locator")) and
        all(tuple(part[k] for k in keys) == expected and part["tag"] == tag.removeprefix("-") and
            part["sign"] == (-1 if tag.startswith("-") else 1) and part["line"] == label and
            math.isfinite(part["value"]) and part["value"] >= 0 and
            re.fullmatch(r"[0-9a-f]{64}", part["sha256"]) and valid_depreciation_component(cik, report, field, part)
            for part, (tag, label) in zip(parts, terms)) and
        fact["value"] == sum(part["sign"] * part["value"] for part in parts)
    )


def verify_period(period, row):
    mirror = None
    workbook = None
    route = period.get("route")
    interim_copy = None
    rendered = None
    resolvers = {"issuer_inline": inline_url, "issuer_instance": issuer_instance_url, QUARTER_PDF_ROUTE: quarter_copy_url}
    if route in resolvers:
        report = row["edgar"]["latest_interim"]
        cik = int(row["id"].removeprefix("sec:"))
        interim_copy = resolvers[route](cik,report)
        if (not interim_copy or period["report"] != report or
                row["edgar"]["interim_routes"].get(period["period_kind"]) != route):
            raise SystemExit("Public copy does not match the expected SEC interim filing")
    if route == RENDERED_ROUTE:
        report = row["edgar"]["latest_interim"]
        cik = int(row["id"].removeprefix("sec:"))
        rendered = rendered_10q_url(cik, report)
        if (not rendered or period["report"] != report or
                row["edgar"]["interim_routes"].get(period["period_kind"]) != route):
            raise SystemExit("Rendered tables do not match the expected SEC interim filing")
        sections = TABLES if period["period_kind"] == "ytd" else TABLES.keys() - {"cash_flow"}
        rendered_tables = {table_url(report, section) for section in sections}
    if route in COPY_SOURCES:
        report = row["edgar"]["latest_annual"]
        cik = int(row["id"].removeprefix("sec:"))
        mirror = MIRRORS.get((cik, report["accession"]))
        if (not mirror or period["filing"] != report["accession"] or
                (period["end"], period["currency"]) != mirror[:2] or period["report"] != report or
                row["source"] != COPY_SOURCES[route] or row["edgar"]["annual_route"] != route or
                (route == "regulator_20f") != (mirror[2] == FCA_BHP)):
            raise SystemExit("Public copy does not match the expected SEC filing")
        if route == "regulator_20f" and cik == 811809 and not bhp_investment_reconciles(period["facts"]):
            raise SystemExit("BHP exploration and capital investment amounts do not reconcile")
    elif row["source"] in COPY_SOURCES.values() and period is row["statement"]:
        raise SystemExit("Missing public 20-F provenance")
    if route == WORKBOOK_ROUTE:
        report = row["edgar"]["latest_annual"]
        cik = int(row["id"].removeprefix("sec:"))
        workbook = workbook_url(cik, report)
        if (not workbook or period is not row["statement"] or period["filing"] != report["accession"] or
                period["report"] != report or period["end"] != report["end"] or
                period["currency"] != PROFILES[cik, report["accession"]][1] or
                row["source"] != WORKBOOK_SOURCE or row["edgar"]["annual_route"] != WORKBOOK_ROUTE):
            raise SystemExit("SEC workbook does not match the expected annual filing")
    elif row["source"] == WORKBOOK_SOURCE and period is row["statement"]:
        raise SystemExit("Missing SEC workbook provenance")
    annual_report = period.get("report") if period is row["statement"] else None
    selected_cik = annual_cik(row, annual_report) if annual_report else None
    income_profile = income_profile_for(selected_cik, annual_report) if annual_report else None
    parent_equity = {}
    if parent_evidence := period.get("annual_parent_equity"):
        try:
            parent_equity = equity_facts(selected_cik, annual_report, period, parent_evidence)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            raise SystemExit("Unverified annual parent-equity reconciliation") from exc
        if any(period["facts"].get(key) != value for key, value in parent_equity.items()):
            raise SystemExit("Parent equity differs from its filed closing equity columns")
    balance_evidence = period.get("annual_balance_sheet")
    balance = {}
    if balance_evidence:
        try:
            balance = balance_facts(annual_report, period, balance_evidence)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            raise SystemExit("Unverified annual balance-sheet liability reconciliation") from exc
        if any(period["facts"].get(key) != value for key, value in balance.items()):
            raise SystemExit("Filed liability or equity amount differs from the balance-sheet reconciliation")
    debt = {}
    if debt_evidence := period.get("annual_debt"):
        try:
            debt = debt_facts(selected_cik, annual_report, period, debt_evidence)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            raise SystemExit("Unverified annual borrowing reconciliation") from exc
        if any(period["facts"].get(key) != value for key, value in debt.items()):
            raise SystemExit("Annual borrowing differs from its filed components")
    borrowing_cash = {}
    if evidence := period.get("annual_borrowing_cash"):
        try:
            borrowing_cash, pending = borrowing_cash_facts(annual_report, period, evidence)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            raise SystemExit("Unverified annual borrowing cash flows") from exc
        if (pending != period.get("borrowing_cash_pending") or
                any(period["facts"].get(key) != value for key, value in borrowing_cash.items())):
            raise SystemExit("Annual borrowing cash flows differ from their filed components")
    cash = {}
    if cash_evidence := period.get("annual_cash_balance"):
        try:
            cash = cash_facts(selected_cik, annual_report, period, cash_evidence)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            raise SystemExit("Unverified annual cash-balance reconciliation") from exc
        if any(period["facts"].get(key) != value for key, value in cash.items()):
            raise SystemExit("Cash balance differs from the filed reconciliation")
    dividends = {}
    if dividend_evidence := period.get("annual_dividends"):
        try:
            dividends = dividend_facts(selected_cik, annual_report, period, dividend_evidence)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            raise SystemExit("Unverified annual cash distributions") from exc
        if any(period["facts"].get(key) != value for key, value in dividends.items()):
            raise SystemExit("Annual cash distributions differ from the filed reconciliation")
    evidence = period.get("annual_earnings_exhibit")
    disclosed = {}
    if evidence:
        try:
            disclosed = exhibit_facts(selected_cik, annual_report, period, evidence)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise SystemExit("Unverified annual earnings exhibit") from exc
        if any(period["facts"].get(key) != value for key, value in disclosed.items()):
            raise SystemExit("Annual earnings exhibit facts do not reconcile")
    lines = note_line_facts(selected_cik, annual_report, period["facts"]) if annual_report else {}
    if any(period["facts"].get(key) != value for key, value in lines.items()):
        raise SystemExit("Annual note line differs from the reconciled source")
    try:
        pretax_scope = scoped_pretax_facts(selected_cik, annual_report, period) if annual_report else {}
    except (ValueError, KeyError, TypeError) as exc:
        raise SystemExit("Unverified annual pretax bridge") from exc
    if any(period["facts"].get(key) != value for key, value in pretax_scope.items()):
        raise SystemExit("Annual pretax scope differs from the reconciled source")
    scope_evidence = period.get("annual_business_scopes")
    scoped = {}
    if scope_evidence:
        try:
            scoped = business_facts(selected_cik, annual_report, period, scope_evidence)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise SystemExit("Unverified annual business scopes") from exc
        if any(period["facts"].get(key) != value for key, value in scoped.items()):
            raise SystemExit("Annual business-scope facts do not reconcile")
    for key, fact in period["facts"].items():
        source=fact["source"]
        url=fact["url"]
        official=source.startswith(("https://data.sec.gov/", "https://www.sec.gov/Archives/edgar/"))
        if mirror:
            official=(source==mirror[2] and url==report["url"] and fact["filed"]==report["filed"] and
                      fact["form"]==report["form"] and fact["tag"].startswith(route + ":") and
                      len(fact["sha256"])==64)
        if workbook:
            official = (source == workbook and url == report["url"] and fact["accession"] == report["accession"]
                        and fact["filed"] == report["filed"] and fact["form"] == report["form"]
                        and fact["tag"].startswith(WORKBOOK_ROUTE + ":") and bool(fact.get("locator"))
                        and len(fact["sha256"]) == 64)
        if interim_copy:
            locator = fact.get("locator") if route == QUARTER_PDF_ROUTE else fact.get("context_id")
            official = (source == interim_copy and url == report["url"] and fact["accession"] == report["accession"]
                        and fact["filed"] == report["filed"] and fact["form"] == report["form"]
                        and bool(locator) and len(fact["sha256"]) == 64)
        if rendered:
            official = (source == rendered and url == report["url"] and fact["accession"] == report["accession"]
                        and fact["filed"] == report["filed"] and fact["form"] == report["form"]
                        and fact.get("table_url") in rendered_tables and bool(fact.get("locator"))
                        and len(fact["table_sha256_16"]) == 16 and len(fact["sha256"]) == 64)
        if fact["tag"].startswith("filing_claims:"):
            report = period.get("report")
            cik = int(row["id"].removeprefix("sec:"))
            profile = claim_copy(cik,report) if report else None
            official = bool(profile and period is row["statement"] and
                            profile[:3] == (report["form"],period["end"],period["currency"]) and
                            source == profile[3] and key in profile[4] and fact["tag"] == f"filing_claims:{key}" and
                            url == report["url"] and period["filing"] == report["accession"] == fact["accession"] and
                            fact["filed"] == report["filed"] and fact["form"] == report["form"] and
                            fact["unit"] == period["currency"] and fact["start"] is None and
                            bool(fact.get("locator")) and len(fact["sha256"]) == 64)
        if fact["tag"] == CAPEX_TAG or key in CAPEX_ADDITIONAL_FIELDS:
            report = annual_report
            components = fact.get("components", []) if key == "capex" else [fact]
            signed_net = key in NET_FIELDS or (key == "capex" and selected_cik == AXP[0])
            official = bool(
                report and period["period_kind"] == "annual" and
                valid_capex_components(components, selected_cik, report, key) and
                period["filing"] == report["accession"] and period["end"] == report["end"] and
                fact["value"] == sum(p["value"] for p in components) and
                (key in NET_FIELDS or fact["value"] >= 0) and
                fact["source"] == components[0]["source"] and fact["sha256"] == components[0]["sha256"] and
                all(p["url"] == report["url"] and p["accession"] == report["accession"] and
                    p["filed"] == report["filed"] and p["form"] == report["form"] and
                    p["start"] == period["start"] and p["unit"] == period["currency"] and
                    math.isfinite(p["value"]) and (p["value"] >= 0 or signed_net and p is components[0]) and
                    bool(p.get("locator")) and
                    re.fullmatch(r"[0-9a-f]{64}", p["sha256"])
                    for p in components) and
                all(fact[k] == components[0][k] for k in ("url", "accession", "filed", "form", "start", "unit"))
            )
        if fact["tag"] in {OPERATING_TAG, INCOME_SUBTOTAL_TAG} or (income_profile and key in income_profile.fields and source == RENDERED_ENDPOINT):
            official = bool(income_profile and key in income_profile.fields and
                            verify_income_fact(period, annual_report, selected_cik, income_profile, key, fact))
        if fact["tag"] == DEPRECIATION_TAG:
            official = bool(annual_report and verify_depreciation_fact(period, annual_report, selected_cik, key, fact))
        if fact["tag"] == BUSINESS_TAG:
            official = scoped.get(key) == fact
        if fact["tag"] == PARENT_EQUITY_TAG:
            official = parent_equity.get(key) == fact
        if fact["tag"] in {BALANCE_LIABILITIES_TAG, BALANCE_EQUITY_TAG}:
            official = balance.get(key) == fact
        if fact["tag"] in {DIVIDEND_COMMON, DIVIDEND_TAG}:
            official = dividends.get(key) == fact
        if fact["tag"] == BORROWING_CASH_TAG:
            official = borrowing_cash.get(key) == fact
        if fact["tag"] == DEBT_TAG:
            official = debt.get(key) == fact
        if fact["tag"] == CASH_TAG:
            official = cash.get(key) == fact
        if fact["tag"] == PRETAX_BRIDGE_TAG:
            official = pretax_scope.get(key) == fact
        if fact["tag"] == NOTE_LINE_TAG:
            official = lines.get(key) == fact
        if fact["tag"] == NOTE_TAG:
            official = bool(annual_report and valid_note(period, annual_report, selected_cik, key, fact))
        if fact["tag"] == WORKBOOK_CAPEX_TAG:
            official = bool(official and workbook and selected_cik == 1046179 and key == "capex" and
                            fact.get("components") == list(WORKBOOK_CAPEX_COMPONENTS) and
                            all(k in period["facts"] and period["facts"][k]["value"] >= 0 for k in WORKBOOK_CAPEX_COMPONENTS) and
                            fact["value"] == sum(period["facts"][k]["value"] for k in WORKBOOK_CAPEX_COMPONENTS))
        if fact["tag"] == WORKBOOK_DA_TAG:
            parts = DA_COMPONENTS.get(selected_cik, ())
            official = bool(official and workbook and parts and key == "da" and
                            fact.get("components") == list(parts) and
                            (fact["unit"], fact["start"]) == (period["currency"], period["start"]) and
                            all(k in period["facts"] and period["facts"][k]["value"] >= 0 and
                                all(period["facts"][k][attr] == fact[attr] for attr in ("unit", "start", "source", "sha256"))
                                for k in parts) and fact["value"] == sum(period["facts"][k]["value"] for k in parts))
        if fact["tag"] in {EXHIBIT_TAG, CLIENT_FUNDS_EBIT_TAG}:
            official = disclosed.get(key) == fact
        if not official or not url.startswith("https://www.sec.gov/Archives/edgar/"):
            raise SystemExit("Unverified SEC fact source")
        if not date.fromisoformat(period["end"])<=date.fromisoformat(fact["filed"])<=asof:
            raise SystemExit("Fact dated outside the observation window")
        if not math.isfinite(fact["value"]):
            raise SystemExit("Nonfinite fact")

for row in rows:
    if row["id"].startswith("sec:"):
        sec_count += 1
    if {"market_cap_usd","rank","fx"}&row.keys():
        raise SystemExit("Unapproved market data found in public snapshot")
    q=row.get("market")
    if q:
        if not open_market or q["exchange"]!="XTAI" or q["date"]!=market["date"]:
            raise SystemExit("Unexpected exchange quote")
        if not 0 <= (asof-date.fromisoformat(q["date"])).days <= 7 or date.fromisoformat(q["shares_date"])>asof:
            raise SystemExit("Unusable market date")
        if q["issued_shares"]<=0 or q["close"]<=0 or not math.isclose(q["estimated_cap_twd"],q["close"]*q["issued_shares"]):
            raise SystemExit("Market-cap calculation mismatch")
        if fx and not math.isclose(q["estimated_cap_usd"],q["estimated_cap_twd"]/fx["rate"]):
            raise SystemExit("Currency conversion mismatch")
        prices.append(q)
    if {"models","ratios"}&row.keys() and not q:
        raise SystemExit("Valuation without an approved market input")
    if row["id"].startswith("hkex:"):
        try:
            exchange = row["exchange_filing"]
            listing = hkex.listing_for(exchange["former_cik"], asof)
            verified = (listing and row["id"] == listing.row_id and row["symbol"] == listing.symbol
                        and row["source"] == hkex.SOURCE
                        and hkex.verified_statement(row["statement"], exchange, listing, asof))
        except (KeyError, TypeError, ValueError):
            verified = False
        if not verified:
            raise SystemExit(f"Missing or unverified HKEX annual report for {row['symbol']}")
        hkex_covered.add(row["id"])
    elif row["statement"]:
        verify_period(row["statement"], row)
        if "annual_exhibits_profiled" in snap["stats"] and row["id"].startswith("sec:"):
            period = row["statement"]
            report = period.get("report")
            cik = annual_cik(row, report) if report else None
            profiled = bool(period.get("annual_earnings_exhibit"))
            if report and (cik, report["accession"]) in EXHIBIT_PINNED and not profiled:
                raise SystemExit(f"Refusing to lose reconciled annual earnings exhibit for {row['symbol']}")
            exhibit_profiles += profiled
        if "annual_cash_investment_profiled" in snap["stats"] and row["id"].startswith("sec:"):
            period = row["statement"]
            report = period.get("report")
            cik = annual_cik(row, report) if report else None
            facts = period["facts"]
            net_only = report and reports_only_net_purchases(cik, report)
            profiled = NET_PURCHASES in facts if net_only else facts.get("capex", {}).get("tag") in {
                CAPEX_TAG, WORKBOOK_CAPEX_TAG, BHP_CAPEX_TAG,
            }
            if net_only and "capex" in facts:
                raise SystemExit(f"Net purchases were promoted to gross cash investment for {row['symbol']}")
            if report and (cik, report["accession"]) in CAPEX_PINNED and not profiled:
                raise SystemExit(f"Refusing to lose verified annual cash investment for {row['symbol']}")
            if profiled and report and not required_additional_fields(cik, report) <= period["facts"].keys():
                raise SystemExit(f"Missing a reviewed separate cash outflow for {row['symbol']}")
            if cik == 1046179 and period.get("route") == WORKBOOK_ROUTE:
                if period["facts"].get("capex", {}).get("tag") != WORKBOOK_CAPEX_TAG:
                    raise SystemExit("Missing TSMC workbook cash-investment total")
            if profiled and cik == AXP[0]:
                if facts["capex"]["components"] != [facts[NET_PURCHASES], facts[DISPOSAL_PROCEEDS]]:
                    raise SystemExit("American Express gross purchases do not match the filed net and sales lines")
            if report and (cik, report["accession"]) == APPLOVIN:
                facts = period["facts"]
                intangible, = (p["value"] for p in facts["capex"]["components"] if p["tag"] == INTANGIBLES)
                continuing = facts["capex_intangibles_continuing"]
                discontinued = facts["capex_intangibles_discontinued"]
                if (period.get("capital_investment_gap") != APP_INVESTMENT_GAP or
                        continuing["value"] + discontinued["value"] != intangible or
                        continuing["sha256"] != discontinued["sha256"] or
                        discontinued["sha256"] != facts["capex"]["components"][0]["sha256"]):
                    raise SystemExit("AppLovin continuing and discontinued intangible cash purchases do not reconcile")
            capex_profiles += profiled
        if "annual_note_profiled" in snap["stats"] and row["id"].startswith("sec:"):
            period = row["statement"]
            report = period.get("report")
            cik = annual_cik(row, report) if report else None
            expected = notes_for(cik, report) if report else {}
            profiled = {k for k, f in period["facts"].items() if f["tag"] == NOTE_TAG}
            if (profiled or report and (cik, report["accession"]) in NOTES_PINNED) and profiled != expected.keys():
                raise SystemExit(f"Refusing to lose reconciled annual filing notes for {row['symbol']}")
            note_profiles += bool(profiled)
        if "annual_business_scopes_profiled" in snap["stats"] and row["id"] == f"sec:{DEERE:010d}":
            period = row["statement"]
            profiled = bool(period.get("annual_business_scopes"))
            if period["filing"] == DEERE_PINNED and not profiled:
                raise SystemExit("Refusing to lose Deere business-scope reconciliation")
            business_profiles += profiled
        if "annual_income_profiled" in snap["stats"] and row["id"].startswith("sec:"):
            period = row["statement"]
            report = period.get("report")
            cik = annual_cik(row, report) if report else None
            profile = income_profile_for(cik, report) if report else None
            pinned = bool(report and (cik, report["accession"]) in INCOME_PROFILES)
            if pinned or period.get("income_profiled"):
                expected_basis = profile.sales_basis if profile else None
                if (not profile or not period.get("income_profiled") or period.get("sales_basis") != expected_basis or
                        any(period["facts"].get(key, {}).get("source") != RENDERED_ENDPOINT
                            for key in profile.fields) or not scoped_income_reconciles(cik, report, period["facts"])
                        or not bank_income_reconciles(profile, period)):
                    raise SystemExit(f"Refusing to lose reconciled income statement fields for {row['symbol']}")
                income_profiles += 1
            elif period.get("income_profiled") or period.get("sales_basis"):
                raise SystemExit(f"Unexpected annual income statement profile for {row['symbol']}")
            if row["history"][-1].get("sales_basis") != period.get("sales_basis"):
                raise SystemExit(f"Annual revenue basis differs between the statement and history for {row['symbol']}")
            expected_gap = gap_reason(cik, report) if report and "ebit" not in period["facts"] else None
            if period.get("operating_profit_gap") != expected_gap:
                raise SystemExit(f"Unverified annual operating profit gap for {row['symbol']}")
            operating_gaps += bool(expected_gap)
        if "annual_depreciation_profiled" in snap["stats"] and row["id"].startswith("sec:"):
            period = row["statement"]
            report = period.get("report")
            cik = annual_cik(row, report) if report else None
            fields = depreciation_fields(cik, report) if report else {}
            facts = period["facts"]
            profiled = any(fact["tag"] == DEPRECIATION_TAG for fact in facts.values())
            if report and ((cik, report["accession"]) in DEPRECIATION_PINNED and fields or profiled):
                if (any(facts.get(key, {}).get("tag") != DEPRECIATION_TAG for key in fields) or
                        not depreciation_reconciles(depreciation_rule_key(cik, report), facts)):
                    raise SystemExit(f"Refusing to lose reconciled depreciation and amortization for {row['symbol']}")
                depreciation_profiles += 1
            if cik in DA_COMPONENTS and period.get("route") == WORKBOOK_ROUTE:
                if facts.get("da", {}).get("tag") != WORKBOOK_DA_TAG:
                    raise SystemExit(f"Missing {row['symbol']} workbook depreciation and amortization total")
                depreciation_profiles += 1
            expected_gap = depreciation_gap(cik, report) if report and "da" not in facts else None
            if period.get("depreciation_gap") != expected_gap:
                raise SystemExit(f"Unverified annual depreciation and amortization gap for {row['symbol']}")
            depreciation_gaps += bool(expected_gap)
        if row["id"].startswith("sec:"):
            parent_equity_available += "book" in row["statement"]["facts"]
            revenue_available += "sales" in row["statement"]["facts"]
            liabilities = row["statement"]["facts"].get("liabilities")
            liabilities_available += bool(liabilities)
            liabilities_recovered += bool(liabilities and liabilities["tag"] == BALANCE_LIABILITIES_TAG)
        if "balance_check" in row and row["balance_check"] != balance_check(row["statement"]):
            raise SystemExit("Balance-sheet reconciliation does not match published facts")
        fresh += 0 <= (asof-date.fromisoformat(row["statement"]["end"])).days <= 465
    if row["id"].startswith("hkex:") and row["balance_check"] != balance_check(row["statement"]):
        raise SystemExit("HKEX balance-sheet reconciliation does not match published facts")
    audit = row.get("edgar", {})
    annual = audit.get("latest_annual")
    if ("annual_business_scopes_profiled" in snap["stats"] and row["id"] == f"sec:{DEERE:010d}"
            and annual and annual["accession"] == DEERE_PINNED
            and (row["statement"] or {}).get("filing") != DEERE_PINNED):
        raise SystemExit("Refusing to lose Deere's verified annual filing")
    if row["id"].startswith("sec:"):
        cik = int(row["id"].removeprefix("sec:"))
        if annual and (row["statement"] or {}).get("filing") != annual["accession"]:
            filing_key = (cik, annual["accession"])
            mirror = MIRRORS.get(filing_key)
            if "annual_cash_investment_profiled" in snap["stats"] and mirror and mirror[2] == FCA_BHP:
                raise SystemExit("Refusing to lose the verified BHP annual filing")
            if "annual_note_profiled" in snap["stats"] and filing_key in NOTES_PINNED:
                raise SystemExit(f"Refusing to lose the annual filing with reconciled notes for {row['symbol']}")
        if annual and workbook_url(cik, annual) and (row["statement"] or {}).get("filing") != annual["accession"]:
            raise SystemExit(f"Refusing to lose verified annual coverage for {row['symbol']}")
        interim = audit.get("latest_interim")
        if (audit.get("metadata") == "verified" and interim and
                interim["end"] > (annual or {}).get("end", "")):
            interim_expected += 1
            quarters += bool(audit.get("quarter"))
            if rendered_10q_url(cik, interim) and not (audit.get("quarter") and audit.get("ytd")):
                raise SystemExit(f"Refusing to lose verified interim coverage for {row['symbol']}")
    succession = audit.get("succession")
    if succession:
        cik = int(row["id"].removeprefix("sec:"))
        if succession != SUCCESSIONS.get(cik) or date.fromisoformat(succession["effective"]) > asof:
            raise SystemExit("Unverified registrant succession")
    reviews = audit.get("amendment_reviews", [])
    if reviews:
        statement, annual = row["statement"], audit["latest_annual"]
        if row["id"].startswith("hkex:"):
            statement = row["exchange_filing"].get("archived_annual") or {}
        if (statement.get("end") != annual["end"] or reviews[-1]["accession"] != annual["accession"]
                or reviews[-1]["url"] != annual["url"] or
                any(REVIEWED_AMENDMENTS.get((statement["filing"], r["accession"])) != r["scope"] for r in reviews)):
            raise SystemExit("Amendment review does not match the reported accessions")
    for kind in ("quarter","ytd"):
        if audit.get(kind):
            period, interim = audit[kind], audit["latest_interim"]
            if period["period_kind"] != kind or period["filing"] != interim["accession"] or period["end"] != interim["end"]:
                raise SystemExit("Interim period does not match the expected SEC filing")
            verify_period(period, row)

for source, count in (("Issuer 20-F", "latest_annual_issuer_mirror"), ("FCA 20-F", "latest_annual_regulator_mirror"),
                      (WORKBOOK_SOURCE, "latest_annual_sec_workbook")):
    if sum(r["source"]==source for r in rows)!=snap["stats"].get(count,0):
        raise SystemExit(f"{source} coverage mismatch")
if "annual_exhibits_profiled" in snap["stats"] and exhibit_profiles != snap["stats"]["annual_exhibits_profiled"]:
    raise SystemExit("Annual earnings exhibit coverage mismatch")
if "annual_business_scopes_profiled" in snap["stats"] and business_profiles != snap["stats"]["annual_business_scopes_profiled"]:
    raise SystemExit("Annual business-scope coverage mismatch")
if "annual_note_profiled" in snap["stats"] and note_profiles != snap["stats"]["annual_note_profiled"]:
    raise SystemExit("Annual filing note coverage does not match published facts")
if "annual_cash_investment_profiled" in snap["stats"] and capex_profiles != snap["stats"]["annual_cash_investment_profiled"]:
    raise SystemExit("Annual cash investment profile coverage mismatch")
if "annual_cash_available" in snap["stats"]:
    cash_available = cash_scoped = cash_evidence_count = cash_unallocated_count = 0
    for row in rows:
        if not row["id"].startswith("sec:"):
            continue
        period = row["statement"]
        if not period:
            raise SystemExit(f"Missing annual cash-balance evidence for {row['symbol']}")
        report, facts = period.get("report"), period["facts"]
        cik = annual_cik(row, report) if report else None
        key = (cik, report["accession"]) if report else None
        expected_gap = cash_gap(cik, report, facts) if report else None
        recurring_review = report and cash_rule_key(cik, report) in CASH_REVIEW_EXISTING
        if (key in CASH_PROFILED or recurring_review) and not period.get("annual_cash_balance"):
            raise SystemExit(f"Missing reviewed cash evidence for {row['symbol']}")
        if (period.get("cash_gap") != expected_gap or (key in CASH_GAPS and "cash" in facts) or
                ("cash" not in facts and (not expected_gap or CASH_BROAD not in facts))):
            raise SystemExit(f"Missing or unverified cash scope for {row['symbol']}")
        cash_available += "cash" in facts
        cash_unallocated_count += CASH_FLOW_UNALLOCATED in facts
        cash_evidence_count += bool(period.get("annual_cash_balance")) and CASH_FLOW_UNALLOCATED not in facts
        cash_scoped += bool(expected_gap)
    if (cash_available, cash_scoped) != (snap["stats"]["annual_cash_available"], snap["stats"]["annual_cash_scoped_gaps"]):
        raise SystemExit("Annual cash coverage does not match published facts")
    if "annual_cash_evidence" in snap["stats"] and cash_evidence_count != snap["stats"]["annual_cash_evidence"]:
        raise SystemExit("Annual cash evidence coverage does not match published facts")
    if "annual_cash_unallocated" in snap["stats"] and cash_unallocated_count != snap["stats"]["annual_cash_unallocated"]:
        raise SystemExit("Annual unallocated cash difference coverage does not match published facts")
if "annual_debt_reconciled" in snap["stats"]:
    debt_count = funding_count = 0
    for row in rows:
        period = row["statement"] or {}
        if report := period.get("report"):
            key = (annual_cik(row, report), report["accession"])
            if key in DEBT_PINNED and not period.get("annual_debt"):
                raise SystemExit(f"Missing reviewed annual borrowing evidence for {row['symbol']}")
        if period.get("annual_debt"):
            debt_count += period["facts"].get("debt_total", {}).get("tag") == DEBT_TAG
            funding_count += any(k.startswith("funding_") and v["tag"] == DEBT_TAG for k, v in period["facts"].items())
    if debt_count != snap["stats"]["annual_debt_reconciled"]:
        raise SystemExit("Annual borrowing evidence coverage does not match published facts")
    if funding_count != snap["stats"].get("annual_funding_reconciled", 0):
        raise SystemExit("Annual funding evidence coverage does not match published facts")
if "annual_net_borrowing_cash" in snap["stats"]:
    periods = [row["statement"] or {} for row in rows if row["id"].startswith("sec:")]
    net = sum(p.get("facts", {}).get("debt_net", {}).get("tag") == BORROWING_CASH_TAG for p in periods)
    gaps = sum(bool(p.get("borrowing_cash_pending")) for p in periods)
    if (net, gaps) != (snap["stats"]["annual_net_borrowing_cash"], snap["stats"]["annual_borrowing_cash_scope_gaps"]):
        raise SystemExit("Annual borrowing cash-flow coverage does not match the filed facts")
if "annual_dividend_reconciled" in snap["stats"]:
    dividend_count = common_count = 0
    for row in rows:
        period = row["statement"] or {}
        if report := period.get("report"):
            cik = annual_cik(row, report)
            verified = bool(period.get("annual_dividends"))
            gap = period.get("dividend_scope_gap", False)
            if ((cik, report["accession"]) in DIVIDEND_PINNED and not verified or
                    dividend_supported(cik, report) != (verified or gap) or verified and gap):
                raise SystemExit(f"Missing or contradictory annual dividend evidence for {row['symbol']}")
            dividend_count += verified
            common_count += period["facts"].get("div", {}).get("tag") == DIVIDEND_COMMON
    if (dividend_count, common_count) != (snap["stats"]["annual_dividend_reconciled"],
                                         snap["stats"]["annual_common_dividend_reconciled"]):
        raise SystemExit("Annual dividend coverage does not match published facts")
if "annual_parent_equity_available" in snap["stats"] and (
        parent_equity_available != sec_count or parent_equity_available != snap["stats"]["annual_parent_equity_available"]):
    raise SystemExit(f"Annual parent-equity coverage incomplete: {parent_equity_available}/{sec_count}")
if "annual_revenue_available" in snap["stats"] and (
        revenue_available != sec_count or revenue_available != snap["stats"]["annual_revenue_available"]):
    raise SystemExit(f"Annual revenue coverage incomplete: {revenue_available}/{sec_count}")
if "annual_liabilities_available" in snap["stats"] and (
        liabilities_available != sec_count or liabilities_available != snap["stats"]["annual_liabilities_available"]
        or liabilities_recovered != snap["stats"].get("annual_liabilities_recovered")):
    raise SystemExit(f"Annual total-liability coverage incomplete: {liabilities_available}/{sec_count}")
if "annual_income_profiled" in snap["stats"] and (income_profiles, operating_gaps) != (
        snap["stats"]["annual_income_profiled"], snap["stats"]["annual_operating_profit_reviewed_gaps"]):
    raise SystemExit("Annual income statement coverage mismatch")
if "annual_depreciation_profiled" in snap["stats"] and (depreciation_profiles, depreciation_gaps) != (
        snap["stats"]["annual_depreciation_profiled"], snap["stats"]["annual_depreciation_reviewed_gaps"]):
    raise SystemExit("Annual depreciation and amortization coverage mismatch")
if "interim_expected" in snap["stats"] and (interim_expected, quarters) != (
        snap["stats"]["interim_expected"], snap["stats"]["interim_available"]):
    raise SystemExit("Standalone interim coverage mismatch")
if "hkex_annual_expected" in snap["stats"]:
    symbols = {r["symbol"] for r in rows}
    expected = {p.row_id for p in hkex.LISTINGS.values() if p.symbol in symbols and hkex.listing_for(p.cik, asof)}
    if hkex_covered != expected or (len(hkex_covered), len(expected)) != (
            snap["stats"]["hkex_annual_covered"], snap["stats"]["hkex_annual_expected"]):
        raise SystemExit("HKEX annual filing coverage mismatch")
elif hkex_covered:
    raise SystemExit("Missing HKEX annual filing coverage statistics")
if fresh < .80*sec_count or fresh + len(hkex_covered) != snap["stats"]["fresh"]:
    raise SystemExit(f"Refusing to deploy coverage regression: {fresh}/{sec_count} recent SEC statements")
if open_market:
    prices.sort(key=lambda q:q["rank"])
    if (len(prices)!=50 or len({q["code"] for q in prices})!=50
            or [q["rank"] for q in prices]!=list(range(1,51))
            or any(a["estimated_cap_twd"]<b["estimated_cap_twd"] for a,b in zip(prices,prices[1:]))):
        raise SystemExit("Public Taiwan universe incomplete or misranked")
    if snap["stats"]["metadata_verified"] < .95*sec_count:
        raise SystemExit("Insufficient SEC submissions coverage")
print(f"Public artifact verified: {fresh}/{sec_count} recent SEC statements, {len(hkex_covered)} HKEX annual, "
      f"{len(prices)} exchange prices, dated {asof}")
