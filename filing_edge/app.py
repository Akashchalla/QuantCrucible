"""Local research dashboard. Only the explicit static allowlist is served."""
import base64
import hmac
import json
import threading
import argparse
import re
from urllib.parse import parse_qs, urlparse
from wsgiref.simple_server import make_server, WSGIServer, WSGIRequestHandler
from socketserver import ThreadingMixIn
from edge.runtime import PRIVATE, ROOT, config, read, settings, now, digest
from edge.providers import connections, explain, ProviderError
from edge.research import capital
from edge import workflow
from edge.readiness import assess

STATIC={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
LOCK=threading.Lock()
JOB={'status':'idle','message':'Ready','action':None}


def state():
    cfg=config(); frozen=read('freeze.json')
    return dict(config=cfg,connections=connections(),coverage=read('coverage.json'),
        reports={**{k:read('report-'+k+'.json') for k in ('synthetic','massive')}, 'v2development':read('report-v2-development-2024-01-01-2025-12-31.json'),'v2test':read('report-v2-test-2026-01-01-2026-08-31.json')},
        freeze_v2=read('freeze-v2.json'),audio=read('audio-latest.json'),
        readiness={k:assess(read(n)) for k,n in {'v2development':'report-v2-development-2024-01-01-2025-12-31.json','v2test':'report-v2-test-2026-01-01-2026-08-31.json','massive':'report-massive.json','synthetic':'report-synthetic.json'}.items()},
        coverage_windows={'v2development':read('coverage-v2-2024-01-01-2025-12-31.json'),'v2test':read('coverage-v2-2026-01-01-2026-08-31.json')},
        freeze=frozen,freeze_valid=bool(frozen and frozen['config_hash']==digest(cfg) and frozen.get('research_hash',frozen['source_hash'])==workflow.source_hash()),
        database=read('database-summary.json'),job=dict(JOB),holdout='Evaluated once · Jan–Aug 2026' if read('report-v2-test-2026-01-01-2026-08-31.json') else 'Locked · Jan–Aug 2026')


def launch(action,body):
    with LOCK:
        if JOB['status']=='running':raise ValueError('Another research operation is running. Wait for it to finish.')
        JOB.update(status='running',action=action,message='Starting '+action,started_at=now(),result=None)
    def progress(message):
        with LOCK:JOB['message']=message
    def worker():
        try:
            result=workflow.run(action,body,progress)
            with LOCK:JOB.update(status='complete',message=action+' completed',result=result,finished_at=now())
        except (ProviderError,ValueError) as exc:
            with LOCK:JOB.update(status='failed',message=str(exc),finished_at=now())
        except Exception:
            with LOCK:JOB.update(status='failed',message='Operation failed. No credentials were logged. Recheck input coverage and service access.',finished_at=now())
    threading.Thread(target=worker,daemon=True).start()
    return dict(JOB)


def application(environ,start_response):
    headers=[('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),
             ('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; media-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
    def respond(code,data,mime='application/json',extra=None):
        payload=json.dumps(data,allow_nan=False).encode() if mime=='application/json' else data
        start_response(code,headers+[('Content-Type',mime+'; charset=utf-8'),('Content-Length',str(len(payload)))]+(extra or []))
        return [payload]
    if environ.get('PATH_INFO')=='/healthz' and environ.get('REQUEST_METHOD')=='GET':
        return respond('200 OK',{'status':'ok','service':'filing-edge'})
    env=settings(); password=env.get('APP_PASSWORD','')
    host=urlparse('//'+environ.get('HTTP_HOST','')).hostname
    if not password and host not in ('127.0.0.1','localhost','::1'):
        return respond('403 Forbidden',{'error':'Remote access requires APP_PASSWORD and an HTTPS reverse proxy.'})
    if password:
        expected='Basic '+base64.b64encode(('research:'+password).encode()).decode()
        if not hmac.compare_digest(environ.get('HTTP_AUTHORIZATION',''),expected):
            return respond('401 Unauthorized',{'error':'Authentication required.'},extra=[('WWW-Authenticate','Basic realm="Filing Edge"')])
    path=environ.get('PATH_INFO','/'); method=environ['REQUEST_METHOD']
    try:
        if method=='GET':
            if path in STATIC:
                name,mime=STATIC[path]
                return respond('200 OK',(ROOT/'web'/name).read_bytes(),mime)
            if path=='/healthz':return respond('200 OK',{'status':'ok','service':'filing-edge'})
            if path=='/api/database':
                from edge.storage import dashboard
                return respond('200 OK',dashboard())
            if path.startswith('/api/audio/'):
                key=path.split('/')[-1]
                if not re.fullmatch('[a-f0-9]{64}',key):raise ValueError('Invalid audio ID.')
                f=PRIVATE/('audio-'+key+'.mp3')
                if not f.exists():raise ValueError('Audio is not available yet.')
                return respond('200 OK',f.read_bytes(),'audio/mpeg')
            if path=='/api/state':return respond('200 OK',state())
            if path=='/api/report':
                kind=parse_qs(environ.get('QUERY_STRING','')).get('kind',['synthetic'])[0]
                if kind not in ('synthetic','massive','v2development','v2test'):raise ValueError('Unknown report kind.')
                report=state()['reports'][kind]
                if not report:raise ValueError('No report exists for this data source.')
                return respond('200 OK',report,extra=[('Content-Disposition',f'attachment; filename="filing-edge-{kind}.json"')])
            return respond('404 Not Found',{'error':'Not found.'})
        if method!='POST':return respond('405 Method Not Allowed',{'error':'Method not allowed.'})
        origin=environ.get('HTTP_ORIGIN')
        if (origin and urlparse(origin).netloc!=environ.get('HTTP_HOST')) or environ.get('HTTP_X_FILING_EDGE')!='1':
            return respond('403 Forbidden',{'error':'Same-origin request required.'})
        length=int(environ.get('CONTENT_LENGTH') or '0')
        if not 0<length<=16384:raise ValueError('Request size is invalid.')
        body=json.loads(environ['wsgi.input'].read(length))
        if not isinstance(body,dict):raise ValueError('Expected a JSON object.')
        if path=='/api/briefing':
            from edge.briefing import generate
            kind=body.get('kind','v2development')
            report=state()['reports'].get(kind)
            if not report:raise ValueError('Evaluate this study before generating audio.')
            return respond('200 OK',generate(report))
        if path=='/api/capital':
            names=('account','spot','strike','premium','allocation')
            if set(body)!=set(names):raise ValueError('Provide account, spot, strike, premium and allocation.')
            return respond('200 OK',capital(**{k:float(body[k]) for k in names}))
        if path=='/api/explain':
            cov=read('coverage.json',{})
            event=next((e for e in cov.get('events',[]) if e['id']==body.get('id')),None)
            if not event:raise ValueError('Select a real filing from the coverage audit.')
            return respond('200 OK',explain(event))
        action=path.removeprefix('/api/')
        if path.startswith('/api/') and action in ('check','coverage','demo','freeze','study','database-init','database-sync'):
            return respond('202 Accepted',launch(action,body))
        return respond('404 Not Found',{'error':'Not found.'})
    except (ValueError,TypeError,OverflowError) as exc:
        message=str(exc) if isinstance(exc,(ProviderError,ValueError)) and not isinstance(exc,json.JSONDecodeError) else 'Invalid request.'
        return respond('400 Bad Request',{'error':message})
    except Exception:
        return respond('500 Internal Server Error',{'error':'Operation failed; credentials were not logged.'})


class ThreadingServer(ThreadingMixIn,WSGIServer):
    daemon_threads=True

class QuietHandler(WSGIRequestHandler):
    def log_message(self,*args):pass

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--host',default='127.0.0.1');args=parser.parse_args()
    if args.host not in ('127.0.0.1','localhost') and not settings().get('APP_PASSWORD'):
        parser.error('Set APP_PASSWORD before binding outside localhost; terminate TLS with your reverse proxy.')
    with make_server(args.host,args.port,application,server_class=ThreadingServer,handler_class=QuietHandler) as server:
        print(f'Filing Edge: http://{args.host}:{args.port}',flush=True)
        server.serve_forever()
