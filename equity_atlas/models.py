"""CFA valuation primitives and deterministic, evidence-gated screen."""
from datetime import date
from statistics import median
from .facts import balance_check, temporary_equity_fields, values

VERSION = "2026.11-v2"
FINANCIAL = {"bank","insurer","broker"}
CYCLE = {"commodity","cyclical"}
CORE = {"operating","cyclical","commodity","utility"}
RATES = { # nominal USD scenario hurdle, not an estimated security beta
    "bank":(.105,None), "broker":(.115,None), "insurer":(.105,None),
    "commodity":(.12,.10), "cyclical":(.115,.095), "utility":(.085,.07),
    "operating":(.105,.085), "holdco":(.11,None), "reit":(.10,None),
    "unknown":(None,None),
}
NAMES = {
    "assets":"Adjusted NAV", "comps":"Peer implied equity", "pe_ggm":"Justified forward P/E",
    "pb_ggm":"Justified P/B", "ri_single":"Single-stage residual income",
    "ri_multi":"Multistage residual income", "ddm":"Multistage dividend discount",
    "ddm_ggm":"Gordon dividend discount", "fcff":"FCFF", "fcfe":"FCFE",
}
PRIORITY = {
    "bank":["ri_multi","pb_ggm","comps","ddm","ri_single","ddm_ggm","pe_ggm","assets"],
    "broker":["ri_multi","comps","pb_ggm","ddm","ri_single","ddm_ggm","pe_ggm","assets"],
    "insurer":["ri_multi","pb_ggm","comps","ddm","ri_single","ddm_ggm","pe_ggm","assets"],
    "utility":["ddm","ddm_ggm","fcff","comps","fcfe","pe_ggm"],
    "commodity":["fcff","comps","assets","fcfe"],
    "cyclical":["fcff","comps","fcfe","assets"],
    "operating":["fcff","comps","fcfe","ddm","pe_ggm","ddm_ggm","ri_multi","ri_single","pb_ggm"],
    "holdco":["assets"], "reit":["assets"], "unknown":[],
}
ROIC_TERMINAL = .13
GROWTH_TERMINAL = .025
CYCLE_MIN = 5
STALENESS_DAYS = 465

def perp(flow_next, rate, g):
    if rate <= g or rate <= 0:
        raise ValueError("discount rate must exceed growth")
    return flow_next / (rate-g)

def pv(flows, rate, continuing_at_horizon=0):
    if not flows or rate <= 0:
        raise ValueError("positive discount rate and explicit forecast required")
    return sum(x/(1+rate)**t for t,x in enumerate(flows,1)) + continuing_at_horizon/(1+rate)**len(flows)

def ri_single(book, roe, re, g):
    if not 0 <= g <= roe or book <= 0:
        raise ValueError("positive book and feasible terminal retention required")
    return book + perp(book*(roe-re),re,g)

def ri_multi(book, roes, retention, re, terminal_roe, g):
    initial = book
    flows = []
    for roe, retain in zip(roes,retention,strict=True):
        if not 0 <= retain <= 1 or book <= 0:
            raise ValueError("positive book and feasible retention required")
        ni = roe * book
        flows.append(ni - re * book)
        book += ni*retain
    return initial + pv(flows,re,ri_single(book,terminal_roe,re,g)-book)

def ddm(dividends, rate, g):
    if not dividends or min(dividends) < 0 or dividends[-1] <= 0:
        raise ValueError("nonnegative dividends and a positive terminal anchor required")
    return pv(dividends,rate,perp(dividends[-1]*(1+g),rate,g))

def fcff_value(flows, wacc, terminal_nopat, roic, g, bridge):
    if not 0 <= g < roic or terminal_nopat <= 0:
        raise ValueError("positive terminal NOPAT and funded growth required")
    return pv(flows,wacc,perp(terminal_nopat*(1-g/roic),wacc,g)) + bridge

def fcfe_value(flows, re, terminal_net, roe, g):
    if not 0 <= g < roe or terminal_net <= 0:
        raise ValueError("positive terminal common income and funded growth required")
    return pv(flows,re,perp(terminal_net*(1-g/roe),re,g))

def consecutive(history, currency):
    result = []
    for row in reversed(history):
        if row["currency"] != currency:
            break
        if result:
            days=(date.fromisoformat(result[-1]["end"])-date.fromisoformat(row["end"])).days
            if not 320 <= days <= 410:
                break
        result.append(row)
    return list(reversed(result))

def quantile(seq, p):
    s=sorted(seq)
    i=(len(s)-1)*p
    lo=int(i)
    return s[lo]+(s[min(lo+1,len(s)-1)]-s[lo])*(i-lo)

def comparable_sales_history(history):
    """Keep the latest contiguous history with the same sales definition."""
    if not history:
        return history
    basis=history[-1].get("sales_basis")
    for index in range(len(history)-2,-1,-1):
        if history[index].get("sales_basis") != basis:
            return history[index+1:]
    return history


def cycle_read(history, kind):
    if kind not in CYCLE:
        return {"phase":"not classified cyclical"}
    margins=[]
    for row in reversed(comparable_sales_history(history)):
        v=values(row)
        if "ebit" not in v or v.get("sales",0)<=0:
            break
        margins.append((row["end"],v["ebit"]/v["sales"]))
    margins.reverse()
    # Compare latest against the preceding completed years; the reference cannot contain the observation.
    if len(margins)<CYCLE_MIN+1:
        return {"phase":"insufficient cycle history", "years":len(margins)}
    actual=margins[-1][1]
    sample=[m for _,m in margins[:-1]]
    low,mid,high=quantile(sample,.25),median(sample),quantile(sample,.75)
    phase="above historical range" if actual>high else "below historical range" if actual<low else "within historical range"
    return {"phase":phase,"years":len(sample),"window":[margins[0][0],margins[-2][0]],
            "actual_margin":actual,"low_margin":low,"mid_margin":mid,"high_margin":high}

def debt_amount(v):
    if "debt_total" in v:
        return v["debt_total"]
    if {"debt_current_total","debt_noncurrent"} <= v.keys():
        return v["debt_current_total"] + v["debt_noncurrent"]
    debt=v.get("debt")
    if debt is None and {"debt_current","debt_noncurrent"} <= v.keys():
        debt=v["debt_current"]+v["debt_noncurrent"]
    return debt+v.get("short_borrow",0) if debt is not None else None

def common_book(v):
    if "common_book" in v:
        return v["common_book"]
    return v["book"] - v.get("preferred",0) if "book" in v else None

def common_earnings(v, tag):
    if "net_common" in v:
        return v["net_common"]
    if {"net_parent","preferred_earnings_adjustment"} <= v.keys():
        return v["net_parent"] - v["preferred_earnings_adjustment"]
    if tag in {"ifrs-full:ProfitLoss","us-gaap:ProfitLoss","issuer:consolidated:net"}:
        return None
    if v.get("preferred",0)>0 and "AvailableToCommon" not in tag:
        return None
    return v.get("net")

def common_dividends(statement):
    v=values(statement)
    fact=statement["facts"].get("div",{})
    if fact.get("tag","").split(":")[-1] in {"PaymentsOfDividendsCommonStock","PaymentsOfOrdinaryShareDividends"}:
        return v["div"]
    minority=v.get("minority",v.get("total_equity",0)-v.get("book",0) if "total_equity" in v else 0)
    if minority>0:
        return None
    if v.get("preferred",0)>0:
        if {"div_total","div_preferred_paid"} <= v.keys() and v["div_total"] >= v["div_preferred_paid"]:
            return v["div_total"] - v["div_preferred_paid"]
        return None
    return v.get("div")

def observed(case):
    """Raw ratios in issuer dollars. No division by missing/nonpositive fundamentals."""
    v=case["latest"]
    fx=case["fx"]
    market=case["market_cap_usd"]
    if fx is None or not case["fresh"]:
        return {},None
    equity=market*fx
    book=common_book(v)
    net=common_earnings(v,case["net_tag"])
    # No silent zero for debt or cash. Equity delta can measure NCI when both are disclosed.
    debt=debt_amount(v)
    hybrid=v.get("hybrid_equity",0)
    minority=v.get("minority")
    if minority is None and {"book","total_equity"} <= v.keys():
        minority=max(0,v["total_equity"]-v["book"]-hybrid)
    # Separately presented claims enter the enterprise-to-common bridge at carrying value.
    temporary=sum(v[k] for k in temporary_equity_fields(v))
    claims=(minority or 0)+v.get("preferred",0)+hybrid+temporary
    bridge=None
    if not case.get("ev_exclusion") and case["kind"] in CORE and debt is not None and debt>=0 and v.get("cash",-1)>=0:
        bridge=v["cash"]+v.get("st_investments",0)-debt-claims
    ev=equity-bridge if bridge is not None else None
    ratios={}
    for metric,numerator,den in [
        ("P/E",equity,net),("P/B",equity,book),("EV/Sales",ev,v.get("sales")),
        ("EV/EBIT",ev,v.get("ebit")),("EV/Midcycle EBIT",ev,(case["cycle"].get("mid_margin") or 0)*v.get("sales",0)),
    ]:
        if numerator is not None and numerator>0 and den is not None and den>0:
            ratios[metric]={"multiple":numerator/den,"denominator":den}
    return ratios,bridge

def prepare(issuer, history, fx, day):
    stmt=history[-1] if history else None
    curr=stmt["currency"] if stmt else None
    h=consecutive(history,curr)
    v=values(stmt) if stmt else {}
    audit=issuer.get("edgar",{})
    expected=audit.get("latest_annual")
    annual_gap=None
    if stmt and expected and stmt["end"] < expected["end"]:
        annual_gap=f"The latest filed fiscal year ({expected['end']}) is unavailable."
    elif stmt and expected and audit.get("annual_route")=="amendment_pending" and stmt["end"]==expected["end"]:
        annual_gap="A same-period amended annual filing still needs review."
    fresh=bool(stmt and not annual_gap and 0 <= (day-date.fromisoformat(stmt["end"])).days <= STALENESS_DAYS)
    rates=fx.get(curr)
    ev_exclusion=issuer.get("ev_exclusion")
    balance=balance_check(stmt) if stmt else None
    if balance and not ev_exclusion:
        tolerance=max(1_000_000,abs(v["assets"])*.0001)
        if max(abs(balance["unexplained_residual"]),abs(balance.get("unexplained_equity_attribution",0))) > tolerance:
            ev_exclusion="The filed balance sheet has an unresolved material claim."
    case={**issuer,"statement":stmt,"history":h,"latest":v,"fresh":fresh,
          "annual_gap":annual_gap,"ev_exclusion":ev_exclusion,
          "fx":rates["rate"] if rates else None,"fx_observation":rates,
          "cycle":cycle_read(h,issuer["kind"]),
          "net_tag":(stmt or {}).get("facts",{}).get("net",{}).get("tag","")}
    ratios,bridge=observed(case)
    case.update(ratios=ratios,bridge=bridge)
    return case

def comparable_profiles(target, candidate):
    kind=target["kind"]
    a,b=target["latest"],candidate["latest"]
    if kind in FINANCIAL:
        if all(r.get("book",0)>0 and "net" in r for r in (a,b)):
            return abs(a["net"]/a["book"]-b["net"]/b["book"]) <= .06
        return True
    if a.get("sales",0)>0 and b.get("sales",0)>0 and target["fx"] and candidate["fx"]:
        scale=(a["sales"]/target["fx"])/(b["sales"]/candidate["fx"])
        if not .1<=scale<=10:
            return False
        if "ebit" in a and "ebit" in b:
            ma=(target["cycle"].get("mid_margin",a["ebit"]/a["sales"]))
            mb=(candidate["cycle"].get("mid_margin",b["ebit"]/b["sales"]))
            if abs(ma-mb)>max(.15,.50*abs(ma)):
                return False
    return True

def clean_surplus(history):
    checks=[]
    recent=history[-4:]
    for before,after in zip(recent,recent[1:]):
        a,b=values(before),values(after)
        start,end=common_book(a),common_book(b)
        net=common_earnings(b,after["facts"].get("net",{}).get("tag",""))
        dividend=common_dividends(after)
        if start is None or start<=0 or end is None or net is None or dividend is None:
            continue
        expected=start+net-dividend+b.get("issuance",0)-b.get("buybacks",0)
        checks.append((end-expected)/start)
    return checks

def fit(case, peers, override=None):
    override=override or {}
    v,h,k,c=case["latest"],case["history"],case["kind"],case["cycle"]
    fx=case["fx"]
    market=case["market_cap_usd"]
    re,wacc=RATES[k]
    g=GROWTH_TERMINAL
    results={}
    def block(method, reason, status="blocked"):
        results[method]={"method":method,"label":NAMES[method],"status":status,"reason":reason}
    def calc(method, function, inputs, reason, has_rate=True):
        try:
            mid=function(0.0,0.0)
            seq=[function(d,gg) for d in (-.015,0,.015) for gg in (-.005,0,.005)] if has_rate else [mid]
            if not all(-float("inf")<x<float("inf") for x in seq):
                raise ValueError("nonfinite result")
            if mid <= 0:
                raise ValueError("nonpositive common equity; inspect distress and terminal assumptions")
        except (ValueError,ZeroDivisionError,OverflowError) as exc:
            return block(method,str(exc))
        results[method]={"method":method,"label":NAMES[method],"status":"estimated","reason":reason,
                         "equity_usd":mid/fx,"low_usd":min(seq)/fx,"high_usd":max(seq)/fx,
                         "gap":mid/(fx*market)-1,"inputs":inputs}
    nav=override.get("nav")
    nav_day=date.fromisoformat(nav["period"]) if nav else None
    if (nav and nav.get("source","").startswith("https://") and nav_day and
        0 <= (date.fromisoformat(case["as_of"])-nav_day).days <= 75 and
        nav["period"] <= nav.get("published","9999") <= case["as_of"]):
        nav_fx=1 if nav.get("currency")=="USD" else fx if case["statement"] and nav.get("currency")==case["statement"]["currency"] else None
        if nav_fx:
            value=(nav["fair_value_assets"]-nav["all_senior_claims"])/nav_fx
            if 0<value<float("inf"):
                results["assets"]={"method":"assets","label":NAMES["assets"],"status":"estimated",
                    "reason":"Fair-value assets less senior claims. Holdings and valuation timestamp are independent of statement freshness.",
                    "equity_usd":value,"low_usd":value,"high_usd":value,"gap":value/market-1,"inputs":nav}
    for method in NAMES:
        if method in results:
            continue
        if method=="assets":
            block(method,"Needs reviewed fair-value assets and senior claims dated within 75 days; book is not adjusted NAV.")
        elif method not in PRIORITY[k]:
            block(method,"Method outside this business archetype’s default model set.","not_applicable")
        elif not case["statement"]:
            block(method,"No coherent annual statement available.")
        elif case.get("annual_gap"):
            block(method,case["annual_gap"])
        elif not case["fresh"]:
            block(method,"Annual statement older than policy window.")
        elif fx is None:
            block(method,"No usable as-of conversion to USD.")
    if len(results)==len(NAMES):
        return finish(case, results)
    net=common_earnings(v,case["net_tag"])
    book=common_book(v) or 0
    reported_net=v.get("net")
    earnings_state=("loss" if reported_net is not None and reported_net<0 else
                    "unknown common earnings" if net is None else "profit" if net>0 else "break-even")
    case["earnings_state"]=earnings_state
    sales=v.get("sales",0)
    income_margin=net/sales if net is not None and sales>0 else None
    hist=[values(x) for x in h]
    sales_hist=[values(x) for x in comparable_sales_history(h)]
    recent=sales_hist[-5:]
    growth=[b["sales"]/a["sales"]-1 for a,b in zip(recent,recent[1:]) if a.get("sales",0)>0 and b.get("sales",0)>0]
    short_growth=max(-.05,min(.12,median(growth))) if len(growth)>=2 else g
    case["growth_state"]="high historical growth" if len(growth)>=2 and median(growth)>.12 else "ordinary or insufficient history"
    if "comps" not in results:
        order=(["P/B","P/E"] if k in FINANCIAL else
               ["EV/Midcycle EBIT","EV/Sales"] if k in CYCLE else
               ["P/E","EV/EBIT","EV/Sales"] if net is not None and net>0 else ["EV/EBIT","EV/Sales"])
        used=False
        for ratio in order:
            target=case["ratios"].get(ratio)
            if not target or (k in CYCLE and c.get("mid_margin",0)<=0):
                continue
            members=[p for p in peers if p["id"]!=case["id"] and p["peer_group"]==case["peer_group"]
                     and p["kind"]==k and p["peer_group"]!="unclassified" and ratio in p["ratios"]
                     and p["accounting"]==case["accounting"] and comparable_profiles(case,p)
                     and abs((date.fromisoformat(p["statement"]["end"])-date.fromisoformat(case["statement"]["end"])).days)<=180]
            if len(members)<3:
                continue
            benchmarks=[p["ratios"][ratio]["multiple"] for p in members]
            mult=median(benchmarks)
            bridge=case["bridge"] if ratio.startswith("EV/") else 0
            calc("comps",lambda d,x: mult*target["denominator"]+bridge,
                 {"multiple":ratio,"peer_median":mult,"peer_count":len(members),"peer_ids":[p["id"] for p in members],
                  "target_denominator":target["denominator"],"bridge":bridge},
                 "Leave-one-out median after business, accounting, size and profitability checks. No growth adjustment.",False)
            if results["comps"]["status"]=="estimated":
                results["comps"]["low_usd"]=(quantile(benchmarks,.25)*target["denominator"]+bridge)/fx
                results["comps"]["high_usd"]=(quantile(benchmarks,.75)*target["denominator"]+bridge)/fx
            used=True
            break
        if not used:
            block("comps","Requires a usable denominator and ≥3 same-group peers with compatible accounting, period, size and profitability.")
    checks=clean_surplus(h)
    case["book_rollforward_residuals"]=checks
    books=[common_book(x) for x in hist]
    earnings=[common_earnings(x, row["facts"].get("net",{}).get("tag","")) for x,row in zip(hist,h)]
    roes=[income/start for start,income in zip(books,earnings[1:]) if start and start>0 and income is not None]
    roe=median(roes[-5:]) if len(roes)>=3 else None
    terminal_roe=max(.07,min(.20,roe)) if roe is not None else None
    for method in ("ri_single","ri_multi","pb_ggm"):
        if method in results:
            continue
        if book<=0 or terminal_roe is None or roe<=0:
            block(method,"Needs positive common book and ≥3 transitions to a defensible long-run ROE.")
        elif len(checks)<2 or max(map(abs,checks))>.05:
            block(method,"Unexplained book roll-forward exceeds 5% or fewer than two transitions can be checked.")
        elif method in ("ri_single","pb_ggm") and (net is None or net<=0 or case["growth_state"]=="high historical growth"):
            block(method,"Constant growth needs sustainable positive earnings; use a recovery or transition model.")
        elif method in ("ri_single","pb_ggm"):
            calc(method,lambda d,x:ri_single(book,terminal_roe,re+d,g+x),
                 {"book":book,"roe":terminal_roe,"re":re,"g":g,
                  "justified_p_b":(terminal_roe-g)/(re-g),"market_implied_roe":g+(re-g)*market*fx/book},
                 "Same clean-surplus economics for justified P/B and single-stage RI.")
        else:
            prev=books[-2] or 0
            current=net/prev if net is not None and prev>0 else roe
            if not -.5<=current<=.5:
                block(method,"Current ROE outside calibrated range; needs a company-specific transition.")
                continue
            path=[current+(terminal_roe-current)*i/5 for i in range(1,6)]
            calc(method,lambda d,x:ri_multi(book,path,[min(.8,(g+x)/terminal_roe)]*5,re+d,terminal_roe,g+x),
                 {"book":book,"roe_path":path,"terminal_roe":terminal_roe,"re":re,"g":g},
                 "Five-year fade in ROE with funded terminal growth; common equity basis.")
    dividends=[common_dividends(row) for row in h[-5:]]
    dividend=dividends[-1] if dividends else None
    stable=len(dividends)>=4 and all(x is not None and x>0 for x in dividends) and all(b>=.8*a for a,b in zip(dividends,dividends[1:]))
    payout=dividend/net if dividend is not None and net is not None and net>0 else None
    case["dividend_state"]="stable payer" if stable else ("reported payout; unstable or short history" if dividend else ("no reported cash dividend" if dividend==0 else "dividend evidence unavailable"))
    for method in ("ddm","ddm_ggm","pe_ggm"):
        if method in results:
            continue
        if not stable or payout is None or not .10<=payout<=.90:
            block(method,"Needs 4+ regular dividends, positive common earnings, and a sustainable 10–90% payout.")
        elif method!="ddm" and (case["growth_state"]=="high historical growth" or
                (v.get("buybacks",0)>dividend)):
            block(method,"Rapid growth or repurchase-heavy distribution makes stable dividend payout unsuitable.")
        elif method=="ddm" and v.get("buybacks",0)>2*dividend:
            block(method,"Repurchases dominate distributions; dividend cash flows omit material capital returns.")
        elif method=="ddm":
            path=[dividend]
            for i in range(1,6):
                path.append(path[-1]*(1+short_growth+(g-short_growth)*i/5))
            calc(method,lambda d,x:ddm(path[1:],re+d,g+x),
                 {"d0":path[0],"dividend_path":path[1:],"payout":payout,"re":re,"g":g},
                 "Five-year transition from capped historical sales growth to terminal dividend growth.")
        else:
            calc(method,lambda d,x:perp(dividend*(1+g+x),re+d,g+x),
                 {"dividends":dividend,"forward_earnings":net*(1+g),"payout":payout,"re":re,"g":g,
                  "justified_forward_pe":payout/(re-g),
                  "market_implied_dividend_growth":(market*fx*re-dividend)/(market*fx+dividend)},
                 "Gordon economics: justified forward P/E equals payout divided by (required return − growth).")
    if "fcff" not in results:
        bridge=case["bridge"]
        if bridge is None or sales<=0 or "ebit" not in v or "capex" not in v or "da" not in v or v.get("capex",-1)<0:
            block("fcff",case.get("ev_exclusion") or case["statement"].get("operating_profit_gap") or
                  case["statement"].get("depreciation_gap") or
                  "Needs operating profit, sales, D&A, capex and a sourced cash/debt bridge.")
        elif k in CYCLE and (not c.get("mid_margin") or c["mid_margin"]<=0):
            block("fcff","Cyclical baseline needs a positive midcycle margin from ≥5 preceding comparable years.")
        elif k not in CYCLE and v["ebit"]<=0:
            block("fcff","Negative operating profit without a reviewed path to positive cash flow.")
        else:
            actual=v["ebit"]/sales
            end_margin=c.get("mid_margin",actual)
            target_margins=[c.get("low_margin",end_margin),end_margin,c.get("high_margin",end_margin)]
            taxes=[x["tax"]/x["pretax"] for x in hist[-4:] if x.get("pretax",0)>0 and 0<=x.get("tax",-1)<=.60*x["pretax"]]
            tax=median(taxes) if len(taxes)>=2 else .25
            nwcs=[(x["ar"]+x["inventory"]-x["ap"])/x["sales"] for x in sales_hist[-4:]
                  if x.get("sales",0)>0 and {"ar","inventory","ap"}<=x.keys()]
            nwc_sales=max(-.30,min(.40,median(nwcs))) if len(nwcs)>=2 else .05
            da_sales=v["da"]/sales
            capex_sales=v["capex"]/sales
            if not 0<=da_sales<=.5 or not 0<=capex_sales<=.5:
                block("fcff","Reported investment ratios outside operating model calibration.")
            else:
                def scenario(d,x,target):
                    rev=sales
                    flows=[]
                    for i in range(1,6):
                        gg=short_growth+(g+x-short_growth)*i/5
                        nxt=rev*(1+gg)
                        margin=actual+(target-actual)*i/5
                        nopat=nxt*margin*(1-tax)
                        flows.append(nopat+nxt*(da_sales-capex_sales)-nwc_sales*(nxt-rev))
                        rev=nxt
                    return fcff_value(flows,wacc+d,rev*(1+g+x)*target*(1-tax),ROIC_TERMINAL,g+x,bridge)
                calc("fcff",lambda d,x:scenario(d,x,end_margin),
                     {"sales":sales,"ebit_margin":actual,"target_margin":end_margin,"growth_start":short_growth,
                      "wacc":wacc,"g":g,"terminal_roic":ROIC_TERMINAL,"tax":tax,"da_sales":da_sales,
                      "capex_sales":capex_sales,"nwc_sales_proxy":nwc_sales,"bridge":bridge,
                      "tax_basis":"historical effective rates" if len(taxes)>=2 else "policy fallback",
                      "nwc_basis":"historical trade working capital" if len(nwcs)>=2 else "policy fallback"},
                     "Five-year operating forecast with a funded terminal reinvestment rate. Bridge and working capital are screen proxies.")
                if results["fcff"]["status"]=="estimated" and k in CYCLE:
                    cases={}
                    for name,target in zip(("trough","midcycle","strong"),target_margins):
                        if target>0:
                            cases[name]=scenario(0,0,target)/fx
                    results["fcff"]["cycle_cases_usd"]=cases
                    if actual>0:
                        results["fcff"]["reported_margin_case_usd"]=scenario(0,0,actual)/fx
                if results["fcff"]["status"]=="estimated":
                    # At fixed inputs, modeled equity is linear in the terminal margin.
                    e0=scenario(0,0,.01)
                    e1=scenario(0,0,.11)
                    if e1>e0:
                        results["fcff"]["inputs"]["market_implied_terminal_ebit_margin"]=.01+.10*(market*fx-e0)/(e1-e0)
    if "fcfe" not in results:
        fc=override.get("fcfe")
        if (not fc or not fc.get("source") or fc.get("currency")!=case["statement"]["currency"] or
            fc.get("period")!=case["statement"]["end"] or fc.get("published","9999")>case["as_of"]):
            # Require evidence for both directions of debt cash flows or an aggregate.
            def net_debt_cash(row):
                if "debt_net" in row:
                    return row["debt_net"]
                if {"lt_issued","lt_repaid","st_issued","st_repaid"}<=row.keys():
                    return row["lt_issued"]-row["lt_repaid"]+row["st_issued"]-row["st_repaid"]
                if {"lt_issued","lt_repaid"}<=row.keys() and row.get("short_borrow") == 0:
                    return row["lt_issued"]-row["lt_repaid"]
                return None
            basis=sales_hist[-3:]
            borrows=[net_debt_cash(x) for x in basis]
            lev=[debt_amount(x)/x["book"] for x in basis if debt_amount(x) is not None and x.get("book",0)>0]
            if (case["accounting"]!="US GAAP" or k in CYCLE or len(basis)<3 or None in borrows or
                len(lev)<3 or max(lev)-min(lev)>.35 or not 0<=median(lev)<3 or
                net is None or net<=0 or not terminal_roe or terminal_roe<=g or
                not all(x.get("sales",0)>0 and "cfo" in x and x.get("capex",-1)>=0 for x in basis)):
                block("fcfe","Needs complete debt cash flows, stable leverage, a positive earnings anchor and a consistent CFO/interest basis.")
            else:
                flow_margin=median((x["cfo"]-x["capex"]+b)/x["sales"] for x,b in zip(basis,borrows))
                if flow_margin<=0:
                    block("fcfe","Historical financing-adjusted cash flow is nonpositive; forecast recovery explicitly.")
                else:
                    def forecast(d,x):
                        rev=sales
                        flows=[]
                        for i in range(1,6):
                            rev*=1+short_growth+((g+x)-short_growth)*i/5
                            mature_margin=income_margin*(1-(g+x)/terminal_roe)
                            flows.append(rev*(flow_margin+(mature_margin-flow_margin)*i/5))
                        return fcfe_value(flows,re+d,rev*(1+g+x)*income_margin,terminal_roe,g+x)
                    calc("fcfe",forecast,{"fcfe_sales":flow_margin,"leverage":lev,"re":re,
                         "terminal_roe":terminal_roe,"g":g},
                         "Operating cash flow less cash investment plus reported net borrowing; fades to sustainable equity reinvestment.")
        else:
            calc("fcfe",lambda d,x:fcfe_value(fc["flows"],re+d,fc["terminal_net"],fc["terminal_roe"],g+x),
                 {**fc,"re":re,"g":g},"Explicit source-linked cash flows after financing, discounted at the cost of equity.")
    return finish(case, results)

def finish(case,results):
    preferred=PRIORITY[case["kind"]]
    # DDM is a cross-check for ordinary operating businesses; it omits retained capital
    # that management may eventually distribute. RI and comps can be displayed separately.
    lead=[m for m in preferred if case["kind"]!="operating" or m not in {"ddm","ddm_ggm","pe_ggm"}]
    selected=next((m for m in lead if results[m]["status"]=="estimated"),None)
    return {"preferred":preferred[0] if preferred else None,"selected":selected,
            "decisions":list(results.values())}
