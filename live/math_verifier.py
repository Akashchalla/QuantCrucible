"""Independent deterministic numerical verification for Quant Crucible.

The verifier intentionally does not call an LLM. Financial/statistical arithmetic is
recomputed locally from the underlying series so the result remains reproducible and testable.
Gemini is the orchestration, research and explanation layer; it never becomes the source of
truth for these calculations.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


def verify_return_metrics(net: pd.Series, reported: dict[str, Any]) -> dict[str, Any]:
    x = pd.Series(net).dropna().astype(float)
    std = x.std(ddof=1)
    recomputed = {
        "mean_bps": float(x.mean() * 1e4),
        "sharpe": float(np.sqrt(252) * x.mean() / std) if std > 0 else float("nan"),
        "ann_return": float(x.mean() * 252),
    }
    checks = {}
    for k, v in recomputed.items():
        rv = reported.get(k)
        ok = (
            rv is not None
            and np.isfinite(v)
            and np.isfinite(float(rv))
            and abs(v - float(rv)) <= max(1e-10, 1e-7 * max(1.0, abs(v)))
        )
        checks[k] = bool(ok)
    return {
        "provider": "deterministic-independent-recompute",
        "verified": all(checks.values()),
        "checks": checks,
        "recomputed": recomputed,
        "note": (
            "Metrics are independently recomputed from the underlying return series. "
            "Gemini may explain or critique the methodology, but does not supply the numeric truth."
        ),
    }
