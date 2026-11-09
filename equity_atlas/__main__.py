import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from .fetch import Cache
from .pipeline import run, make_public

def main():
    p=argparse.ArgumentParser(description="Build a source-linked equity valuation snapshot")
    p.add_argument("--cache",default="data/cache")
    p.add_argument("--filing-cache",help="separate cache for accession-scoped filings and public filing copies")
    p.add_argument("--out",default="data/screener")
    p.add_argument("--offline",action="store_true")
    choice=p.add_mutually_exclusive_group()
    choice.add_argument("--limit",type=int)
    choice.add_argument("--floor",type=float,help="minimum market cap in USD")
    choice.add_argument("--public",metavar="ISSUERS_CSV",help="SEC filings-only site; no rank or quote data")
    p.add_argument("--open-market",action="store_true",help="Add Taiwan exchange data to the public site")
    p.add_argument("--ranking",help="optional local USD market-cap CSV; use source schema in README")
    p.add_argument("--overrides",help="local evidence-linked NAV or FCFE inputs")
    args=p.parse_args()
    cache=Cache(args.cache,args.offline,filing_root=args.filing_cache)
    if args.open_market and not args.public:
        p.error("--open-market requires --public")
    if args.public:
        if args.ranking or args.overrides:
            p.error("Public builds cannot read market rankings or local overrides")
        data=make_public(cache,args.public,args.out,datetime.now(timezone.utc).date(),args.open_market)
    else:
        if (args.limit is not None and args.limit<=0) or (args.floor is not None and args.floor<=0):
            p.error("Limit and floor must be positive")
        data=run(cache,args.out,count=(args.limit or 100) if args.floor is None else None,floor=args.floor,
                 ranking=args.ranking,overrides=json.loads(Path(args.overrides).read_text()) if args.overrides else None)
    print(json.dumps({"output":args.out,"as_of":data["as_of"],**data["stats"]},indent=2))

if __name__=="__main__":
    main()
