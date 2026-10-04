"""Publish only derived research summaries and public filing evidence; exclude raw market responses."""
import sys,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from edge.runtime import read,config,PRIVATE,digest
from edge.providers import connections
from edge.briefing import transcript
from edge.readiness import assess
OUT=ROOT/'docs';OUT.mkdir(exist_ok=True)
reports={}
for key,name in [('massive','report-massive.json'),('synthetic','report-synthetic.json'),('v2development','report-v2-development-2024-01-01-2025-12-31.json'),('v2test','report-v2-test-2026-01-01-2026-08-31.json')]:
    r=read(name)
    if not r:continue
    r['trades']=[];r['published_summary']=True
    if r.get('portfolio'):r['portfolio']['ledger']=[]
    reports[key]=r
voices={}
for f in PRIVATE.glob('audio-*.json'):
    a=json.loads(f.read_text())
    if 'id' not in a:continue
    src=PRIVATE/('audio-'+a['id']+'.mp3')
    if not src.exists():continue
    matching=next((r for r in reports.values() if r['run_id']==a['run_id']),None)
    if not matching or a['transcript']!=transcript(matching):continue
    dest='briefing-'+a['id'][:16]+'.mp3';shutil.copyfile(src,OUT/dest);a['url']='./'+dest;voices[a['run_id']]=a
conns=connections()
for c in conns:c['detail']='Saved verification: '+c['detail']
state=dict(config=config(),connections=conns,coverage=read('coverage.json'),reports=reports,
    coverage_windows={'v2development':read('coverage-v2-2024-01-01-2025-12-31.json'),'v2test':read('coverage-v2-2026-01-01-2026-08-31.json')},
    freeze=read('freeze.json'),freeze_valid=False,freeze_v2=read('freeze-v2.json'),database=read('database-summary.json'),
    readiness={k:assess(r) for k,r in reports.items()},job={'status':'idle','message':'Saved-results replay · use the authenticated app for live APIs'},holdout='Evaluated once · Jan–Aug 2026',audio=None)
# Public SEC filing evidence is retained; raw option observations and NBBO are not included.
data=dict(state=state,voices=voices,explanations=read('demo-explanations.json',{}),database=read('tiger-live-snapshot.json',{}))
(OUT/'data.js').write_text('window.FILING_REPLAY = '+json.dumps(data,allow_nan=False)+';\n')
html=(ROOT/'web/index.html').read_text().replace('href="/style.css"','href="./style.css"').replace('src="/app.js"','src="./app.js"')
html=html.replace('<script src="./app.js"','<script src="./data.js"></script><script src="./replay.js"></script><script src="./app.js"')
html=html.replace('<main>','<main><div class="notice">SAVED-RESULTS DEMO · Actual completed API outputs, not a live server. Research and provider operations run in the authenticated Python app. <a href="https://github.com/srinivaspenumarthi/hack">Source &amp; judge notebook ↗</a></div>')
html=html.replace('Generate audio →','Load saved audio →').replace('Explain with Gemini →','Read Gemini explanation →').replace('Read live Timescale aggregates →','Read saved Timescale aggregates →')
# Content versions prevent a browser from mixing a new HTML page with cached old reports or scripts.
for asset,content in [('data.js',(OUT/'data.js').read_bytes()),('app.js',(ROOT/'web/app.js').read_bytes()),('style.css',(ROOT/'web/style.css').read_bytes()),('replay.js',(OUT/'replay.js').read_bytes())]:
    import hashlib
    html=html.replace('./'+asset+'"','./'+asset+'?v='+hashlib.sha256(content).hexdigest()[:12]+'"')
(OUT/'index.html').write_text(html)
for f in ['app.js','style.css']:shutil.copyfile(ROOT/'web'/f,OUT/f)
(OUT/'.nojekyll').touch()
manifest={k:read(k+'.json') for k in ['freeze-v2','access-v2-development-2024-01-01-2025-12-31','access-v2-test-2026-01-01-2026-08-31']}
manifest['original_pilot']=read('pilot-v1/freeze-original.json');manifest['reports']={k:dict(run_id=r['run_id'],data_hash=r['data_hash'],config_hash=r['config_hash']) for k,r in reports.items()}
(ROOT/'submission/research-manifest.json').write_text(json.dumps(manifest,indent=2))
(ROOT/'submission/results-summary.json').write_text(json.dumps(reports,indent=2))
print('Saved-results replay built. Raw market responses and secrets excluded.')
