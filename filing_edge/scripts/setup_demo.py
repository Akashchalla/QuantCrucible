"""Populate the complete authenticated demo with actual APIs. Never sends brokerage orders."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from edge.study import run_window
from edge.providers import check_connections,explain
from edge.runtime import read,save
from edge.storage import initialize,persist_dataset,persist_run,dashboard
from edge.briefing import generate
from edge.workflow import database_summary
check_connections(print)
initialize()
for mode,start,end in [('development','2024-01-01','2025-12-31'),('test','2026-01-01','2026-08-31')]:
    r=run_window(start,end,mode,print)
    persist_dataset(read(f'dataset-v2-{mode}-{start}-{end}.json'));persist_run(r);generate(r)
    cov=read(f'coverage-v2-{start}-{end}.json')
    if cov['events']:explain(cov['events'][0])
save('tiger-live-snapshot.json',dashboard());database_summary()
print('Actual-data demo populated. Start python app.py; test window is now inspected.')
