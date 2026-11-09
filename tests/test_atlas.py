import unittest
from datetime import date
from equity_atlas.facts import from_sec
from equity_atlas.models import prepare, fit, cycle_read, ddm, fcfe_value, fcff_value, perp, ri_single, ri_multi
from equity_atlas.pipeline import universe, curated_history

DAY=date(2026,11,9)
def stmt(y, **fields):
    return {"end":f"{y}-12-31","currency":"USD","facts":{k:{"value":v,"tag":"us-gaap:"+k} for k,v in fields.items()}}
def case(kind, history, **kwargs):
    return prepare({"id":"test","kind":kind,"peer_group":"peer","accounting":"US GAAP",
                    "market_cap_usd":200,"as_of":str(DAY),**kwargs},
                   history,{"USD":{"rate":1}},DAY)

class FinanceTests(unittest.TestCase):
    def test_clean_surplus_residual_income_equals_ddm(self):
        b0,re,roe,g=80,.10,.15,.02
        d1=b0*(roe-g)
        expected=130
        self.assertAlmostEqual(perp(d1,re,g),expected)
        self.assertAlmostEqual(ri_single(b0,roe,re,g),expected)
        b1=b0*(1+g)
        self.assertAlmostEqual(ri_multi(b0,[roe]*3,[g/roe]*3,re,roe,g),expected)
        self.assertAlmostEqual(ddm([d1,b1*(roe-g)],re,g),expected)

    def test_terminal_at_end_of_explicit_horizon(self):
        self.assertAlmostEqual(fcff_value([8],.10,12,.10,.02,-25),(8+9.6/.08)/1.1-25)
        self.assertAlmostEqual(fcfe_value([8],.10,12,.10,.02),(8+9.6/.08)/1.1)
        with self.assertRaises(ValueError):
            perp(1,.03,.03)
        with self.assertRaises(ValueError):
            ri_single(80,.02,.10,.03)

    def test_peak_cycle_excludes_current_observation(self):
        hist=[stmt(y,sales=100,ebit=x) for y,x in zip(range(2020,2026),[10,8,12,11,9,40])]
        c=cycle_read(hist,"commodity")
        self.assertEqual(c["phase"],"above historical range")
        self.assertAlmostEqual(c["mid_margin"],.10)
        self.assertEqual(cycle_read(hist[1:],"commodity")["phase"],"insufficient cycle history")

    def test_loss_and_bank_disable_wrong_denominators(self):
        x=case("bank",[stmt(2025,net=-12,book=100,sales=100,ebit=10,cash=40,debt=60)])
        self.assertEqual(set(x["ratios"]),{"P/B"})
        outcome=fit(x,[])
        methods={m["method"]:m["status"] for m in outcome["decisions"]}
        self.assertEqual(methods["fcff"],"not_applicable")
        self.assertEqual(methods["pe_ggm"],"blocked")
        self.assertIsNone(outcome["selected"])

    def test_nav_independent_of_statement_and_expires(self):
        x=case("holdco",[])
        nav={"source":"https://example.com/filing","currency":"USD","period":"2026-10-01",
             "published":"2026-10-02","fair_value_assets":300,"all_senior_claims":25}
        out=fit(x,[],{"nav":nav})
        self.assertEqual(out["selected"],"assets")
        self.assertEqual(out["decisions"][0]["equity_usd"],275)
        nav["period"]="2025-10-01"
        self.assertIsNone(fit(x,[],{"nav":nav})["selected"])

    def test_no_ev_if_captive_finance_bridge_excluded(self):
        x=case("cyclical",[stmt(2025,net=12,book=100,sales=100,ebit=10,cash=40,debt=60)],ev_exclusion="Captive finance")
        self.assertIsNone(x["bridge"])
        self.assertNotIn("EV/Sales",x["ratios"])

class SourceTests(unittest.TestCase):
    def test_as_of_accession_period_and_conflict(self):
        def row(val,start="2025-01-01",end="2025-12-31",filed="2026-02-12",accn="1-26-3"):
            return {"val":val,"start":start,"end":end,"filed":filed,"accn":accn,"form":"10-K"}
        def tag(*rows):
            return {"units":{"USD":rows}}
        payload={"cik":1,"facts":{"us-gaap":{
            "Revenues":tag(row(200),row(58,start="2025-10-01"),row(1000,filed="2027-02-12")),
            "NetIncomeLoss":tag(row(20)),
            "StockholdersEquity":tag(row(90,start=None)),
            "OperatingIncomeLoss":tag(row(27),row(34)),
            "PaymentsToAcquireProductiveAssets":tag(row(50,accn="1-26-4")),
        }}}
        result=from_sec(payload,{"url":"https://data.sec.gov/x","sha256":"abcd"},DAY,1)
        self.assertEqual(len(result),1)
        fields=result[0]["facts"]
        self.assertEqual(fields["sales"]["value"],200)
        self.assertEqual(fields["net"]["accession"],"1-26-3")
        self.assertNotIn("ebit",fields)
        self.assertNotIn("capex",fields)
        self.assertEqual(result[0]["conflicts"],["ebit"])
        with self.assertRaises(ValueError):
            from_sec(payload,{},DAY,2)

    def test_rank_validation_and_floor(self):
        raw=b"Rank,Name,Symbol,marketcap,country\n1,X,X,1000,USA\n2,Y,Y,900,USA\n3,Z,Z,800,UK\n"
        self.assertEqual(len(universe(raw,None,900)),2)
        self.assertEqual([x["symbol"] for x in universe(raw,2)],["X","Y"])
        with self.assertRaises(ValueError):
            universe(raw.replace(b"900",b"1100"),2)

    def test_curated_uses_unit_and_dated_source(self):
        data={"X":{"currency":"EUR","url":"https://example.com","unit":1000000,
                   "filed":"2026-03-11","locator":"p. 6","years":{"2025-12-31":{"net":3,"book":10}}}}
        self.assertEqual(curated_history("X",date(2026,3,10),data),[])
        x=curated_history("X",DAY,data)[0]
        self.assertEqual(x["facts"]["net"]["value"],3000000)
        self.assertIsNone(x["facts"]["book"]["start"])

if __name__=="__main__":
    unittest.main()
