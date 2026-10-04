"""Build a self-contained notebook; no market cache, results or credentials are embedded."""
from pathlib import Path
import json,zipfile,io,base64,hashlib
ROOT=Path(__file__).resolve().parents[1]
files=[ROOT/'judge.py',ROOT/'config.json',ROOT/'protocol-v2.json']+sorted((ROOT/'edge').glob('*.py'))
buf=io.BytesIO()
with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
    for p in files:z.writestr(str(p.relative_to(ROOT)),p.read_bytes())
payload=base64.b64encode(buf.getvalue()).decode();sha=hashlib.sha256(buf.getvalue()).hexdigest()
cells=[]
def md(s):cells.append(dict(cell_type='markdown',metadata={},source=s.splitlines(True)))
def code(s):cells.append(dict(cell_type='code',execution_count=None,metadata={},outputs=[],source=s.splitlines(True)))
md('''# Filing Edge | Judge notebook
Systematic Trading + Massive. This notebook contains the exact research source in a verified archive. It runs in a clean Python 3.11+ kernel with **only a Massive API key**; no Tiger Data, Gemini or ElevenLabs key is needed for replication.

Set the dates in the second code cell. Run all cells. The code uses Massive filings and options only. Historical option NBBO entitlement is required. Requests are cached locally and bounded; a complete run can take time. No outcome is fabricated when coverage is missing.

Version 1 development results were inspected before version 2. Version 2 was frozen before the 2026 test. Changing the research source after accessing a window is rejected; retain the audit history. The 2026 static issuer universe and historical classification timing are documented limitations.
''')
code(f'''import base64, hashlib, io, os, sys, tempfile, zipfile
from pathlib import Path
archive = base64.b64decode({payload!r})
assert hashlib.sha256(archive).hexdigest() == {sha!r}
workspace = Path(tempfile.mkdtemp(prefix='filing-edge-judge-'))
with zipfile.ZipFile(io.BytesIO(archive)) as z:
    assert all(not Path(n).is_absolute() and '..' not in Path(n).parts for n in z.namelist())
    z.extractall(workspace)
sys.path.insert(0, str(workspace))
print('Verified research source extracted; no credentials are embedded.')
''')
code('''# Judges may replace these dates with an unseen historical window.
START_DATE = '2024-01-01'
END_DATE = '2025-12-31'
MODE = 'development'  # For different dates use 'sealed'; fixed 2026-01-01..2026-08-31 uses 'test'.
import getpass
if not os.environ.get('MASSIVE_API_KEY'):
    os.environ['MASSIVE_API_KEY'] = getpass.getpass('Massive API key (hidden): ')
from judge import run_study
report = run_study(START_DATE, END_DATE, MODE)
''')
code(r'''from IPython.display import display, Markdown
import html, json
rows = []
for h in report['horizons']:
    s = h['groups']['standalone']
    edge = 'N/A' if s['edge'] is None else f"{s['edge']*10000:.1f}"
    interval = 'N/A' if s['interval'] is None else ' / '.join(f"{x*10000:.1f}" for x in s['interval'])
    rows.append(f"| {h['horizon']} | {s['pairs']} | {edge} | {interval} |")
display(Markdown('## Fixed-horizon results\n| Sessions | Complete pairs | Difference (bps) | Exploratory interval (bps) |\n|---|---:|---:|---:|\n'+'\n'.join(rows)))
p = report['portfolio']
print(json.dumps({k:p[k] for k in ['trade_count','total_return','cagr','annualized_volatility','sharpe_zero_cash','max_drawdown','stale_mark_days','skipped']},indent=2))
display(Markdown('**'+report['decision']+'**\n\n'+'\n\n'.join(report['warnings'])))
output = workspace/'judge-report.json'
output.write_text(json.dumps(report,indent=2,allow_nan=False))
print('Full reproducibility report:',output)
''')
md('''## How to interpret this
A positive event-minus-control average is not proof of an investable edge. Review uncertainty, missing pairs, information timing, capacity and drawdowns. Expiry means a preclose option buyback proxy, not a settlement simulation. The portfolio sizes using information available at entry; missing future quotes never retroactively cancel a trade.

The raw market cache stays local. Do not publish your API key or licensed raw data. All model comparisons, cost/delay cells and expiry/moneyness sensitivities are retained in the report. The app integrations are optional explanation, storage and accessibility layers, not signal generators.
''')
for i,c in enumerate(cells):
    if c['cell_type']=='code':compile(''.join(c['source']),f'notebook-cell-{i}','exec')
nb=dict(cells=cells,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.11'}},nbformat=4,nbformat_minor=5)
for i,c in enumerate(cells):c['id']=f'filing-edge-{i}'
(ROOT/'submission'/'Filing_Edge_Judge.ipynb').write_text(json.dumps(nb,indent=1))
print('Notebook created with source archive SHA256 '+sha)
