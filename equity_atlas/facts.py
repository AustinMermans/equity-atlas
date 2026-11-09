"""Conservative annual statement extraction with concept and filing provenance."""
from collections import defaultdict
from datetime import date
from decimal import Decimal, localcontext
import math
import re

# Alias order is policy; consolidated parent/shareholder concepts precede broader fallbacks.
TAGS = {
    "sales": "RevenuesNetOfInterestExpense Revenues Revenue SalesRevenueNet RevenueFromContractWithCustomerExcludingAssessedTax RevenueFromContractWithCustomerIncludingAssessedTax",
    "contract_sales": "RevenueFromContractWithCustomerExcludingAssessedTax RevenueFromContractWithCustomerIncludingAssessedTax",
    "net": "NetIncomeLossAvailableToCommonStockholdersBasic ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity ProfitLossAttributableToOwnersOfParent NetIncomeLoss ProfitLoss",
    "net_parent": "ProfitLossAttributableToOwnersOfParent NetIncomeLoss",
    "net_consolidated": "ProfitLoss",
    "net_common": "NetIncomeLossAvailableToCommonStockholdersBasic ProfitLossAttributableToOrdinaryEquityHoldersOfParentEntity",
    "ebit": "OperatingIncomeLoss ProfitLossFromOperatingActivities",
    "assets": "Assets",
    "liabilities": "Liabilities",
    "book": "StockholdersEquity EquityAttributableToOwnersOfParent",
    "total_equity": "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest Equity",
    "preferred": "PreferredStockIncludingAdditionalPaidInCapitalNetOfDiscount PreferredStockIncludingAdditionalPaidInCapital PreferredStockCarryingValue PreferredStockValue",
    "preferred_liquidation": "PreferredStockLiquidationPreferenceValue",
    "common_book": "CommonStockholdersEquity",
    "shares_outstanding": "CommonStockSharesOutstanding",
    "weighted_shares_basic": "WeightedAverageNumberOfSharesOutstandingBasic",
    "weighted_shares_diluted": "WeightedAverageNumberOfDilutedSharesOutstanding",
    "eps_basic": "EarningsPerShareBasic BasicEarningsLossPerShare",
    "eps_diluted": "EarningsPerShareDiluted DilutedEarningsLossPerShare",
    "minority": "MinorityInterest NoncontrollingInterests",
    "cash": "CashAndCashEquivalentsAtCarryingValue CashAndCashEquivalents",
    "cash_due_from_banks": "CashAndDueFromBanks",
    "interest_bearing_deposits_at_banks": "InterestBearingDepositsInBanks",
    "customer_deposits": "Deposits",
    "loans_net": "LoansAndLeasesReceivableNetReportedAmount",
    "net_interest_income": "InterestIncomeExpenseNet InterestRevenueExpense",
    "credit_loss_provision": "ProvisionForLoanLeaseAndOtherLosses",
    "st_investments": "ShortTermInvestments ShortTermInvestmentsAvailableForSale",
    "debt_total": "DebtLongtermAndShorttermCombinedAmount DebtAndLeaseObligations Borrowings",
    "debt": "LongTermDebtAndCapitalLeaseObligations LongTermDebt",
    "debt_current": "LongTermDebtAndCapitalLeaseObligationsCurrent LongTermDebtCurrent CurrentPortionOfLongTermBorrowings",
    "debt_noncurrent": "LongTermDebtAndCapitalLeaseObligationsNoncurrent LongTermDebtNoncurrent NoncurrentBorrowings",
    "short_borrow": "ShortTermBorrowings ShortTermDebt",
    "debt_current_total": "CurrentBorrowings",
    "cfo": "NetCashProvidedByUsedInOperatingActivities CashFlowsFromUsedInOperatingActivities",
    "capex": "PaymentsToAcquirePropertyPlantAndEquipment PaymentsToAcquireProductiveAssets PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities PurchaseOfPropertyPlantAndEquipment",
    "tax": "IncomeTaxExpenseBenefit IncomeTaxExpenseContinuingOperations TaxExpense",
    "pretax": "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest ProfitLossBeforeTax",
    "ar": "AccountsReceivableNetCurrent TradeReceivables",
    "inventory": "InventoryNet Inventories",
    "ap": "AccountsPayableCurrent TradePayables",
    "lt_issued": "ProceedsFromIssuanceOfLongTermDebt",
    "lt_repaid": "RepaymentsOfLongTermDebt",
    "st_issued": "ProceedsFromShortTermDebt",
    "st_repaid": "RepaymentsOfShortTermDebt",
    "interest": "InterestExpenseDebt InterestAndDebtExpense InterestExpense InterestExpenseOnBorrowings",
    "div": "PaymentsOfDividendsCommonStock PaymentsOfOrdinaryShareDividends PaymentsOfDividends PaymentsOfOrdinaryDividends DividendsPaidClassifiedAsFinancingActivities DividendsPaid",
    "div_total": "PaymentsOfDividends PaymentsOfOrdinaryDividends DividendsPaidClassifiedAsFinancingActivities DividendsPaid",
    "div_preferred_paid": "PaymentsOfDividendsPreferredStock PaymentsOfPreferredDividends",
    "div_common_declared": "DividendsCommonStockCash",
    "preferred_earnings_adjustment": "PreferredStockDividendsAndOtherAdjustments",
    "buybacks": "PaymentsForRepurchaseOfCommonStock PaymentsToAcquireOrRedeemEntitysShares",
    "issuance": "ProceedsFromStockPlans ProceedsFromIssuanceOfCommonStock ProceedsFromIssuingShares",
    "debt_net": "ProceedsFromRepaymentsOfDebt",
    "da": "DepreciationDepletionAndAmortization DepreciationAndAmortization DepreciationAndAmortisationExpense",
    "da_with_accretion": "DepreciationAmortizationAndAccretionNet",
    "depreciation": "Depreciation DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
    "amortization": "AmortizationOfIntangibleAssets AmortisationOfIntangibleAssets",
    "oci": "OtherComprehensiveIncomeLossNetOfTax OtherComprehensiveIncomeAttributableToOwnersOfParent",
}
STOCK = {"assets","liabilities","book","total_equity","preferred","minority","cash","st_investments","debt","debt_current","debt_noncurrent","short_borrow","debt_total","ar","inventory","ap","common_book","preferred_liquidation","shares_outstanding","debt_current_total","cash_due_from_banks","interest_bearing_deposits_at_banks","customer_deposits","loans_net"}
ANNUAL = {"10-K","10-K/A","20-F","20-F/A","40-F","40-F/A","10-KT"}
INTERIM = {"10-Q","10-Q/A","10-QT","10-QT/A"}
REGISTRATION = {"S-1","S-1/A","F-1","F-1/A","424B4"}
SHARE_FIELDS = {"shares_outstanding","weighted_shares_basic","weighted_shares_diluted"}
EPS_FIELDS = {"eps_basic","eps_diluted"}
ALIASES = {metric: val.split() for metric, val in TAGS.items()}
REVERSE = defaultdict(list)
for metric, tags in ALIASES.items():
    for i, tag in enumerate(tags):
        REVERSE[tag].append((metric,i))

def qualifies(metric, start, end, kind="annual"):
    if metric in STOCK:
        return start is None
    bounds = {"annual": (330, 400), "quarter": (70, 115), "ytd": (145, 300)}
    low, high = bounds[kind]
    return start is not None and low <= (end - start).days + 1 <= high

def sec_filing_index(submissions, cik, asof):
    """Resolve accession metadata from the registrant's own submission feed."""
    if int(submissions["cik"]) != cik:
        raise ValueError("SEC submissions CIK mismatch")
    recent = submissions["filings"]["recent"]
    result = {}
    for i, accession in enumerate(recent["accessionNumber"]):
        form = recent["form"][i]
        filed = recent["filingDate"][i]
        report = recent["reportDate"][i]
        primary = recent["primaryDocument"][i]
        if (form not in ANNUAL | INTERIM | REGISTRATION or not report or
            not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession) or
            not re.fullmatch(r"[a-zA-Z0-9_.-]+", primary) or
            not date.fromisoformat(report) <= date.fromisoformat(filed) <= asof):
            continue
        path = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}"
        result[accession] = {"end": report, "filed": filed, "form": form, "url": f"{path}/{primary}",
                             "primary": primary, "path": path, "accession": accession}
    return result

def latest_filing(index, forms):
    return max((x for x in index.values() if x["form"] in forms),
               key=lambda x: (x["end"], x["filed"], x["accession"]), default=None)

def precise_duplicates(facts):
    """Keep the most precise representation of consistent tagged duplicates."""
    by_precision = {}
    lower, upper = [], []
    if len({(x["tag"], x.get("unit")) for x in facts}) != 1:
        return []
    with localcontext() as context:
        context.prec = 80
        for fact in facts:
            raw = fact.get("decimals") or ""
            value = Decimal(str(fact["value"]))
            if raw == "INF":
                precision, radius = 100, Decimal(0)
            elif re.fullmatch(r"-?[0-9]{1,2}", raw) and -30 <= int(raw) <= 30:
                precision = int(raw)
                radius = Decimal("0.5").scaleb(-precision)
            else:
                return []
            candidates = by_precision.setdefault(precision, [])
            if candidates and candidates[0]["value"] != fact["value"]:
                return []
            candidates.append(fact)
            lower.append(value-radius)
            upper.append(value+radius)
    return by_precision[max(by_precision)] if max(lower) <= min(upper) else []


def _pick_fields(metrics):
    # Count distinct flow concepts per start date, not duplicate fact records.
    starts = defaultdict(set)
    for metric, items in metrics.items():
        for item in items:
            if item["start"] is not None:
                starts[item["start"]].add(metric)
    if not starts:
        return None, {}, []
    start = max(starts, key=lambda k: (len(starts[k] & {"sales","net","ebit","cfo"}), len(starts[k]), k))
    chosen, conflicts = {}, []
    for metric, items in metrics.items():
        eligible = [x for x in items if x["start"] is None or x["start"] == start]
        if not eligible:
            continue
        priority = min(x["priority"] for x in eligible)
        eligible = [x for x in eligible if x["priority"] == priority]
        if len({x["value"] for x in eligible}) != 1:
            eligible = precise_duplicates(eligible)
            if not eligible:
                conflicts.append(metric)
                continue
        fact = max(eligible, key=lambda x: (x["filed"], x["tag"], x.get("fact_id", ""))).copy()
        fact.pop("priority")
        chosen[metric] = fact
    if "book" not in chosen and "book" not in conflicts and {"total_equity","minority"} <= chosen.keys():
        total, minority = chosen["total_equity"], chosen["minority"]
        chosen["book"] = {**total, "value": total["value"] - minority["value"],
                          "tag": "derived:ParentBook",
                          "components": {"total_equity": total["tag"], "noncontrolling_equity": minority["tag"]},
                          "locator": "Total equity less noncontrolling equity"}
    if {"book","preferred"} <= chosen.keys() and "common_book" not in chosen and not {"book","preferred"} & set(conflicts):
        book, preferred = chosen["book"], chosen["preferred"]
        chosen["common_book"] = {**book, "value": book["value"] - preferred["value"],
                                 "tag": "derived:CommonBook",
                                 "components": {"parent_book": book["tag"], "preferred_carrying_value": preferred["tag"]},
                                 "locator": "Parent equity less preferred carrying value"}
    return start, chosen, sorted(conflicts)

def _assemble(groups, filings=None, kind="annual"):
    """Choose a coherent as-filed report, then a reporting currency and period."""
    filings = filings or {}
    by_end = defaultdict(list)
    for (end, currency, accession), metrics in groups.items():
        start, chosen, conflicts = _pick_fields(metrics)
        if "net" not in chosen or not {"sales","book"} & chosen.keys():
            continue
        pub = max(x["filed"] for x in chosen.values())
        info = filings.get(accession)
        same_report = bool(info and info["end"] == str(end))
        near = (date.fromisoformat(pub) - end).days <= 240
        # A full amended report supersedes its original. Without the accession's
        # period, favor well-covered near-period facts over later comparatives.
        score = (same_report, near, pub if same_report else "", len(chosen), pub, currency, accession)
        record = {"end": str(end), "start": start, "currency": currency, "filing": accession,
                  "facts": chosen, "conflicts": conflicts, "period_kind": kind}
        if info:
            record["report"] = info
        by_end[end].append((score, record))
    result = [max(candidates, key=lambda pair: pair[0])[1] for _, candidates in sorted(by_end.items())]
    if kind != "annual":
        return result
    dedup = []
    for item in result:
        if dedup and (date.fromisoformat(item["end"]) - date.fromisoformat(dedup[-1]["end"])).days < 290:
            if len(item["facts"]) >= len(dedup[-1]["facts"]):
                dedup[-1] = item
        else:
            dedup.append(item)
    return dedup[-10:]

def _group_sec(payload, meta, asof, cik, filings, kind):
    if int(payload["cik"]) != cik:
        raise ValueError("SEC payload CIK mismatch")
    groups = defaultdict(lambda: defaultdict(list))
    forms = ANNUAL | REGISTRATION if kind == "annual" else INTERIM
    for ns in ("us-gaap", "ifrs-full"):
        for tag, series in payload["facts"].get(ns, {}).items():
            if tag not in REVERSE:
                continue
            for unit, records in series["units"].items():
                # Match a compatible monetary currency after we collect shares.
                if not re.fullmatch(r"[A-Z]{3}(?:/shares)?|shares", unit):
                    continue
                for x in records:
                    if x.get("form") not in forms or not x.get("filed") or not x.get("accn"):
                        continue
                    end = date.fromisoformat(x["end"])
                    filed = date.fromisoformat(x["filed"])
                    if not 0 <= (asof - end).days <= 4400 or not end <= filed <= asof:
                        continue
                    start = date.fromisoformat(x["start"]) if x.get("start") else None
                    accession = x["accn"]
                    info = filings.get(accession)
                    if kind != "annual" and info and info["end"] != str(end):
                        continue
                    for metric, priority in REVERSE[tag]:
                        if not qualifies(metric, start, end, kind) or not math.isfinite(x["val"]):
                            continue
                        if (metric in SHARE_FIELDS) != (unit == "shares") or (metric in EPS_FIELDS) != unit.endswith("/shares"):
                            continue
                        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace('-', '')}/{accession}-index.htm"
                        groups[(end, unit.split("/")[0], accession)][metric].append({
                            "value": x["val"], "tag": ns + ":" + tag, "filed": str(filed), "unit": unit,
                            "start": str(start) if start else None, "accession": accession, "form": x["form"],
                            "priority": priority, "url": info["url"] if info else url,
                            "source": meta["url"], "sha256": meta["sha256"],
                        })
    for (end, currency, accession), fields in list(groups.items()):
        if currency != "shares":
            fields.update(groups.get((end, "shares", accession), {}))
    return {key: fields for key, fields in groups.items() if key[1] != "shares"}

def from_sec(payload, meta, asof, cik, filings=None, kind="annual"):
    filings = filings or {}
    groups = _group_sec(payload, meta, asof, cik, filings, kind)
    return _assemble(groups, filings, kind)

def from_esef(entries, asof, lei):
    groups = defaultdict(lambda:defaultdict(list))
    for attr, obj, meta in entries:
        filed_str = (attr.get("published") or attr.get("date_added") or "")[:10]
        if not filed_str:
            continue
        filed = date.fromisoformat(filed_str)
        if filed > asof or attr.get("error_count"):
            continue
        for fact_id,x in obj.get("facts",{}).items():
            dim = x.get("dimensions",{})
            if set(dim) - {"concept","entity","period","unit","language"}:
                continue  # no segments, share classes, or parent-only statement dimensions
            if dim.get("entity","").split(":")[-1].upper() != lei:
                continue
            name = dim.get("concept","")
            if not name.startswith("ifrs-full:"):
                continue
            tag = name.split(":")[-1]
            cur = dim.get("unit","").removeprefix("iso4217:")
            period = dim.get("period","")
            if tag not in REVERSE or not re.fullmatch("[A-Z]{3}",cur) or not period:
                continue
            try:
                times = period.split("/")
                # xBRL-JSON dateTime end is exclusive, e.g. Jan 1 00:00 means Dec 31 close.
                from datetime import timedelta
                end = date.fromisoformat(times[-1][:10])
                if "T00:00:00" in times[-1]:
                    end -= timedelta(days=1)
                start = date.fromisoformat(times[0][:10]) if len(times)==2 else None
                val = float(x["value"])
            except (ValueError,TypeError,KeyError):
                continue
            if not 0 <= (asof-end).days <= 4400 or not end <= filed or not math.isfinite(val):
                continue
            for metric, priority in REVERSE[tag]:
                if qualifies(metric,start,end):
                    groups[(end,cur,attr["fxo_id"])][metric].append({
                        "value":val,"tag":name,"filed":str(filed),
                        "start":str(start) if start else None,"fact_id":fact_id,
                        "form":"ESEF","priority":priority,
                        "url":"https://filings.xbrl.org"+attr["report_url"],
                        "source":meta["url"],"sha256":meta["sha256"],
                    })
    return _assemble(groups)

def values(statement):
    return {key:x["value"] for key,x in statement.get("facts",{}).items()}
