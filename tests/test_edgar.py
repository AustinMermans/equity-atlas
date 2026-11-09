from datetime import date
import unittest

from equity_atlas.edgar import annual_from_instance
from equity_atlas.facts import from_sec
from equity_atlas.market import SHARES, taiwan_issuers
from equity_atlas.models import common_book, common_dividends, common_earnings, debt_amount

DAY = date(2026, 11, 9)
META = {"url": "https://data.sec.gov/api/example", "sha256": "example"}


class EdgarTests(unittest.TestCase):
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

    def test_taiwan_join_estimates_cap_and_excludes_fund_codes(self):
        registry=[{"公司代號":code,"出表日期":"1151108",SHARES:shares,"英文簡稱":"Issuer","公司名稱":"Issuer"}
                  for code,shares in [("2330","100"),("2454","300"),("0050","9999")]]
        quotes=[{"Date":"1151106","Code":code,"ClosingPrice":price}
                for code,price in [("2330","10"),("2454","5"),("0050","30")]]
        day, rows=taiwan_issuers(quotes,registry,DAY,2)
        self.assertEqual(str(day),"2026-11-06")
        self.assertEqual([(r["code"],r["estimated_cap_twd"]) for r in rows],[("2454",1500),("2330",1000)])
