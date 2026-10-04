import unittest,math
from copy import deepcopy
from edge.execution import quote,decision_time,open_short,close_short
from edge.study import protocol,quoted_trade
from edge.portfolio import simulate,assignment_cashflow
from edge.runtime import config
from edge.calendar import shift

class FakeMassive:
    def __init__(self,row):self.row=row
    def get(self,*a,**k):return {'results':[self.row] if self.row else []}

class SubmissionTests(unittest.TestCase):
    def test_quote_rejects_future_crossed_and_nan(self):
        day='2024-06-03';ns=int(decision_time(day).timestamp())*10**9
        q=dict(bid_price=2,ask_price=2.1,bid_size=40,ask_size=40,sip_timestamp=ns)
        self.assertEqual(quote(FakeMassive(q),'O:X',day,protocol())['status'],'usable')
        for patch in ({'sip_timestamp':ns+1},{'ask_price':1},{'bid_price':math.nan},{'sip_timestamp':ns-121*10**9}):
            self.assertEqual(quote(FakeMassive(q|patch),'O:X',day,protocol())['status'],'unavailable')
    def test_early_close_and_weekend(self):
        self.assertEqual(decision_time('2024-11-29').hour,12)
        with self.assertRaises(ValueError):quote(FakeMassive(None),'O:X','2024-06-02',protocol())
    def test_spread_and_fees_reduce_pnl(self):
        q=dict(bid=2,ask=2.1)
        self.assertLess(open_short(q,2,.65,.05)-close_short(q,2,.65,.05),-20)
    def test_physical_assignment(self):
        r=assignment_cashflow(95,70,2,400)
        self.assertEqual(r['shares_received'],200);self.assertEqual(r['cash_paid'],19000)
        self.assertEqual(r['liquidation_pnl'],-4600)
    def fixture(self):
        cfg=config();p=protocol();a='2024-06-03';e=shift(a,1);x=shift(a,21)
        q=dict(status='usable',bid=2,ask=2.1,bid_size=100,ask_size=100)
        c=dict(ticker='O:X',bucket=cfg['headline_bucket'],otm=cfg['headline_otm'],strike=95,reference_spot=100,expiry='2024-10-18',
               quotes={shift(a,i):q.copy() for i in range(1,22)},bars={shift(a,-i):dict(close=2,volume=1000) for i in range(1,21)})
        o=dict(id='x',pair_id='x',role='event',context='standalone',ticker='X',anchor=a,available=e,contracts=[c])
        data=dict(event_start=a,outcome_cutoff=x,observations=[o]);return cfg,p,data,o,c,e,x
    def test_no_exit_lookahead_for_acceptance(self):
        cfg,p,data,o,c,e,x=self.fixture()
        full=simulate(data,cfg,p);self.assertEqual(full['trade_count'],1)
        del c['quotes'][x]
        missing=simulate(data,cfg,p)
        self.assertEqual(missing['trade_count'],1);self.assertEqual(missing['open_positions'],1)
        self.assertEqual(missing['ledger'][0]['quantity'],full['ledger'][0]['quantity'])
        self.assertGreater(missing['stale_mark_days'],0)
    def test_cash_conservation_and_collateral(self):
        cfg,p,data,o,c,e,x=self.fixture();r=simulate(data,cfg,p)
        self.assertAlmostEqual(r['final_equity']-p['initial_capital'],sum(t['net_pnl'] for t in r['ledger']))
        self.assertLessEqual(max(v['collateral'] for v in r['curve']),p['initial_capital']*p['issuer_fraction'])
    def test_zero_display_capacity_and_delayed_signal(self):
        cfg,p,data,o,c,e,x=self.fixture();c['quotes'][e]=c['quotes'][e]|{'bid_size':1}
        self.assertEqual(simulate(data,cfg,p)['trade_count'],0)
        o['available']=shift(e,1)
        row=quoted_trade(o,cfg['headline_bucket'],cfg['headline_otm'],21,1,.05,.65,x)
        self.assertEqual(row['reason'],'signal_not_available')
    def test_missing_returns_are_not_zero(self):
        cfg,p,data,o,c,e,x=self.fixture();del c['quotes'][x]
        r=quoted_trade(o,cfg['headline_bucket'],cfg['headline_otm'],21,1,.05,.65,x)
        self.assertEqual(r['status'],'unavailable');self.assertNotIn('net_return',r)

if __name__=='__main__':unittest.main()
