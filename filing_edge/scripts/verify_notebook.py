"""Independent clean-kernel integration check; Massive credential stays in environment only."""
import os,sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from nbclient import NotebookClient
import nbformat
from edge.runtime import settings
os.environ['MASSIVE_API_KEY']=settings()['MASSIVE_API_KEY']
nb=nbformat.read(ROOT/'submission/Filing_Edge_Judge.ipynb',as_version=4)
work=ROOT/'tmp/notebook-verified-final';work.mkdir(exist_ok=True,parents=True)
nb.cells[1].source=nb.cells[1].source.replace("Path(tempfile.mkdtemp(prefix='filing-edge-judge-'))",'Path('+repr(str(work))+')')
nb.cells[2].source=nb.cells[2].source.replace("'2024-01-01'","'2023-06-01'").replace("'2025-12-31'","'2023-08-31'").replace("MODE = 'development'","MODE = 'sealed'")
try:
    NotebookClient(nb,timeout=3600,kernel_name='python3').execute()
    nbformat.write(nb,ROOT/'private_data/judge-clean-kernel-validation.ipynb')
    (ROOT/'submission/notebook-validation.json').write_text(json.dumps({'status':'passed','window':['2023-06-01','2023-08-31'],'mode':'sealed','credentials':'Massive only','fresh_kernel':True,'workspace':'Explicit fresh workspace instead of system temp for local storage reliability.','note':'This example window was inspected for software replication; it is not claimed as an untouched future holdout.'},indent=2))
    print('Clean-kernel judge notebook completed with only the Massive key.',flush=True)
except Exception as e:
    (ROOT/'private_data/notebook-validation-error.txt').write_text(type(e).__name__+'\n'+str(e).replace(os.environ['MASSIVE_API_KEY'],'[REDACTED]'))
    print('Notebook verification failed; private sanitized diagnostics saved.',flush=True)
    raise SystemExit(1)
