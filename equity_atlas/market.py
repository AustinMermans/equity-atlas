"""Licensed public data from Taiwan's exchange and central bank."""
from datetime import date, timedelta
import math
import re

TWSE_CLOSE = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TWSE_DAILY_QUOTES = "https://www.twse.com.tw/rwd/en/afterTrading/MI_INDEX?date={}&type=ALLBUT0999&response=json"
TWSE_ISSUERS = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TWSE_MULTIPLES = "https://www.twse.com.tw/rwd/en/afterTrading/BWIBBU_d?date={}&selectType=ALL&response=json"
CBC_FX = "https://www.cbc.gov.tw/en/lp-700-2-1-40.html"
OPEN_LICENSE = "https://data.gov.tw/en/license"
DATASETS = {
    "close": "https://data.gov.tw/en/datasets/11549",
    "shares": "https://data.gov.tw/en/datasets/18419",
    "multiples": "https://data.gov.tw/dataset/11764",
    "fx": "https://www.cbc.gov.tw/en/cp-510-1865-DA249-2.html",
}
SHARES = "已發行普通股數或TDR原股發行股數"


def taiwan_date(text):
    if not re.fullmatch(r"\d{7}", text):
        raise ValueError(f"Unexpected Taiwan exchange date: {text!r}")
    return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:]))


def number(value):
    try:
        x = float(str(value).replace(",", ""))
        return x if math.isfinite(x) else None
    except ValueError:
        return None


def taiwan_issuers(quotes, registry, day, limit):
    """Match security and issuer by exchange code, then rank common equity estimates."""
    quote_day = max(taiwan_date(row["Date"]) for row in quotes)
    if not 0 <= (day - quote_day).days <= 7:
        raise ValueError(f"Taiwan exchange closing prices out of date: {quote_day}")
    issuers = {}
    for row in registry:
        code = row["公司代號"]
        if code in issuers:
            raise ValueError(f"Duplicate Taiwan issuer code: {code}")
        issuers[code] = row
    prices = {}
    for row in quotes:
        code = row["Code"]
        if taiwan_date(row["Date"]) != quote_day or not re.fullmatch(r"[1-9]\d{3}", code):
            continue
        if code in prices:
            raise ValueError(f"Duplicate Taiwan closing price: {code}")
        prices[code] = row
    rows = []
    for code, quote in prices.items():
        issuer = issuers.get(code)
        if not issuer:
            continue
        shares_day = taiwan_date(issuer["出表日期"])
        if shares_day > day or not -4 <= (quote_day - shares_day).days <= 45:
            continue
        close = number(quote["ClosingPrice"])
        shares = issuer[SHARES].replace(",", "")
        if not close or close <= 0 or not shares.isdigit() or int(shares) <= 0:
            continue
        rows.append({"exchange": "XTAI", "code": code, "currency": "TWD", "date": str(quote_day),
                     "close": close, "issued_shares": int(shares), "shares_date": str(shares_day),
                     "estimated_cap_twd": close * int(shares),
                     "name": issuer["英文簡稱"].strip() or issuer["公司名稱"],
                     "local_name": issuer["公司名稱"]})
    rows.sort(key=lambda row: (-row["estimated_cap_twd"], row["code"]))
    rows = rows[:limit]
    if len(rows) != limit:
        raise ValueError(f"Taiwan feed has {len(rows)} usable issuers; expected {limit}")
    return quote_day, rows


def dated_quotes(report, day):
    label = day.strftime("%Y/%m/%d") + " Daily Quotes(All(no Warrant & CBBC & OCBBC))"
    if report["stat"] != "OK" or report["date"] != day.strftime("%Y%m%d"):
        raise ValueError("Exchange daily quote report date mismatch")
    tables = [table for table in report["tables"] if table.get("title") == label]
    if len(tables) != 1:
        raise ValueError("No unique daily quote table in the exchange report")
    table = tables[0]
    fields = table["fields"]
    if fields.count("Security Code") != 1 or fields.count("Closing Price") != 1:
        raise ValueError("Unexpected exchange daily quote columns")
    code, price = fields.index("Security Code"), fields.index("Closing Price")
    roc_day = f"{day.year - 1911:03d}{day:%m%d}"
    return [{"Date": roc_day, "Code": row[code], "ClosingPrice": row[price]} for row in table["data"]]


def load_taiwan(cache, day, limit=50):
    registry, shares_meta = cache.json(TWSE_ISSUERS, 12)
    issues = []
    try:
        quotes, close_meta = cache.json(TWSE_CLOSE, 4)
        quote_day, rows = taiwan_issuers(quotes, registry, day, limit)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issues.append(f"TWSE OpenAPI closing prices: {exc}")
        for days_ago in range(8):
            session = day - timedelta(days=days_ago)
            try:
                report, close_meta = cache.json(TWSE_DAILY_QUOTES.format(session.strftime("%Y%m%d")), 24)
                quote_day, rows = taiwan_issuers(dated_quotes(report, session), registry, day, limit)
                break
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                continue
        else:
            raise ValueError("No usable official Taiwan closing prices in the last seven days") from exc
    receipts = {"close": close_meta, "shares": shares_meta}
    try:
        report, receipts["multiples"] = cache.json(TWSE_MULTIPLES.format(quote_day.strftime("%Y%m%d")), 24)
        if report["stat"] != "OK" or report["date"] != quote_day.strftime("%Y%m%d"):
            raise ValueError("Exchange valuation report date mismatch")
        fields = report["fields"]
        mapped = {entry["Security Code"]: entry for entry in (dict(zip(fields, line)) for line in report["data"])}
        for row in rows:
            item = mapped.get(row["code"])
            if not item or number(item["Closing Price"]) != row["close"]:
                continue
            row["exchange_multiples"] = {
                "P/E": number(item["P/E ratio"]), "P/B": number(item["P/B ratio"]),
                "dividend_yield_pct": number(item["Dividend yield (%)"]),
                "period": item["Fiscal year / quarter"],
            }
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issues.append(f"TWSE multiples: {exc}")
    fx = None
    try:
        raw, receipts["fx"] = cache.get(CBC_FX, 4)
        html = raw.decode("utf-8")
        pattern = r'<td data-th="Date">\s*<span>([0-9/]+)</span>\s*</td>\s*<td data-th="NTD/USD">\s*<span>([0-9.]+)</span>\s*</td>'
        rates = dict(re.findall(pattern, html))
        rate = number(rates.get(quote_day.strftime("%Y/%m/%d")))
        if rate and 15 <= rate <= 60:
            fx = {"date": str(quote_day), "rate": rate, "source": receipts["fx"]}
        if not fx:
            raise ValueError(f"No official USD/TWD closing rate for {quote_day}")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        issues.append(f"CBC FX: {exc}")
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        if fx:
            row["estimated_cap_usd"] = row["estimated_cap_twd"] / fx["rate"]
    return rows, {"exchange": "Taiwan Stock Exchange", "date": str(quote_day),
                  "license": OPEN_LICENSE, "datasets": DATASETS, "receipts": receipts,
                  "fx": fx, "issues": issues}
