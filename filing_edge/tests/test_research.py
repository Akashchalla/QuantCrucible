import copy
import io
import json
import math
import unittest
from unittest.mock import patch
from edge.calendar import shift,on_or_after
from edge.model import trade,validate_dataset
from edge.research import capital,summarize
from edge.providers import Massive,ProviderError,NoRedirect
from edge.runtime import config
import app


def observation():
    return dict(id='a-event',pair_id='a',role='event',context='standalone',ticker='TEST',anchor='2024-06-03',available='2024-06-04',contracts=[dict(ticker='O:TEST',bucket='3-6m',otm=.05,strike=95,reference_spot=100,expiry='2024-09-20',bars={'2024-06-04':{'close':2.,'volume':100},'2024-06-05':{'close':1.,'volume':150}})])

class AccountingTests(unittest.TestCase):
    def quote(self,obs=None,**overrides):
        kw=dict(bucket='3-6m',otm=.05,horizon=2,delay=1,haircut=.05,fee=.65,cutoff='2024-12-31');kw.update(overrides)
        return trade(obs or observation(),**kw)
    def test_short_put_costs_and_full_collateral(self):
        r=self.quote();self.assertEqual(r['status'],'priced');self.assertAlmostEqual(r['gross_pnl'],100);self.assertAlmostEqual(r['costs'],16.3);self.assertAlmostEqual(r['net_pnl'],83.7);self.assertAlmostEqual(r['net_return'],83.7/9500)
    def test_no_entry_before_signal_available(self):
        o=observation();o['available']='2024-06-05';self.assertEqual(self.quote(o)['reason'],'signal_not_available')
    def test_no_stale_price_carry(self):
        o=observation();del o['contracts'][0]['bars']['2024-06-05'];self.assertEqual(self.quote(o)['reason'],'no_fresh_exit_bar')
    def test_no_same_day_profit_and_no_oos_leak(self):
        self.assertEqual(self.quote(horizon=1)['reason'],'horizon_not_after_eligible_entry')
        self.assertEqual(self.quote(cutoff='2024-06-04')['reason'],'outcome_beyond_window_cutoff')
    def test_higher_costs_lower_each_trade_return(self):
        self.assertLess(self.quote(haircut=.10)['net_return'],self.quote(haircut=.05)['net_return'])
    def test_infinite_volume_is_not_a_valid_fill(self):
        o=observation();o['contracts'][0]['bars']['2024-06-04']['volume']=math.inf
        self.assertEqual(self.quote(o)['reason'],'no_fresh_entry_bar')
    def test_invalid_execution_costs_are_rejected(self):
        with self.assertRaises(ValueError):self.quote(haircut=-.1)
    def test_duplicate_pair_role_is_rejected(self):
        o=observation();other=copy.deepcopy(o);other['id']='another-id'
        with self.assertRaises(ValueError):validate_dataset(dict(schema_version=1,kind='massive',mode='development',outcome_cutoff='2024-12-31',observations=[o,other]))
    def test_calendar_holidays(self):
        self.assertEqual(shift('2024-07-03',1),'2024-07-05');self.assertEqual(shift('2025-01-08',1),'2025-01-10')
    def test_volume_is_lagged(self):
        o=observation();o['contracts'][0]['bars'].update({d:{'close':2.,'volume':10} for d in ['2024-05-28','2024-05-29','2024-05-30','2024-05-31','2024-06-03']});self.assertEqual(self.quote(o)['lagged_option_adv'],10)
    def test_missing_control_never_counts_as_zero(self):
        row=self.quote();s=summarize([row],30,1);self.assertEqual(s['pairs'],0);self.assertIsNone(s['edge'])
    def test_paired_issuer_cluster_difference(self):
        r=self.quote();rows=[]
        for i in range(8):
            for role,val in [('event',.03),('control',.01)]:rows.append(dict(r,pair_id=str(i),ticker='T'+str(i%4),anchor='2024-01-01' if i<4 else '2024-07-01',role=role,net_return=val))
        s=summarize(rows,99,42);self.assertEqual(s['pairs'],8);self.assertAlmostEqual(s['edge'],.02);self.assertAlmostEqual(s['interval'][0],.02)
    def test_capital_reserves_and_tail(self):
        r=capital(100000,100,95,2,.2);self.assertEqual(r['contracts'],2);self.assertEqual(r['collateral'],19000);self.assertAlmostEqual(r['max_loss'],18601.3);self.assertAlmostEqual(r['scenarios'][0]['pnl'],-r['max_loss']);self.assertLessEqual(r['collateral']+2*.65,20000)
    def test_nonfinite_capital_rejected(self):
        for value in [math.inf,math.nan,-1,0]:
            with self.assertRaises(ValueError):capital(value,100,95,2,.2)
    def test_dataset_cutoff_is_enforced(self):
        with self.assertRaises(ValueError):validate_dataset(dict(schema_version=1,kind='massive',mode='development',outcome_cutoff='2024-06-04',observations=[observation()]))

class BoundaryTests(unittest.TestCase):
    def call(self,path='/',method='GET',body=None,host='127.0.0.1:8765',origin=None,header=True,password=''):
        payload=json.dumps(body or {}).encode();env={'PATH_INFO':path,'REQUEST_METHOD':method,'HTTP_HOST':host,'CONTENT_LENGTH':str(len(payload)),'wsgi.input':io.BytesIO(payload)}
        if origin:env['HTTP_ORIGIN']=origin
        if header:env['HTTP_X_FILING_EDGE']='1'
        result={}
        def start(code,headers):result.update(code=code,headers=dict(headers))
        with patch('app.settings',return_value={'APP_PASSWORD':password}):result['body']=b''.join(app.application(env,start))
        return result
    def test_secret_files_not_served(self):
        for path in ['/.env','/private_data/coverage.json','/../.env','/edge/runtime.py']:
            self.assertTrue(self.call(path)['code'].startswith('404'))
    def test_mutation_requires_origin_and_header(self):
        self.assertTrue(self.call('/api/demo','POST',origin='https://evil.example')['code'].startswith('403'))
        self.assertTrue(self.call('/api/demo','POST',header=False)['code'].startswith('403'))
    def test_remote_requires_auth(self):
        self.assertTrue(self.call(host='public.example')['code'].startswith('403'))
        self.assertTrue(self.call(password='testing-only')['code'].startswith('401'))
    def test_capital_endpoint(self):
        r=self.call('/api/capital','POST',{'account':100000,'spot':100,'strike':95,'premium':2,'allocation':.2});self.assertEqual(json.loads(r['body'])['contracts'],2)
    def test_holdout_not_exposed(self):
        self.assertTrue(self.call('/api/test','POST')['code'].startswith('404'))
    def test_provider_redirect_never_forwards_key(self):
        with self.assertRaises(ProviderError):NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')
    def test_pagination_refuses_partial_results(self):
        m=object.__new__(Massive)
        with patch.object(m,'get',return_value={'results':[1],'next_url':'https://api.massive.com/next'}):
            with self.assertRaises(ProviderError):m.rows('/first',pages=2)
    def test_error_payload_not_echoed(self):
        r=self.call('/api/capital','POST',{'secret-test-value':'never-echo'});self.assertNotIn(b'never-echo',r['body'])

if __name__=='__main__':unittest.main()
