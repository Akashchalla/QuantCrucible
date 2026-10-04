-- Run explicitly using `python cli.py database-init` or the local dashboard.
CREATE TABLE IF NOT EXISTS research_runs (
  run_id text PRIMARY KEY, created_at timestamptz NOT NULL,
  kind text NOT NULL CHECK (kind IN ('synthetic','massive')),
  config_hash text NOT NULL, report jsonb NOT NULL
);
-- Fixed daily labels only: these are not actual last-trade execution times.
CREATE TABLE IF NOT EXISTS option_observations (
  session_label timestamptz NOT NULL, contract text NOT NULL, source text NOT NULL,
  close double precision NOT NULL CHECK(close >= 0),
  volume double precision NOT NULL CHECK(volume >= 0),
  PRIMARY KEY(session_label,contract,source)
);
SELECT create_hypertable('option_observations', 'session_label', if_not_exists => TRUE);
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_option_activity
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 day',session_label) AS session,
  source, count(*) AS contracts, sum(volume) AS traded_contracts
FROM option_observations GROUP BY 1,2 WITH NO DATA;
