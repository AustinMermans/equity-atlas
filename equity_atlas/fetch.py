"""Local cache, rate-limited public sources, and immutable fetch receipts."""
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .rendered_filing import ENDPOINT as RENDERED_FILING_ENDPOINT

RANK = "https://companiesmarketcap.com/?download=csv"
INDEX = "https://www.sec.gov/files/company_tickers.json"
MIRROR = "https://raw.githubusercontent.com/jadchaar/sec-cik-mapper/main/mappings/stocks/ticker_to_cik.json"
SEC = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"
ESEF = "https://filings.xbrl.org"

def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.replace(path)

def dump(path, obj):
    atomic(path, (json.dumps(obj, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())

class Cache:
    def __init__(self, root, offline=False):
        self.root = Path(root)
        self.offline = offline
        self.lock = threading.Lock()
        self.next_sec = 0.0
        self.rendered_lock = threading.Lock()
        self.next_rendered = 0.0
        self.user_agent = os.environ.get("ATLAS_SEC_USER_AGENT", "")
        self.hits = self.downloads = 0

    def get(self, url, ttl_hours=24, *, post_json=None):
        request_key = url.encode()
        if post_json is not None:
            request_key += b"\0POST\0" + post_json
        key = hashlib.sha256(request_key).hexdigest()
        receipt = self.root / (key + ".json")
        if receipt.exists():
            meta = json.loads(receipt.read_text())
            body = self.root / meta["sha256"]
            age = time.time() - dt.datetime.fromisoformat(meta["retrieved_at"]).timestamp()
            if body.is_file() and (self.offline or age < ttl_hours * 3600):
                self.hits += 1
                data = body.read_bytes()
                if hashlib.sha256(data).hexdigest() != meta["sha256"]:
                    raise ValueError("cache checksum mismatch: " + url)
                return data, meta
        if self.offline:
            raise FileNotFoundError("cache miss: " + url)
        sec = url.startswith(("https://www.sec.gov/", "https://data.sec.gov/"))
        if sec and not self.user_agent:
            raise ValueError("Set ATLAS_SEC_USER_AGENT to a project name and contact email")
        for attempt in range(3):
            try:
                if sec:
                    with self.lock:
                        time.sleep(max(0, self.next_sec - time.monotonic()))
                        self.next_sec = time.monotonic() + .28
                if url == RENDERED_FILING_ENDPOINT:
                    with self.rendered_lock:
                        time.sleep(max(0, self.next_rendered - time.monotonic()))
                        self.next_rendered = time.monotonic() + 2.0
                headers = {"User-Agent": self.user_agent if sec else "EquityAtlas/0.1 (private research)"}
                if post_json is not None:
                    headers.update({"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
                with urlopen(Request(url, data=post_json, headers=headers), timeout=18) as response:
                    data = response.read()
                meta = {"url": url, "retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "sha256": hashlib.sha256(data).hexdigest()}
                with self.lock:
                    atomic(self.root / meta["sha256"], data)
                    dump(receipt, meta)
                    self.downloads += 1
                return data, meta
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise
                after = exc.headers.get("Retry-After")
                if after and (not after.isdigit() or int(after) > 20):
                    raise
                time.sleep(int(after) if after else 2 ** attempt)
            except (URLError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)

    def json(self, url, ttl_hours=24):
        data, meta = self.get(url, ttl_hours)
        return json.loads(data), meta

def ticker_map(cache):
    try:
        obj, meta = cache.json(INDEX, 168)
        return {v["ticker"]: int(v["cik_str"]) for v in obj.values()}, meta
    except (OSError, ValueError):
        obj, meta = cache.json(MIRROR, 168)
        return {ticker: int(cik) for ticker, cik in obj.items()}, meta

def parallel(items, operation, workers=6):
    def safe(item):
        try:
            return operation(item), None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return None, str(exc)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(items, pool.map(safe, items), strict=True))

def fx_snapshot(cache, day):
    quotes = "AED,AUD,BRL,CAD,CHF,CNY,DKK,EUR,GBP,HKD,IDR,ILS,INR,JPY,KRW,MXN,NOK,NZD,PLN,SAR,SEK,SGD,THB,TRY,TWD,ZAR"
    query = urlencode({"base":"USD","quotes":quotes,"from":str(day - dt.timedelta(days=7)),"to":str(day)})
    rates, meta = cache.json("https://api.frankfurter.dev/v2/rates?" + query, 168)
    latest = {"USD": {"date": str(day), "rate": 1.0}}
    for r in sorted(rates, key=lambda v:v["date"]):
        if r["base"] == "USD" and 0 <= (day - dt.date.fromisoformat(r["date"])).days <= 5 and r["rate"] > 0:
            latest[r["quote"]] = {"date":r["date"],"rate":r["rate"],"source":meta}
    return latest
