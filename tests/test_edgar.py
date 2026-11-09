from datetime import date
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from equity_atlas.capex import enrich_capex, valid_capex_components
from equity_atlas.catalog import cik_on
from equity_atlas.depreciation import enrich_depreciation
from equity_atlas.fetch import Cache
from equity_atlas.rendered_filing import ENDPOINT
from equity_atlas.operating import enrich_operating
from equity_atlas.edgar import amendment_reviews, annual_from_instance, periods_from_instance
from equity_atlas.facts import balance_check, from_sec, precise_duplicates
from equity_atlas.inline import periods_from_inline
from equity_atlas.issuer_20f import column, linked_report, statement_page
from equity_atlas.market import SHARES, taiwan_issuers
from equity_atlas.models import common_book, common_dividends, common_earnings, debt_amount

DAY = date(2026, 11, 9)
META = {"url": "https://data.sec.gov/api/example", "sha256": "example"}


class EdgarTests(unittest.TestCase):
    def test_depreciation_rule_rolls_forward_after_filing_and_scope_checks(self):
        cik = 1551152
        accession = "0001551152-27-000011"
        path = "https://www.sec.gov/Archives/edgar/data/1551152/000155115227000011"
        report = {"accession": accession, "path": path, "url": path + "/abbv.htm",
                  "end": "2026-12-31", "filed": "2027-02-18", "form": "10-K"}
        table_url = path + "/R29.htm"
        cfo_tag = "us-gaap:NetCashProvidedByUsedInOperatingActivities"
        statement = {"filing": accession, "end": report["end"], "start": "2026-01-01", "period_kind": "annual",
                     "currency": "USD", "facts": {"cfo": {"value": 21_000_000_000, "tag": cfo_tag}}}
        table = {"title": "Consolidated Statements of Cash Flows", "sources": [table_url], "money_scale": 1_000,
                 "currency": "USD", "columns": ["line", "concept", "12 months to " + report["end"]],
                 "rows": [["Depreciation", "us-gaap:Depreciation", 810_000],
                          ["Amortization of intangible assets", "us-gaap:AmortizationOfIntangibleAssets", 7_850_000],
                          ["Net cash from operating activities", cfo_tag, 21_000_000]]}
        result = {"structuredContent": {"company": {"cik": cik}, "period": "annual",
                  "filings": {"rows": [[accession, report["form"], report["filed"], report["end"], path + "/index.htm"]]},
                  "cash_flow": table}, "_meta": {"canlicapital.com/receipt": {"sources": [
                      {"url": table_url, "sha256_16": "a" * 16}]}}}
        class StubCache:
            def get(self, url, ttl, *, post_json):
                return json.dumps({"result": result}).encode(), {"url": url, "sha256": "b" * 64}
        def extract():
            return enrich_depreciation(StubCache(), {"facts": {}}, META, cik, report, statement)["facts"]["da"]
        fact = extract()
        self.assertEqual((fact["value"], fact["table_url"]), (8_660_000_000, table_url))
        table["rows"][1][0] = "Amortization and impairment of intangible assets"
        with self.assertRaisesRegex(ValueError, "Missing or conflicting"):
            extract()
        table["sources"] = [path + "/../R29.htm"]
        with self.assertRaisesRegex(ValueError, "Unverified"):
            extract()

    def test_cash_investment_rule_reuses_the_current_filing_and_requires_every_line(self):
        cik = 8670
        accession = "0000008670-27-000031"
        report = {"accession": accession, "end": "2027-06-30", "filed": "2027-08-05", "form": "10-K",
                  "url": "https://www.sec.gov/Archives/edgar/data/8670/000000867027000031/adp.htm"}
        record = {"accn": accession, "start": "2026-07-01", "end": report["end"],
                  "filed": report["filed"], "form": report["form"]}
        statement = {"filing": accession, "start": record["start"], "end": report["end"],
                     "period_kind": "annual", "currency": "USD", "facts": {"capex": {"value": 190}}}
        obj = {"facts": {"us-gaap": {
            "PaymentsToAcquireOtherPropertyPlantAndEquipment": {"units": {"USD": [{**record, "val": 190}]}},
            "PaymentsToAcquireIntangibleAssets": {"units": {"USD": [{**record, "val": 410}]}},
        }}}
        meta = {"url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000008670.json", "sha256": "a" * 64}
        fact = enrich_capex(None, obj, meta, cik, report, statement)["facts"]["capex"]
        self.assertEqual(fact["value"], 600)
        self.assertTrue(valid_capex_components(fact["components"], cik, report, "capex"))
        self.assertFalse(valid_capex_components(fact["components"][:1], cik, report, "capex"))

    def test_income_rule_rechecks_the_concept_when_the_filing_rolls_forward(self):
        cik = 92122
        accession = "0000092122-27-000009"
        path = "https://www.sec.gov/Archives/edgar/data/92122/000009212227000009"
        report = {"accession": accession, "path": path, "url": path + "/so.htm",
                  "end": "2026-12-31", "filed": "2027-02-16", "form": "10-K"}
        table_url = path + "/R29.htm"
        statement = {"filing": accession, "end": report["end"], "start": "2026-01-01", "period_kind": "annual",
                     "currency": "USD", "facts": {"sales": {"value": 120_000_000}, "ebit": {"value": 30_000_000}}}
        table = {"title": "Consolidated Statements of Income - Southern", "sources": [table_url], "money_scale": 1_000_000,
                 "currency": "USD", "columns": ["line", "concept", "12 months to " + report["end"]],
                 "rows": [["Total operating revenues", "us-gaap:Revenues", 120],
                          ["Depreciation and amortization", "so:DepreciationAndAmortizationExcludingNuclearFuel", 10],
                          ["Total operating expenses", "us-gaap:CostsAndExpenses", 90],
                          ["Operating Income", "us-gaap:OperatingIncomeLoss", 30]]}
        result = {"structuredContent": {"company": {"cik": cik}, "period": "annual",
                  "filings": {"rows": [[accession, report["form"], report["filed"], report["end"], path + "/index.htm"]]},
                  "income": table}, "_meta": {"canlicapital.com/receipt": {"sources": [
                      {"url": table_url, "sha256_16": "a" * 16}]}}}
        class StubCache:
            def get(self, url, ttl, *, post_json):
                return json.dumps({"result": result}).encode(), {"url": url, "sha256": "b" * 64}
        fact = enrich_operating(StubCache(), cik, report, statement)["facts"]["da_excluding_nuclear_fuel"]
        self.assertEqual((fact["value"], fact["table_url"]), (10_000_000, table_url))
        table["rows"][1][1] = "us-gaap:DepreciationAndAmortization"
        with self.assertRaisesRegex(ValueError, "concept changed"):
            enrich_operating(StubCache(), cik, report, statement)

    def test_issuer_report_discovery_requires_the_label_and_download_host(self):
        page = b"""<a href="https://other.example/2025.pdf">2025 Report (English)</a>
        <a href="https://reports.example/2024.pdf">2024 Report (English)</a>
        <a href="https://reports.example/2025.pdf">2025 <strong>Report</strong> (English)</a>"""
        self.assertEqual(linked_report(page, "2025 Report (English)", "reports.example"),
                         "https://reports.example/2025.pdf")
        with self.assertRaisesRegex(ValueError, "Missing unique"):
            linked_report(page, "2025 Report (English)", "unknown.example")

    def test_filing_cache_does_not_store_invalid_responses(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            cache = Cache(root / "mutable", filing_root=root / "filings")
            with patch("equity_atlas.fetch.urlopen", return_value=BytesIO(b'<html>Unavailable</html>')):
                with self.assertRaises(ValueError):
                    cache.json("https://example.com/latest", 4)
            with patch("equity_atlas.fetch.urlopen", return_value=BytesIO(b'{"result":{"isError":true}}')):
                with self.assertRaises(ValueError):
                    cache.get(ENDPOINT, 8760)
            self.assertEqual(list(root.iterdir()), [])

    def test_preferred_capital_and_consolidated_scope(self):
        year = {"start":"2025-01-01","end":"2025-12-31","filed":"2026-02-24",
                "form":"10-K","accn":"0000000001-26-000001"}
        def flow(value):
            return {"units":{"USD":[{**year,"val":value}]}}
        def stock(value):
            return {"units":{"USD":[{**year,"start":None,"val":value}]}}
        data={"cik":1,"facts":{"us-gaap":{
            "RevenueFromContractWithCustomerExcludingAssessedTax":flow(800),
            "Revenues":flow(1000), "NetIncomeLoss":flow(120),
            "NetIncomeLossAvailableToCommonStockholdersBasic":flow(110),
            "StockholdersEquity":stock(500),
            "PreferredStockIncludingAdditionalPaidInCapitalNetOfDiscount":stock(40),
            "PreferredStockLiquidationPreferenceValue":stock(46),
            "PaymentsOfDividends":flow(65), "DividendsCommonStockCash":flow(52),
            "Depreciation":flow(12),
        }}}
        statement=from_sec(data,META,DAY,1)[0]
        v={k:x["value"] for k,x in statement["facts"].items()}
        self.assertEqual((v["sales"],v["contract_sales"]),(1000,800))
        self.assertEqual((v["preferred"],v["preferred_liquidation"]),(40,46))
        self.assertEqual(common_book(v),460)
        self.assertEqual(common_earnings(v,"us-gaap:NetIncomeLoss"),110)
        self.assertEqual((v["div_total"],v["div_common_declared"]),(65,52))
        self.assertIsNone(common_dividends(statement))
        self.assertNotIn("da",v)
        self.assertEqual(debt_amount({"debt_current_total":20,"debt_noncurrent":80,"short_borrow":12}),100)

    def test_quarter_does_not_take_year_to_date_cashflow(self):
        common={"end":"2026-09-30","filed":"2026-10-29","form":"10-Q","accn":"0000000001-26-000002"}
        def facts(*rows):
            return {"units":{"USD":[{**common,"start":start,"val":value} for start,value in rows]}}
        raw={"cik":1,"facts":{"us-gaap":{
            "Revenues":facts(("2026-07-01",120),("2026-01-01",355)),
            "NetIncomeLoss":facts(("2026-07-01",12),("2026-01-01",38)),
            "NetCashProvidedByUsedInOperatingActivities":facts(("2026-01-01",52)),
        }}}
        q=from_sec(raw,META,DAY,1,kind="quarter")[0]
        ytd=from_sec(raw,META,DAY,1,kind="ytd")[0]
        self.assertEqual(q["facts"]["sales"]["value"],120)
        self.assertNotIn("cfo",q["facts"])
        self.assertEqual(ytd["facts"]["cfo"]["value"],52)

    def test_extracted_instance_rejects_segment_and_wrong_entity(self):
        xml=b'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:g="http://fasb.org/us-gaap/2025" xmlns:iso="http://www.xbrl.org/2003/iso4217">
            <xbrli:context id="year"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
            <xbrli:context id="segment"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier>
                <xbrli:segment/></xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
            <xbrli:context id="other"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">2</xbrli:identifier></xbrli:entity>
                <xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
            <xbrli:unit id="USD"><xbrli:measure>iso:USD</xbrli:measure></xbrli:unit>
            <g:Revenues contextRef="segment" unitRef="USD">800</g:Revenues>
            <g:Revenues contextRef="other" unitRef="USD">700</g:Revenues>
            <g:Revenues contextRef="year" unitRef="USD" decimals="-3">1000000</g:Revenues>
            <g:NetIncomeLoss contextRef="year" unitRef="USD">-130000</g:NetIncomeLoss>
        </xbrli:xbrl>'''
        filing={"end":"2025-12-31","filed":"2026-02-24","form":"10-K","url":"https://www.sec.gov/a.htm",
                "accession":"0000000001-26-000001"}
        result=annual_from_instance(xml,META,filing,1)[0]
        self.assertEqual(result["facts"]["sales"]["value"],1000000)
        self.assertEqual(result["facts"]["sales"]["context_id"],"year")
        self.assertEqual(result["facts"]["net"]["value"],-130000)

    def test_archive_interim_separates_quarter_and_year_to_date(self):
        report = {"end": "2026-09-30", "filed": "2026-10-29", "form": "10-Q",
                  "url": "https://www.sec.gov/Archives/edgar/test.htm",
                  "accession": "0000000001-26-000001"}
        def context(key, start, end):
            return (f'<x:context id="{key}"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">'
                    f'1</x:identifier></x:entity><x:period><x:startDate>{start}</x:startDate>'
                    f'<x:endDate>{end}</x:endDate></x:period></x:context>')

        header = ('<x:xbrl xmlns:x="http://www.xbrl.org/2003/instance" xmlns:g="http://fasb.org/us-gaap/2026" '
                  'xmlns:iso="http://www.xbrl.org/2003/iso4217">'
                  '<x:unit id="USD"><x:measure>iso:USD</x:measure></x:unit>')
        values = {
            "quarter": ("2026-07-01", "2026-09-30", 100, 15),
            "ytd": ("2026-01-01", "2026-09-30", 300, 50),
            "prior": ("2025-07-01", "2025-09-30", 90, 13),
        }
        content = []
        for key, (start, end, sales, earnings) in values.items():
            content.append(context(key, start, end))
            for tag, value in (("Revenues", sales), ("NetIncomeLoss", earnings)):
                content.append(f'<g:{tag} contextRef="{key}" unitRef="USD">{value}</g:{tag}>')
        raw = (header + "".join(content) + "</x:xbrl>").encode()
        actual = periods_from_instance(raw, META, report, 1, ("quarter", "ytd"))
        self.assertEqual(actual["quarter"][0]["facts"]["sales"]["value"], 100)
        self.assertEqual(actual["ytd"][0]["facts"]["sales"]["value"], 300)
        self.assertEqual(actual["ytd"][0]["facts"]["net"]["start"], "2026-01-01")
        self.assertEqual(actual["quarter"][0]["filing"], report["accession"])

    def test_issuer_instance_validates_registrant_form_and_date(self):
        raw = b"""<x:xbrl xmlns:x="http://www.xbrl.org/2003/instance" xmlns:dei="http://xbrl.sec.gov/dei/2026">
          <x:context id="q"><x:entity><x:identifier scheme="http://www.sec.gov/CIK">1</x:identifier></x:entity>
            <x:period><x:instant>2026-09-30</x:instant></x:period>
          </x:context>
          <dei:EntityCentralIndexKey contextRef="q">0000000001</dei:EntityCentralIndexKey>
          <dei:DocumentType contextRef="q">10-Q</dei:DocumentType>
          <dei:DocumentPeriodEndDate contextRef="q">2026-09-30</dei:DocumentPeriodEndDate>
        </x:xbrl>"""
        report = {"end": "2026-09-30", "form": "10-Q", "accession": "0000000001-26-000001"}
        self.assertEqual(periods_from_instance(raw, META, report, 1, ("quarter",), verify_header=True),
                         {"quarter": []})
        with self.assertRaises(ValueError):
            periods_from_instance(raw, META, {**report, "form": "10-K"}, 1, ("quarter",), verify_header=True)
        with self.assertRaises(ValueError):
            periods_from_instance(raw, META, report, 2, ("quarter",), verify_header=True)

    def test_review_is_bound_to_original_and_every_later_amendment(self):
        original = "0000002488-26-000018"
        reviewed = "0000002488-26-000021"
        future = "0000002488-26-000022"
        base = {"end": "2025-12-27", "url": "https://www.sec.gov/Archives/edgar/test.htm"}
        filings = {
            original: {**base, "accession": original, "filed": "2026-02-04", "form": "10-K"},
            reviewed: {**base, "accession": reviewed, "filed": "2026-03-01", "form": "10-K/A"},
        }
        statement = {"filing": original, "end": base["end"]}
        self.assertEqual(amendment_reviews(filings, statement, filings[reviewed])[0]["accession"], reviewed)
        filings[future] = {**filings[reviewed], "accession": future, "filed": "2026-03-02"}
        self.assertEqual(amendment_reviews(filings, statement, filings[future]), [])

    def test_inline_parent_facts_apply_scale_and_sign(self):
        html = """
        <html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
              xmlns:xbrli="http://www.xbrl.org/2003/instance"
              xmlns:iso="http://www.xbrl.org/2003/iso4217"
              xmlns:dei="http://xbrl.sec.gov/dei/2026"
              xmlns:us-gaap="http://fasb.org/us-gaap/2026"
              xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2022-02-16">
        <ix:resources><xbrli:unit id="USD"><xbrli:measure>iso:USD</xbrli:measure></xbrli:unit>
        <xbrli:context id="parent">
          <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">1</xbrli:identifier></xbrli:entity>
          <xbrli:period><xbrli:startdate>2026-07-01</xbrli:startdate><xbrli:enddate>2026-09-30</xbrli:enddate></xbrli:period>
        </xbrli:context>
        <xbrli:context id="partnership">
          <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">2</xbrli:identifier></xbrli:entity>
          <xbrli:period><xbrli:startdate>2026-07-01</xbrli:startdate><xbrli:enddate>2026-09-30</xbrli:enddate></xbrli:period>
        </xbrli:context></ix:resources>
        <ix:nonnumeric name="dei:EntityCentralIndexKey" contextref="parent">0000000001</ix:nonnumeric>
        <ix:nonnumeric name="dei:DocumentType" contextref="parent">10-Q</ix:nonnumeric>
        <ix:nonnumeric name="dei:DocumentPeriodEndDate" contextref="parent">September 30, 2026</ix:nonnumeric>
        <ix:nonfraction name="us-gaap:Revenues" contextref="parent" unitref="USD" scale="3"
                        decimals="-3" id="revenue" format="ixt:num-dot-decimal">1,500</ix:nonfraction>
        <ix:nonfraction name="us-gaap:NetIncomeLoss" contextref="parent" unitref="USD" scale="3"
                        sign="-" decimals="-3" id="earnings" format="ixt:num-dot-decimal"><b>25</b></ix:nonfraction>
        <ix:nonfraction name="us-gaap:NetIncomeLoss" contextref="partnership" unitref="USD"
                        id="wrong-entity" format="ixt:num-dot-decimal">999</ix:nonfraction>
        </html>"""
        report = {"end": "2026-09-30", "filed": "2026-10-29", "form": "10-Q",
                  "url": "https://www.sec.gov/Archives/edgar/test.htm", "accession": "0000000001-26-000001"}
        periods = periods_from_inline(html.encode(), META, report, 1, ("quarter", "ytd"))
        self.assertEqual(periods["ytd"], [])
        self.assertEqual(periods["quarter"][0]["facts"]["sales"]["value"], 1_500_000)
        self.assertEqual(periods["quarter"][0]["facts"]["net"]["value"], -25_000)
        self.assertEqual(periods["quarter"][0]["facts"]["net"]["fact_id"], "earnings")
        with self.assertRaises(ValueError):
            periods_from_inline(html.encode(), META, {**report, "form": "10-K"}, 1, ("quarter",))

    def test_rounded_duplicate_retains_more_precise_cash(self):
        rounded = {"tag": "us-gaap:CashAndCashEquivalentsAtCarryingValue", "unit": "USD",
                   "value": 2_273_000_000, "decimals": "-6"}
        precise = {**rounded, "value": 2_273_497_000, "decimals": "-3"}
        self.assertEqual(precise_duplicates([rounded, precise]), [precise])
        self.assertEqual(precise_duplicates([rounded, {**precise, "value": 2_274_497_000}]), [])
        self.assertEqual(precise_duplicates([rounded, {**precise, "decimals": "-6"}]), [])

    def test_registrant_cik_follows_effective_date(self):
        self.assertEqual(cik_on(2115436, date(2026, 6, 30)), 34088)
        self.assertEqual(cik_on(34088, date(2026, 7, 1)), 2115436)
        self.assertEqual(cik_on(1045609, DAY), 1045609)

    def test_temporary_equity_reconciliation_uses_carrying_scope(self):
        def statement(**values):
            return {"facts": {k: {"value": v} for k, v in values.items()}}

        base = dict(assets=120, liabilities=60, total_equity=50)
        fields = dict(temporary_equity_parent=7, redeemable_nci=3, redeemable_nci_redemption=9)
        split = balance_check(statement(**base, **fields))
        self.assertTrue(split["reconciled"])
        self.assertEqual(split["temporary_equity_fields"], ["temporary_equity_parent", "redeemable_nci"])
        total = balance_check(statement(**base, **fields, temporary_equity_total=10))
        self.assertEqual(total["temporary_equity_fields"], ["temporary_equity_total"])
        only_redemption = balance_check(statement(**base, redeemable_nci_redemption=10))
        self.assertFalse(only_redemption["reconciled"])
        self.assertEqual(only_redemption["unexplained_residual"], 10)

    def test_four_column_filing_selects_current_quarter_and_current_ytd(self):
        line = "Net income    $ 4,892   $ 3,478    $ 15,865   $ 11,005"
        self.assertEqual(column(line, "Net income", 4), 4892)
        self.assertEqual(column(line, "Net income", 4, column_index=2), 15865)

    def test_issuer_copy_uses_current_column_after_optional_note(self):
        self.assertEqual(column("Net profit . . . .    ¥(2,500)    ¥ 1,999", "Net profit", 2), -2500)
        self.assertEqual(column("Dividends paid    32   —   (100)", "Dividends paid", 2), 0)
        with self.assertRaises(ValueError):
            column("Net profit    200    100\nNet profit    300    100", "Net profit", 2)
        with self.assertRaises(ValueError):
            column("Net profit    200n    100", "Net profit", 2)
        with self.assertRaises(ValueError):
            statement_page(["Financial Position\n2025 USD\nF-8"], "Financial Position", "F-8", ("2026 USD",))

    def test_taiwan_join_estimates_cap_and_excludes_fund_codes(self):
        registry=[{"公司代號":code,"出表日期":"1151108",SHARES:shares,"英文簡稱":"Issuer","公司名稱":"Issuer"}
                  for code,shares in [("2330","100"),("2454","300"),("0050","9999")]]
        quotes=[{"Date":"1151106","Code":code,"ClosingPrice":price}
                for code,price in [("2330","10"),("2454","5"),("0050","30")]]
        day, rows=taiwan_issuers(quotes,registry,DAY,2)
        self.assertEqual(str(day),"2026-11-06")
        self.assertEqual([(r["code"],r["estimated_cap_twd"]) for r in rows],[("2454",1500),("2330",1000)])
