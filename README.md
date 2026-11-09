# Equity Atlas

Equity Atlas is a company screener with a deterministic CFA valuation engine. It separates the company universe, reported facts, model suitability, estimates, and the evidence behind each result. A blocked model carries a reason.

- **Public:** [Equity Atlas on GitHub Pages](https://austinmermans.github.io/equity-atlas/) shows official Taiwan exchange closes, capitalization estimates and exchange multiples for 50 issuers alongside SEC filings for 170 issuers. The scheduled build obtains its inputs directly from official sources. Optional local imports stay in the browser.
- **Local:** The valuation edition includes market capitalization, reported ratios, model decisions, scenario ranges, and a cycle view. It runs with Python 3.11+ and has no runtime packages.

The public build checks each issuer's latest annual period against SEC submissions. When Company Facts lacks that period, it tries the SEC XBRL instance first. For reviewed accessions, it can then download the issuer's copy of the same 20-F and extract its consolidated statement tables using Poppler's `pdftotext`. The screener shows direct SEC and issuer-copy coverage separately and links both filing records and downloaded source documents. A new accession needs a reviewed table profile. Extraction errors retain earlier available filings and appear in the issuer's data gaps.

```sh
export ATLAS_SEC_USER_AGENT='Equity Atlas your-contact@example.com'
python3 -m equity_atlas --limit 100 --out data/pilot
python3 -m equity_atlas --limit 250 --out data/expanded
python3 -m http.server 8764 --bind 127.0.0.1 --directory data/expanded
```

Open http://127.0.0.1:8764, or use **Open snapshot** at the Pages site and select `data/expanded/snapshot.json`. For a local file-only launch, open `data/expanded/index.html` and select the snapshot manually. `--offline` reuses the most recent cached source files; it does not advance the market snapshot date. `--ranking PATH` accepts a data export with `Rank,Name,Symbol,marketcap,country` columns, sorted by USD full issuer capitalization; file modification time is treated as the capture time. One row per issuer is required, with a listing-qualified symbol for non-US companies and one cap across economically equivalent classes. The default CompaniesMarketCap download is a delayed provider snapshot for local research. Its values and results computed from them are kept out of Git and Pages. Use a feed that grants the necessary rights before redistributing market data.

```sh
python3 -m unittest discover -s tests -v
python3 -m equity_atlas --public public-issuers.csv --open-market --out data/public-site
python3 scripts/verify_public.py data/public-site/snapshot.json
```

The public workflow runs weekdays at 10:23 UTC and supports a manual refresh. A build that falls below 80% recent annual coverage fails before deployment. The public view carries the build date, quote date, and filing periods independently. For a scheduled local market run, use `scripts/refresh-market.sh` with the same SEC user agent, optionally `ATLAS_LIMIT` and `ATLAS_RANKING`. It preserves dated run outputs and updates `data/latest` only on success. Set the working directory and interpreter path explicitly in any external scheduler.

See [methodology](docs/methodology.md), [source and scaling notes](docs/pipeline.md), and the [pilot review](docs/pilot-review.md).
