"""Manual policy seed plus SEC SIC fallback. Keys are listing-qualified provider symbols."""
from collections import defaultdict
from urllib.parse import urlencode
from .fetch import ESEF

# A profile is a routing judgment; an industry is a peer shortlist, not a claim of perfect comps.
CLUSTERS = {
    ("bank","deposit banks"):"JPM BAC WFC C RY TD HSBC MUFG CBA.AX 601939.SS 601288.SS 1398.HK 601988.SS",
    ("broker","capital markets"):"MS GS",
    ("bank","card lenders"):"AXP",
    ("insurer","health insurance"):"UNH",
    ("insurer","diversified insurance"):"ALV.DE",
    ("holdco","diversified holdings"):"BRK-B IHC.AE PRX.AS",
    ("commodity","integrated oil"):"2222.SR XOM CVX SHEL 0857.HK TTE RELIANCE.NS",
    ("commodity","diversified mining"):"BHP",
    ("cyclical","memory fabrication"):"MU 005930.KS 000660.KS CXMT 688825.SS",
    ("cyclical","foundries"):"TSM INTC",
    ("cyclical","semiconductor equipment"):"ASML AMAT LRCX",
    ("cyclical","autos"):"TSLA TM",
    ("cyclical","industrial systems"):"CAT SIE.DE GEV",
    ("cyclical","aerospace defense"):"GE RTX",
    ("cyclical","electronics components"):"TXN APH",
    ("cyclical","industrial gases"):"LIN",
    ("operating","fabless semiconductors"):"NVDA AMD AVGO ARM",
    ("operating","consumer hardware"):"AAPL DELL",
    ("operating","enterprise software"):"MSFT ORCL SAP IBM PLTR",
    ("operating","networking hardware"):"ANET CSCO",
    ("operating","cybersecurity"):"PANW CRWD",
    ("operating","digital platforms"):"GOOG META TCEHY",
    ("operating","commerce platforms"):"AMZN BABA SHOP",
    ("operating","space and satellite"):"SPCX",
    ("operating","pharma"):"LLY JNJ ABBV MRK NVS AZN RO.SW AMGN GILD",
    ("operating","life science equipment"):"TMO ABT",
    ("operating","payment networks"):"V MA",
    ("operating","mass merchants"):"WMT COST",
    ("operating","home improvement"):"HD",
    ("operating","packaged beverages"):"KO PEP 600519.SS",
    ("operating","packaged foods"):"NESN.SW",
    ("operating","household products"):"PG OR.PA",
    ("operating","apparel and luxury"):"ITX.MC MC.PA",
    ("operating","tobacco"):"PM",
    ("operating","media"):"NFLX DIS",
    ("operating","restaurants"):"MCD",
    ("operating","telecom carriers"):"VZ 0941.HK",
}
PROFILE = {s:(k,g) for (k,g),symbols in CLUSTERS.items() for s in symbols.split()}
# CIK overrides validated against SEC entity names; delisted ADR histories will normally be stale.
CIKS = {"SPCX":(1181412,"SPACE EXPLORATION"),"0857.HK":(1108329,"PETROCHINA"),"0941.HK":(1117795,"CHINA MOBILE")}
LEIS = {
    "OR.PA":"529900JI1GG6F7RKVI53", "MC.PA":"IOG4E947OATN0KJYSD45",
    "ITX.MC":"549300TTCXZOGZM2EY83", "SIE.DE":"W38RGI023J3WT1HWRP32",
    "ALV.DE":"529900K9B0N5BT694847", "PRX.AS":"635400Z5LQ5F9OLVT688",
}
EXACT_SIC = {
    6021:("bank","deposit banks"),6022:("bank","deposit banks"),6029:("bank","deposit banks"),
    6035:("bank","deposit banks"),6036:("bank","deposit banks"),6081:("bank","deposit banks"),
    6211:("broker","capital markets"), 6221:("broker","capital markets"),
    2834:("operating","pharma"), 2836:("operating","pharma"),
    3571:("operating","consumer hardware"), 3661:("operating","networking hardware"),
    3711:("cyclical","autos"), 3721:("cyclical","aerospace defense"),
    7372:("operating","enterprise software"), 7373:("operating","enterprise software"),
    1311:("commodity","oil and gas production"), 2911:("commodity","refining"),
    5311:("operating","mass merchants"), 5411:("operating","grocery"),
    6512:("reit","real estate operators"), 6798:("reit","listed real estate"),
    6799:("holdco","diversified holdings"), 6141:("bank","consumer lenders"),
    4813:("operating","telecom carriers"), 5812:("operating","restaurants"),
}
def sec_meta(cik):
    return f"https://data.sec.gov/submissions/CIK{cik:010d}.json"

def classify(symbol, sic):
    if symbol in PROFILE:
        return (*PROFILE[symbol],"reviewed issuer profile")
    if sic in EXACT_SIC:
        return (*EXACT_SIC[sic],f"SEC SIC {sic}")
    if not sic or sic==9995:
        return "unknown","unclassified","no usable issuer industry"
    if 6300<=sic<6500:
        return "insurer",f"SIC {sic}",f"SEC SIC {sic}"
    if 6000<=sic<6300 or 6500<=sic<6800:
        return "unknown","unclassified",f"SEC SIC {sic}: financial/real estate classification needs review"
    if 4900<=sic<5000:
        return "utility",f"SIC {sic}",f"SEC SIC {sic}"
    if 1000<=sic<1500:
        return "commodity",f"SIC {sic}",f"SEC SIC {sic}"
    if 3200<=sic<3800 or 4000<=sic<4700:
        return "cyclical",f"SIC {sic}",f"SEC SIC {sic}"
    return "operating",f"SIC {sic}",f"SEC SIC {sic}"

def esef_list(lei):
    return ESEF+"/api/entities/"+lei+"/filings?"+urlencode({"sort":"-period_end","page[size]":12})
