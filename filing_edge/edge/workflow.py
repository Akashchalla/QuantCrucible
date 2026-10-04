"""The same bounded operations are used by the CLI and dashboard."""
from .runtime import config, read, save, digest, now, ROOT
from . import providers, collect, demo, research, storage


def source_hash():
    paths = [ROOT/'edge'/n for n in ('calendar.py','collect.py','demo.py','model.py','providers.py','research.py','runtime.py')] + [ROOT/'config.json']
    return digest({str(p.relative_to(ROOT)):p.read_text() for p in paths})


def freeze():
    cfg=config(); cov=read('coverage.json')
    if not cov or cov['config_hash']!=digest(cfg) or not cov['events']:
        raise ValueError('Collect a nonempty development coverage audit with the current configuration first.')
    existing=read('freeze.json')
    record=dict(created_at=now(),config_hash=digest(cfg),source_hash=source_hash(),config=cfg,
        coverage_hash=digest(cov),purpose='Development pilot specification; not a preregistration of a final validated strategy.',
        holdout='2026-01-01 through 2026-08-31 remains unopened.')
    if existing:
        if existing['config_hash']!=record['config_hash'] or existing.get('research_hash',existing['source_hash'])!=record['source_hash']:
            raise ValueError('The specification changed after freezing. Preserve the existing run and create a new version explicitly; do not overwrite its freeze.')
        return existing
    save('freeze.json',record)
    return record


def database_summary():
    with storage.connect() as conn:
        runs=conn.execute('SELECT kind,count(*) FROM research_runs GROUP BY kind').fetchall()
        rows=conn.execute('SELECT source,count(*),sum(contracts) FROM daily_option_activity GROUP BY source').fetchall()
    result=dict(checked_at=now(),runs={r[0]:r[1] for r in runs},daily_buckets={r[0]:r[1] for r in rows},
                contract_sessions={r[0]:int(r[2]) for r in rows})
    save('database-summary.json',result)
    return result


def run(action,body=None,progress=lambda _:None):
    cfg=config(); body=body or {}
    if action=='check':return providers.check_connections(progress)
    if action=='coverage':return collect.coverage(cfg,progress)
    if action=='demo':
        progress('Evaluating deterministic synthetic paths')
        data=demo.dataset(cfg); save('dataset-synthetic.json',data)
        report=research.evaluate(data,cfg)
        return dict(run_id=report['run_id'],kind='synthetic')
    if action=='freeze':return freeze()
    if action=='study':
        frozen=read('freeze.json')
        if not frozen or frozen.get('research_hash',frozen['source_hash'])!=source_hash():
            raise ValueError('Freeze the current research code before collecting returns.')
        limit=body.get('limit',12)
        if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=1000:
            raise ValueError('Study limit must be an integer from 1 to 1000.')
        data=collect.collect(cfg,limit,progress)
        report=research.evaluate(data,cfg)
        return dict(run_id=report['run_id'],kind='massive')
    if action=='database-init':
        progress('Creating research tables and the daily continuous aggregate')
        storage.initialize();return database_summary()
    if action=='database-sync':
        kind=body.get('kind','synthetic')
        if kind not in ('synthetic','massive'):raise ValueError('Unknown dataset kind.')
        data,report=read('dataset-'+kind+'.json'),read('report-'+kind+'.json')
        if not data or not report:raise ValueError('Run this study before synchronizing it.')
        progress('Storing '+kind+' option observations in Tiger Data')
        storage.persist_dataset(data);storage.persist_run(report)
        return database_summary()
    raise ValueError('Unknown operation.')
