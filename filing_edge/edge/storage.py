"""Optional Tiger Data persistence; core reproducibility also works offline."""
import json
from urllib.parse import urlparse
from .runtime import ROOT, settings


def connect():
    from .providers import ProviderError
    try:
        import psycopg
    except ImportError:
        raise ProviderError('PostgreSQL driver is missing. Install requirements.txt first.') from None
    url = settings().get('DATABASE_URL', '')
    if not url or urlparse(url).scheme not in ('postgres', 'postgresql'):
        raise ProviderError('Configure a PostgreSQL DATABASE_URL locally.')
    try:
        return psycopg.connect(url, connect_timeout=10, sslmode='require')
    except Exception:
        raise ProviderError('Tiger Data connection failed. Verify connection details, SSL and network access.') from None


def check_database():
    with connect() as conn:
        row = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname='timescaledb')").fetchone()
    return 'PostgreSQL connected; TimescaleDB ' + ('available.' if row[0] else 'not enabled.')


def initialize():
    with connect() as conn:
        conn.execute((ROOT / 'sql' / 'schema.sql').read_text())
    return {'status':'initialized'}


def persist_run(report):
    with connect() as conn:
        conn.execute('INSERT INTO research_runs (run_id, created_at, kind, config_hash, report) VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT (run_id) DO NOTHING',
                     (report['run_id'], report['created_at'], report['kind'], report['config_hash'], json.dumps(report)))
    return {'status':'stored', 'run_id':report['run_id']}


def persist_dataset(dataset):
    with connect() as conn:
        for obs in dataset['observations']:
            for c in obs['contracts']:
                rows = [(d+'T21:00:00Z', c['ticker'], dataset['kind'], b['close'], b['volume']) for d,b in c['bars'].items()]
                with conn.cursor() as cur:
                    cur.executemany('INSERT INTO option_observations (session_label,contract,source,close,volume) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING', rows)
    with connect() as conn:
        conn.autocommit = True
        conn.execute("CALL refresh_continuous_aggregate('daily_option_activity', NULL, NULL)")
    return {'status':'stored', 'note':'session_label is a fixed UTC daily label, not an execution timestamp'}


def dashboard():
    """Read precomputed Timescale aggregates, rather than scanning raw option rows."""
    with connect() as conn:
        rows=conn.execute("SELECT session,contracts,traded_contracts FROM daily_option_activity WHERE source='massive' ORDER BY session DESC LIMIT 60").fetchall()
        runs=conn.execute("SELECT run_id,created_at,kind,report->>'mode',report->>'schema_version' FROM research_runs ORDER BY created_at DESC LIMIT 20").fetchall()
    return dict(source='Tiger Data continuous aggregate',daily=[dict(day=str(r[0])[:10],contracts=r[1],volume=r[2]) for r in reversed(rows)],
        runs=[dict(run_id=r[0],created_at=str(r[1]),kind=r[2],mode=r[3],version=r[4]) for r in runs])
