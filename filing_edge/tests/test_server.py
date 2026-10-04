import io,json,unittest
from unittest.mock import patch
import app

class ServerTests(unittest.TestCase):
    def request(self,path,method='GET',body=None,headers=None):
        data=json.dumps(body or {}).encode();environ={'PATH_INFO':path,'REQUEST_METHOD':method,'HTTP_HOST':'127.0.0.1:8765','wsgi.input':io.BytesIO(data),'CONTENT_LENGTH':str(len(data))}
        environ.update(headers or {});out={}
        def start(code,headers):out['code']=code;out['headers']=dict(headers)
        out['body']=b''.join(app.application(environ,start));return out
    @patch('app.settings',return_value={})
    def test_secrets_not_served(self,_):
        for path in ('/.env','/private_data/connections.json','/../../.env'):
            self.assertTrue(self.request(path)['code'].startswith('404'))
    @patch('app.settings',return_value={'APP_PASSWORD':'unit-test-only'})
    def test_health_is_public_but_state_is_not(self,_):
        self.assertTrue(self.request('/healthz')['code'].startswith('200'))
        self.assertTrue(self.request('/api/state')['code'].startswith('401'))
    @patch('app.settings',return_value={})
    def test_cross_origin_mutation_rejected(self,_):
        r=self.request('/api/capital','POST',{}, {'HTTP_X_FILING_EDGE':'1','HTTP_ORIGIN':'https://attacker.invalid'})
        self.assertTrue(r['code'].startswith('403'))
    @patch('app.settings',return_value={})
    def test_audio_traversal_rejected(self,_):
        self.assertTrue(self.request('/api/audio/../../.env')['code'].startswith('400'))
    @patch('app.settings',return_value={})
    def test_capital_api(self,_):
        r=self.request('/api/capital','POST',{'account':100000,'spot':100,'strike':95,'premium':2,'allocation':.2},{'HTTP_X_FILING_EDGE':'1'})
        self.assertTrue(r['code'].startswith('200'));self.assertEqual(json.loads(r['body'])['contracts'],2)

class ReadinessTests(unittest.TestCase):
    def test_positive_average_does_not_authorize_trading(self):
        from edge.readiness import assess
        r={'kind':'massive','horizons':[{'horizon':21,'groups':{'standalone':{'edge':.1,'pairs':100,'issuers':30,'calendar_clusters':20}}}], 'portfolio':{'total_return':.1}}
        gate=assess(r)
        self.assertEqual(gate['decision'],'Research only')
        self.assertEqual(gate['passed'],4)
