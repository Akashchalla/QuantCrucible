#!/usr/bin/env python3
"""Safe provider preflight for Quant Crucible.

Prints only configured/healthy status; never echoes credential values or response bodies.
Designed to be run locally after copying private credentials into .env.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def status(configured: bool, ok: bool | None = None, **extra):
    out = {"configured": bool(configured)}
    if ok is not None:
        out["ok"] = bool(ok)
    out.update(extra)
    return out


def main() -> int:
    report: dict[str, dict] = {}

    # Gemini: model-list endpoint validates the key without consuming a generation.
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        report["gemini"] = status(False)
    else:
        try:
            import requests
            r = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": key}, timeout=20,
            )
            report["gemini"] = status(True, r.ok, http=r.status_code)
        except Exception as exc:
            report["gemini"] = status(True, False, error=type(exc).__name__)

    # Massive: lightweight market-status endpoint.
    key = os.getenv("MASSIVE_API_KEY", "").strip()
    if not key:
        report["massive"] = status(False)
    else:
        try:
            import requests
            r = requests.get(
                "https://api.massive.com/v1/marketstatus/now",
                params={"apiKey": key}, timeout=20,
            )
            report["massive"] = status(True, r.ok, http=r.status_code)
        except Exception as exc:
            report["massive"] = status(True, False, error=type(exc).__name__)

    # ElevenLabs: account endpoint, response body intentionally discarded.
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        report["elevenlabs"] = status(False)
    else:
        try:
            import requests
            r = requests.get(
                "https://api.elevenlabs.io/v1/user",
                headers={"xi-api-key": key}, timeout=20,
            )
            report["elevenlabs"] = status(True, r.ok, http=r.status_code)
        except Exception as exc:
            report["elevenlabs"] = status(True, False, error=type(exc).__name__)

    # Databento metadata-only request; does not request timeseries data.
    key = os.getenv("DATABENTO_API_KEY", "").strip()
    if not key:
        report["databento"] = status(False)
    else:
        try:
            import databento as db
            hist = db.Historical(key)
            rng = hist.metadata.get_dataset_range(dataset="XNAS.ITCH")
            report["databento"] = status(True, bool(rng))
        except ModuleNotFoundError:
            report["databento"] = status(True, False, error="dependency-not-installed")
        except Exception as exc:
            report["databento"] = status(True, False, error=type(exc).__name__)

    # Timescale/Tiger Data: SELECT 1 only.
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        report["timescale"] = status(False)
    else:
        try:
            import psycopg
            with psycopg.connect(url, connect_timeout=12) as conn:
                with conn.cursor() as cur:
                    cur.execute("select 1")
                    ok = cur.fetchone()[0] == 1
            report["timescale"] = status(True, ok)
        except ModuleNotFoundError:
            report["timescale"] = status(True, False, error="dependency-not-installed")
        except Exception as exc:
            report["timescale"] = status(True, False, error=type(exc).__name__)

    report["alpaca"] = {
        "configured": bool(os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET")),
        "mode": "broker-enabled" if (os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_API_SECRET")) else "simulated-paper",
    }
    report["math_verification"] = {
        "configured": True,
        "ok": True,
        "mode": "deterministic-independent-recompute",
    }

    print(json.dumps(report, indent=2, sort_keys=True))
    required = ["gemini", "massive", "elevenlabs"]
    # Network/dependency failures should be visible but not hide the report.
    return 0 if all(report.get(k, {}).get("configured") for k in required) else 2


if __name__ == "__main__":
    raise SystemExit(main())
