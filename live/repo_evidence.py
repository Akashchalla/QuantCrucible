"""Lightweight repository evidence retrieval for Quant Crucible.

No embeddings or extra service are required. We rank allow-listed project files lexically,
return short excerpts, and keep the model grounded in committed code/results/docs.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .settings import SETTINGS

ALLOW = [
    "HYPOTHESIS.md", "HYPOTHESIS_B.md", "HYPOTHESIS_C.md", "HYPOTHESIS_8K.md",
    "QUANT_CRUCIBLE.md", "IMPLEMENTATION_STATUS.md",
    "results/REPORT.md", "results/REPORT_B.md", "results/REPORT_C.md",
    "results/gapfade_out_of_sample.json", "results/pricing_out_of_sample.json",
    "results/eightk_out_of_sample.json", "results/out_of_sample.json",
    "live/signal.py", "live/risk.py", "live/pipeline.py", "live/crucible.py",
    "live/multiverse.py", "live/black_box.py", "live/ghost_desk.py",
    "live/explainability.py", "live/feeds/massive.py", "live/market_intel.py",
    "filing_edge/HYPOTHESIS.md", "filing_edge/README.md", "filing_edge/BUILD_STATUS.md",
    "filing_edge/submission/results-summary.json", "filing_edge/submission/research-manifest.json",
]

STOP = {"the","a","an","and","or","to","of","in","on","for","is","are","was","were","we","our","this","that","it","me","my","what","why","how","did","do","does","show","tell","explain","more"}


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9_\-]{3,}", text.lower()) if t not in STOP}


def _text(path: Path) -> str:
    try:
        if path.suffix.lower() == ".json":
            return json.dumps(json.loads(path.read_text(errors="replace")), indent=2)
        return path.read_text(errors="replace")
    except Exception:
        return ""


def retrieve(question: str, *, route: str = "", symbol: str = "", limit: int = 5) -> list[dict[str, Any]]:
    qtok = _tokens(f"{question} {route} {symbol}")
    ranked: list[tuple[float, str, str]] = []
    for rel in ALLOW:
        path = SETTINGS.root / rel
        if not path.exists() or not path.is_file():
            continue
        text = _text(path)
        if not text:
            continue
        low = text.lower()
        score = 0.0
        for tok in qtok:
            n = low.count(tok)
            if n:
                score += min(n, 8) * (2.5 if tok in path.name.lower() else 1.0)
        # Route-aware priors so vague follow-ups still retrieve the right project evidence.
        priors = {
            "crucible": ["HYPOTHESIS", "REPORT", "crucible.py", "out_of_sample"],
            "multiverse": ["multiverse.py", "gapfade_out_of_sample", "HYPOTHESIS"],
            "black_box": ["black_box.py", "gapfade_out_of_sample", "REPORT"],
            "ghost": ["ghost_desk.py", "risk.py", "HYPOTHESIS"],
            "research_trial": ["HYPOTHESIS", "out_of_sample", "results-summary"],
            "project_state": ["pipeline.py", "risk.py", "signal.py"],
            "company_research": ["massive.py", "market_intel.py"],
        }
        if any(x.lower() in rel.lower() for x in priors.get(route, [])):
            score += 4.0
        if score <= 0:
            continue
        # Pick a compact window around the highest-value token occurrence.
        pos = 0
        for tok in sorted(qtok, key=len, reverse=True):
            p = low.find(tok)
            if p >= 0:
                pos = p
                break
        start = max(0, pos - 700)
        end = min(len(text), start + 2200)
        excerpt = text[start:end].strip()
        ranked.append((score, rel, excerpt))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [{"path": rel, "excerpt": excerpt} for _, rel, excerpt in ranked[:limit]]
