"""Conservative annual statement extraction with concept and filing provenance."""
from collections import defaultdict
from datetime import date
import math
import re

# Alias order is policy; consolidated parent/shareholder concepts precede broader fallbacks.
TAGS = {
    "sales": "RevenueFromContractWithCustomerExcludingAssessedTax Revenues SalesRevenueNet RevenueFromContractWithCustomerIncludingAssessedTax Revenue",
    "net": "NetIncomeLossAvailableToCommonStockholdersBasic ProfitLossAttributableToOwnersOfParent NetIncomeLoss ProfitLoss",
    "ebit": "OperatingIncomeLoss ProfitLossFromOperatingActivities",
    "assets": "Assets",
    "liabilities": "Liabilities",
    "book": "StockholdersEquity EquityAttributableToOwnersOfParent",
    "total_equity": "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest Equity",
    "preferred": "PreferredStockCarryingValue PreferredStockValue PreferredStocksIncludingAdditionalPaidInCapital",
    "minority": "MinorityInterest NoncontrollingInterests",
    "cash": "CashAndCashEquivalentsAtCarryingValue CashAndCashEquivalents",
    "st_investments": "ShortTermInvestments ShortTermInvestmentsAvailableForSale",
    "debt_total": "DebtLongtermAndShorttermCombinedAmount DebtAndLeaseObligations Borrowings",
    "debt": "LongTermDebtAndCapitalLeaseObligations LongTermDebt",
    "debt_current": "LongTermDebtAndCapitalLeaseObligationsCurrent LongTermDebtCurrent CurrentPortionOfLongTermBorrowings",
    "debt_noncurrent": "LongTermDebtAndCapitalLeaseObligationsNoncurrent LongTermDebtNoncurrent NoncurrentBorrowings",
    "short_borrow": "ShortTermBorrowings ShortTermDebt CurrentBorrowings",
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
    "div": "PaymentsOfDividendsCommonStock PaymentsOfOrdinaryShareDividends PaymentsOfDividends DividendsPaidClassifiedAsFinancingActivities DividendsPaid",
    "buybacks": "PaymentsForRepurchaseOfCommonStock PaymentsToAcquireOrRedeemEntitysShares",
    "issuance": "ProceedsFromStockPlans ProceedsFromIssuanceOfCommonStock ProceedsFromIssuingShares",
    "debt_net": "ProceedsFromRepaymentsOfDebt",
    "da": "DepreciationDepletionAndAmortization DepreciationAndAmortization DepreciationAmortizationAndAccretionNet DepreciationAndAmortisationExpense DepreciationDepletionAndAmortizationPropertyPlantAndEquipment Depreciation",
    "oci": "OtherComprehensiveIncomeLossNetOfTax OtherComprehensiveIncomeAttributableToOwnersOfParent",
}
STOCK = {"assets","liabilities","book","total_equity","preferred","minority","cash","st_investments","debt","debt_current","debt_noncurrent","short_borrow","debt_total","ar","inventory","ap"}
ANNUAL = {"10-K","10-K/A","20-F","20-F/A","40-F","40-F/A","10-KT"}
ALIASES = {metric: val.split() for metric, val in TAGS.items()}
REVERSE = defaultdict(list)
for metric, tags in ALIASES.items():
    for i, tag in enumerate(tags):
        REVERSE[tag].append((metric,i))

def qualifies(metric, start, end):
    if metric in STOCK:
        return start is None
    return start is not None and 330 <= (end - start).days <= 400

def _assemble(groups, asof):
    """Select one accession and reporting currency per fiscal year, then one coherent period."""
    by_end = defaultdict(list)
    for (end, currency, filing), metrics in groups.items():
        if not ({"net","book"} <= metrics.keys() or {"net","sales"} <= metrics.keys()):
            continue
        by_end[end].append((currency,filing,metrics))
    result = []
    for end, candidates in sorted(by_end.items()):
        # Prefer the current-year filing over later comparative presentations. Within it
        # select the better-covered reporting currency (e.g. TWD over convenience USD).
        def score(c):
            cur, _, fields = c
            pub = max(max(x["filed"] for x in values) for values in fields.values())
            lag = (date.fromisoformat(pub) - end).days
            return (lag <= 240, len(fields), pub, cur)
        cur, filing, metrics = max(candidates, key=score)
        start_count = defaultdict(int)
        for metric in ("sales","net","ebit","cfo","div"):
            for x in metrics.get(metric, []):
                start_count[x["start"]] += 1
        start = max(start_count, key=lambda x:(start_count[x],x)) if start_count else None
        chosen = {}
        conflicts = []
        for metric, items in metrics.items():
            items = [x for x in items if x["start"] is None or x["start"] == start]
            if not items:
                continue
            priority = min(x["priority"] for x in items)
            items = [x for x in items if x["priority"] == priority]
            if len({x["value"] for x in items}) != 1:
                conflicts.append(metric)
                continue
            x = max(items,key=lambda y:(y["filed"], y["tag"], y.get("fact_id",""))).copy()
            x.pop("priority")
            chosen[metric] = x
        if "net" in chosen and ("sales" in chosen or "book" in chosen):
            result.append({"end":str(end),"start":start,"currency":cur,"filing":filing,
                           "facts":chosen,"conflicts":sorted(conflicts)})
    # A 52/53-week filer can shift its fiscal year end; do not count close dates as two years.
    dedup = []
    for item in result:
        if dedup and (date.fromisoformat(item["end"])-date.fromisoformat(dedup[-1]["end"])).days < 290:
            if len(item["facts"]) >= len(dedup[-1]["facts"]):
                dedup[-1] = item
        else:
            dedup.append(item)
    return dedup[-10:]

def from_sec(payload, meta, asof, cik):
    if int(payload["cik"]) != cik:
        raise ValueError("SEC payload CIK mismatch")
    groups = defaultdict(lambda:defaultdict(list))
    for ns in ("us-gaap","ifrs-full"):
        for tag, series in payload["facts"].get(ns, {}).items():
            if tag not in REVERSE:
                continue
            for cur, records in series["units"].items():
                if not re.fullmatch("[A-Z]{3}", cur):
                    continue
                for x in records:
                    if x.get("form") not in ANNUAL | {"S-1","S-1/A","F-1","F-1/A","424B4"}:
                        continue
                    if not x.get("filed") or not x.get("accn"):
                        continue
                    end = date.fromisoformat(x["end"])
                    filed = date.fromisoformat(x["filed"])
                    if not 0 <= (asof-end).days <= 4400 or not end <= filed <= asof:
                        continue
                    start = date.fromisoformat(x["start"]) if x.get("start") else None
                    for metric, priority in REVERSE[tag]:
                        if not qualifies(metric,start,end) or not math.isfinite(x["val"]):
                            continue
                        a = x["accn"]
                        groups[(end,cur,a)][metric].append({
                            "value":x["val"],"tag":ns+":"+tag,"filed":str(filed),
                            "start":str(start) if start else None,"accession":a,
                            "form":x["form"],"priority":priority,
                            "url":f"https://www.sec.gov/Archives/edgar/data/{cik}/{a.replace('-','')}/{a}-index.htm",
                            "source":meta["url"],"sha256":meta["sha256"],
                        })
    return _assemble(groups, asof)

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
    return _assemble(groups, asof)

def values(statement):
    return {key:x["value"] for key,x in statement.get("facts",{}).items()}
