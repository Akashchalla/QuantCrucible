"""Shared Gemini planner for text + voice.

Both Streamlit chat and ElevenLabs Speech Engine call :func:`execute_turn`. Gemini is the
router/research brain; every money/statistics action is executed by allow-listed deterministic
Python. There is deliberately no order-placement or strategy-mutation route in this module.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

import requests

from .market_intel import resolve_symbol
from .settings import SETTINGS
from .store import Store

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ROUTES = {
    "company_research", "market_snapshot", "compare", "analogs", "crucible",
    "multiverse", "black_box", "ghost", "project_state", "explain_day",
    "profit_bridge", "replay", "research_trial", "scope_refusal", "clarify",
}

# Frontend tabs are presentation modes, not always analytical routes. Keep them separate
# from the last resolved analytical route so short follow-ups remain grounded.
MODE_ROUTE_MAP = {
    "crucible": "crucible",
    "multiverse": "multiverse",
    "black_box": "black_box",
    "ghost": "ghost",
    "explain_day": "explain_day",
    "profit_bridge": "profit_bridge",
    "replay": "replay",
    "research_trial": "research_trial",
    "systematic": "crucible",
    "massive_research": "research_trial",
    "massive_evidence": "research_trial",
    "massive_capital": "research_trial",
    "massive_infra": "research_trial",
    "vision": "market_snapshot",
}

FOLLOWUP_PHRASES = (
    "show me the evidence", "show evidence", "evidence behind that",
    "explain more simply", "explain simply", "simpler", "tell me more",
    "go deeper", "explain that", "why", "why?", "what about that",
)

PLANNER_SYSTEM = """You are the routing brain for Quant Crucible, an explainable systematic-trading research workstation.
Choose exactly one allow-listed analytical route. Never create an order, signal, personalized buy/sell recommendation,
or mutate a strategy parameter. The current symbol and recent conversation are context; resolve short follow-ups like
"what about earnings?", "compare with Meta", or "show me similar cases" against that context.

Routes:
- company_research: current company/news/earnings/why-is-it-moving questions requiring Google-grounded public research.
- market_snapshot: price/volatility/current quantitative state of one symbol.
- compare: compare performance of 2-5 symbols, usually wants a chart.
- analogs: historical situations similar to the selected symbol/current state.
- crucible: formal hypothesis/red-team/robustness/backtest attacks.
- multiverse: what-if stress scenario, costs/volatility/liquidity/alpha decay.
- black_box: explain/reconstruct a loss, worst day, fills, execution or risk event.
- ghost: counterfactual value/opportunity cost of risk controls / VIX gate.
- project_state: questions about the stored live paper book, gate, positions, orders, recent P&L.
- explain_day: explain a selected/mentioned recorded session, why the gate traded/stayed out, company selection evidence, biggest loss.
- profit_bridge: gross profit -> trading costs/execution differences -> net profit, cost drag, doubled-cost hypotheticals, paper-vs-backtest.
- replay: historical replay commands such as start before open, pause/decision, show available info, move to close.
- research_trial: challenge claims, OOS integrity, survivorship/delisted-stock limitations, failed experiments, options evidence.
- scope_refusal: anything unrelated to markets, companies as investments, quantitative trading, this project/research, or its evidence.
- clarify: a relevant but underspecified question where the evidence target is unclear; ask one concise project-specific clarification instead of guessing.

If the user says "show me the evidence" or "explain more simply", keep the current research module/context instead of inventing a new topic.
Return JSON only. `symbols` should contain Yahoo-style symbols when you know them, e.g. GOOGL, NVDA, XAUUSD=X.
Scenario numbers are multipliers, not percentages: double volatility = 2.0; triple costs = 3.0.
Use periods like 1mo, 3mo, 6mo, 1y, 2y.
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "route": {"type": "STRING", "enum": sorted(ROUTES)},
        "symbol": {"type": "STRING"},
        "symbols": {"type": "ARRAY", "items": {"type": "STRING"}},
        "period": {"type": "STRING"},
        "reason": {"type": "STRING"},
        "scenario": {"type": "OBJECT", "properties": {
            "vix_multiplier": {"type": "NUMBER"},
            "cost_multiplier": {"type": "NUMBER"},
            "alpha_retention": {"type": "NUMBER"},
            "extra_slippage_bps": {"type": "NUMBER"},
            "volatility_multiplier": {"type": "NUMBER"},
            "horizon_sessions": {"type": "INTEGER"},
        }},
    },
    "required": ["route", "symbol", "symbols", "period", "reason", "scenario"],
}


def _context_text(context: list[dict[str, str]] | None) -> str:
    if not context:
        return ""
    rows = []
    for m in context[-10:]:
        role = str(m.get("role") or "user")[:20]
        content = str(m.get("content") or "").strip().replace("\x00", "")[:700]
        if content:
            rows.append(f"{role.upper()}: {content}")
    return "\n".join(rows)


def _gemini_plan(question: str, current_symbol: str, context: list[dict[str, str]] | None = None, ui_context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not SETTINGS.gemini_api_key:
        return _fallback_plan(question, current_symbol, ui_context, context)
    prompt = f"CURRENT_SYMBOL: {current_symbol}\n"
    if ui_context:
        prompt += "UI_CONTEXT: " + json.dumps(ui_context, default=str)[:1200] + "\n"
    ctx = _context_text(context)
    if ctx:
        prompt += f"RECENT_CONVERSATION:\n{ctx}\n"
    prompt += f"QUESTION: {question}"
    payload = {
        "systemInstruction": {"parts": [{"text": PLANNER_SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 700,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMA,
        },
    }
    try:
        r = requests.post(
            GEMINI_URL.format(model=SETTINGS.gemini_model),
            headers={"x-goog-api-key": SETTINGS.gemini_api_key},
            json=payload,
            timeout=45,
        )
        if r.status_code >= 400:
            return _fallback_plan(question, current_symbol, ui_context, context)
        text = "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"])
        doc = json.loads(text)
        if doc.get("route") not in ROUTES:
            raise ValueError("invalid route")
        doc["symbol"] = resolve_symbol(doc.get("symbol") or question, current_symbol)
        doc["symbols"] = [resolve_symbol(s, s) for s in (doc.get("symbols") or [])][:5]
        if doc["route"] == "compare" and current_symbol not in doc["symbols"] and len(doc["symbols"]) < 5:
            doc["symbols"].insert(0, current_symbol)
        doc["period"] = doc.get("period") or "6mo"
        return doc
    except Exception:
        return _fallback_plan(question, current_symbol, ui_context, context)


def _period_from_text(q: str) -> str:
    patterns = [
        (r"\b(1|one)\s*(month|mo)\b", "1mo"),
        (r"\b(3|three)\s*(month|mo)s?\b", "3mo"),
        (r"\b(6|six)\s*(month|mo)s?\b", "6mo"),
        (r"\b(1|one)\s*year\b", "1y"),
        (r"\b(2|two)\s*years?\b", "2y"),
        (r"\b(5|five)\s*years?\b", "5y"),
    ]
    for pat, out in patterns:
        if re.search(pat, q):
            return out
    return "6mo"


def _fallback_plan(
    question: str,
    current_symbol: str,
    ui_context: dict[str, Any] | None = None,
    context: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    q = question.lower().strip()
    recent_text = " ".join(str(m.get("content") or "").lower() for m in (context or [])[-6:])
    conversation_text = (recent_text + " " + q).strip()
    symbol = resolve_symbol(question, current_symbol)
    symbols: list[str] = []
    for token in ["google", "alphabet", "nvidia", "apple", "microsoft", "meta", "amazon", "tesla", "gold", "xauusd", "spy", "qqq", "bitcoin"]:
        if token in q:
            s = resolve_symbol(token)
            if s not in symbols:
                symbols.append(s)
    compare_intent = any(x in q for x in ["compare", "versus", " vs ", "add ", "against "])
    if compare_intent:
        if current_symbol not in symbols:
            symbols.insert(0, current_symbol)
    elif not symbols:
        symbols = [symbol]

    module = str((ui_context or {}).get("module") or "").lower()
    last_route = str((ui_context or {}).get("last_route") or "").lower()
    followup_route = None
    if last_route in ROUTES - {"clarify", "scope_refusal"}:
        followup_route = last_route
    elif module in ROUTES - {"clarify", "scope_refusal"}:
        followup_route = module
    elif module in MODE_ROUTE_MAP:
        followup_route = MODE_ROUTE_MAP[module]

    # Explicit answers to our own clarification must resolve the target instead of
    # falling straight back into the same clarification loop.
    clarified_live = any(x in q for x in ["live paper", "paper trading system", "live trading system", "live system", "paper system"])
    clarified_backtest = any(x in q for x in ["gap-fade", "gap fade", "systematic backtest", "committed backtest", "backtest system"])
    clarified_massive = any(x in q for x in ["massive", "filing edge", "options study", "8-k study", "8k study"])

    # Company/ticker fragments are common with live STT (e.g. "what's the Apple, um").
    market_terms = {
        "google": "GOOGL", "alphabet": "GOOGL", "googl": "GOOGL", "goog": "GOOG",
        "nvidia": "NVDA", "nvda": "NVDA", "apple": "AAPL", "aapl": "AAPL",
        "microsoft": "MSFT", "msft": "MSFT", "meta": "META", "amazon": "AMZN", "amzn": "AMZN",
        "tesla": "TSLA", "tsla": "TSLA", "gold": "XAUUSD=X", "xauusd": "XAUUSD=X",
        "spy": "SPY", "qqq": "QQQ", "bitcoin": "BTC-USD", "btc": "BTC-USD",
    }
    explicit_market_terms = [t for t in market_terms if re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", q)]
    if explicit_market_terms:
        symbol = market_terms[explicit_market_terms[0]]
        symbols = []
        for t in explicit_market_terms:
            s2 = market_terms[t]
            if s2 not in symbols:
                symbols.append(s2)
        if compare_intent and current_symbol not in symbols:
            symbols.insert(0, current_symbol)

    locked = False
    if any(x in q for x in ["who is pm", "prime minister", "recipe", "weather tomorrow", "write a poem", "movie recommendation", "sports score"]):
        route, locked = "scope_refusal", True
    elif clarified_live:
        route, locked = "project_state", True
    elif clarified_backtest:
        route, locked = "crucible", True
    elif clarified_massive:
        route, locked = "research_trial", True
    elif any(x in q for x in ["explain this day", "what happened that day", "why did our strategy trade", "why did we trade", "why did we stay out", "why did we select", "biggest loss"]):
        route, locked = "explain_day", True
    elif any(x in q for x in ["where did our profit go", "profit bridge", "costs reduce", "cost drag", "paper-trading result", "paper trading result", "backtest different"]):
        route, locked = "profit_bridge", True
    elif any(x in q for x in ["start before the market", "historical replay", "replay", "pause and explain", "move to the closing", "move to closing", "what information was available"]):
        route, locked = "replay", True
    elif any(x in q for x in ["put our research on trial", "research on trial", "challenge this claim", "delisted", "survivorship", "genuinely untouched", "why should i trust", "failed experiment"]):
        route, locked = "research_trial", True
    elif any(x in q for x in FOLLOWUP_PHRASES) and followup_route:
        route = followup_route
    elif any(x in q for x in ["red team", "red-team", "hypothesis", "robust", "overfit", "break my", "test strategy"]):
        route, locked = "crucible", True
    elif any(x in q for x in ["ghost", "without gate", "without the gate", "no gate", "gate removed", "always-on", "always on", "what saved", "opportunity cost", "counterfactual"]):
        route, locked = "ghost", True
    elif any(x in q for x in ["multiverse", "stress", "double volatility", "triple cost", "scenario"]) or (
        "what if" in q and any(x in q for x in ["volatility", "vol", "cost", "slippage", "liquidity", "alpha", "spread"])
    ):
        route, locked = "multiverse", True
    elif any(x in q for x in ["black box", "autopsy", "worst day", "why did we lose", "loss came from", "execution loss"]):
        route, locked = "black_box", True
    elif any(x in q for x in ["similar", "analogs", "analogue", "deja vu", "déjà"]):
        route = "analogs"
    elif compare_intent and len(symbols) >= 2:
        route, locked = "compare", True
    elif any(x in q for x in ["today", "latest", "news", "earnings", "announcement", "why is", "what happened", "going on", "company", "filing", "search"]):
        route = "company_research"
    elif any(x in q for x in [
        "gate", "vix", "paper book", "paper trading", "live paper", "position", "order",
        "recent pnl", "pnl", "risk event", "risk limit", "costs and risks", "cost and risk",
        "costs", "cost", "risk", "trading cost", "execution cost", "slippage", "notional",
        "kill switch", "risk control", "execution",
    ]):
        route, locked = "project_state", True
    elif explicit_market_terms:
        # A partial voice question such as "what's the Apple..." is enough to give a
        # useful quantitative snapshot rather than interrogating the user.
        route, locked = "market_snapshot", True
    elif followup_route and (len(q.split()) <= 5 or any(x in q for x in ["that", "it", "same", "again"])):
        route = followup_route
    elif "clarification" in recent_text and any(x in conversation_text for x in ["live paper", "gap-fade", "filing edge", "massive"]):
        route = "project_state" if "live paper" in conversation_text else ("research_trial" if any(x in conversation_text for x in ["filing edge", "massive"]) else "crucible")
    else:
        route = "clarify"

    cost = 3.0 if "triple" in q and "cost" in q else (2.0 if "double" in q and "cost" in q else 2.0)
    vol = 3.0 if "triple" in q and "vol" in q else (2.0 if "double" in q and "vol" in q else 1.5)
    alpha = 0.4 if "alpha decay" in q else 0.7
    return {
        "route": route,
        "symbol": symbol,
        "symbols": symbols[:5],
        "period": _period_from_text(q),
        "reason": "deterministic fallback router",
        "_locked": locked,
        "scenario": {
            "vix_multiplier": vol,
            "cost_multiplier": cost,
            "alpha_retention": alpha,
            "extra_slippage_bps": 5.0,
            "volatility_multiplier": vol,
            "horizon_sessions": 60,
        },
    }


def plan(question: str, current_symbol: str = "GOOGL", context: list[dict[str, str]] | None = None, ui_context: dict[str, Any] | None = None) -> dict[str, Any]:
    q = (question or "").strip()
    if not q:
        raise ValueError("Ask a question first.")
    if len(q) > 1800:
        raise ValueError("Question is too long (max 1,800 characters).")
    deterministic = _fallback_plan(q, resolve_symbol(current_symbol), ui_context, context)
    # Explicit project commands, clarification answers, scope boundaries, and noisy
    # company fragments should be deterministic. This prevents an LLM routing wobble
    # from sending voice back into a clarification loop.
    if deterministic.get("_locked"):
        return deterministic
    planned = _gemini_plan(q, resolve_symbol(current_symbol), context, ui_context)
    # Gemini is the preferred router for genuinely ambiguous language, but never let a
    # generic `clarify` erase a useful deterministic/contextual route.
    if planned.get("route") == "clarify" and deterministic.get("route") != "clarify":
        return deterministic
    return planned


def _tool_trace(route: str) -> list[str]:
    traces = {
        "company_research": ["Gemini route", "Market-data snapshot", "Google Search grounding", "Source evidence", "Frontend visualization"],
        "market_snapshot": ["Gemini route", "Market-data feed", "Deterministic statistics", "Frontend visualization"],
        "compare": ["Gemini route", "Multi-symbol market data", "Normalized-return calculation", "Frontend visualization"],
        "analogs": ["Gemini route", "Historical market data", "State-vector similarity", "Forward-outcome ledger", "Frontend visualization"],
        "crucible": ["Gemini route", "Committed research panel", "8 deterministic red-team attacks", "Independent math verification", "Frontend visualization"],
        "multiverse": ["Gemini route", "Committed research panel", "Scenario replay", "Monte Carlo bootstrap", "Sensitivity surface", "Frontend visualization"],
        "black_box": ["Gemini route", "Committed evidence", "P&L reconciliation", "Loss attribution", "Frontend visualization"],
        "ghost": ["Gemini route", "Counterfactual portfolios", "Risk-control value ledger", "Opportunity-cost ledger", "Frontend visualization"],
        "project_state": ["Gemini route", "Read-only paper-book state", "Grounded operator answer"],
        "explain_day": ["Gemini route", "Recorded session/research ledger", "Gate + selection evidence", "P&L attribution", "Frontend highlight"],
        "profit_bridge": ["Gemini route", "Committed gross returns", "Deterministic cost model", "Paper ledger when available", "Hypothetical scenarios labeled"],
        "replay": ["Gemini route", "Point-in-time evidence gate", "Recorded replay stages", "No-lookahead disclosure", "Frontend timeline"],
        "research_trial": ["Gemini route", "Pre-registered hypotheses", "Committed OOS results", "Failed/fragile evidence", "Strongest limitation first"],
        "scope_refusal": ["Scope guard", "Read-only finance/research boundary"],
        "clarify": ["Gemini intent check", "Repository evidence retrieval", "Clarification instead of guessed fallback"],
    }
    return traces.get(route, ["Gemini route", "Deterministic tool", "Frontend visualization"])



def _compact_for_model(value: Any, depth: int = 0) -> Any:
    """Bound tool output before the synthesis pass; never ask Gemini to do arithmetic."""
    if depth > 3:
        return str(value)[:500]
    try:
        import pandas as pd
        if isinstance(value, pd.DataFrame):
            return value.head(12).reset_index().to_dict(orient="records")
        if isinstance(value, pd.Series):
            return value.head(12).to_dict()
    except Exception:
        pass
    if isinstance(value, dict):
        return {str(k): _compact_for_model(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [_compact_for_model(v, depth + 1) for v in list(value)[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)[:800]


def _gemini_explain(question: str, result: dict[str, Any], context: list[dict[str, str]] | None, ui_context: dict[str, Any] | None) -> str | None:
    if not SETTINGS.gemini_api_key or result.get("route") in {"scope_refusal", "clarify"}:
        return None
    from .repo_evidence import retrieve
    evidence = retrieve(question, route=str(result.get("route") or ""), symbol=str(result.get("symbol") or ""), limit=5)
    result["repo_evidence"] = evidence
    for e in evidence:
        result.setdefault("sources", []).append({"title": e["path"], "url": f"/api/document/{e['path']}"})
    prompt = {
        "question": question,
        "selected_context": ui_context or {},
        "recent_conversation": (context or [])[-8:],
        "route": result.get("route"),
        "symbol": result.get("symbol"),
        "deterministic_tool_answer": result.get("answer"),
        "tool_output": _compact_for_model(result.get("payload")),
        "repository_evidence": evidence,
        "external_sources": result.get("sources", [])[:10],
    }
    system = """You are the final explainer for Quant Crucible, this specific repository—not a generic finance assistant.
Answer the user's exact question using the deterministic tool output and repository excerpts provided.
Be concrete about THIS system: name the strategy, gate, cost model, experiment, file/result, or evidence limitation when relevant.
Never invent a number, trade, timestamp, filing, causal claim, or repository fact. Numerical facts must come from tool_output/repository_evidence.
If evidence is missing, say exactly what is missing. Distinguish actual/committed results from hypotheticals.
For causal market questions, distinguish verified facts, plausible explanations, and unknowns.
Do not repeat a canned overview unless it directly answers the question. For voice, keep the first paragraph concise, then add useful specificity.
If the user asks 'show me the evidence', explicitly name the most relevant files/results.
"""
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": json.dumps(prompt, default=str)[:24000]}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 900},
    }
    try:
        r = requests.post(GEMINI_URL.format(model=SETTINGS.gemini_model), headers={"x-goog-api-key": SETTINGS.gemini_api_key}, json=payload, timeout=45)
        if r.status_code >= 400:
            return None
        return "".join(p.get("text", "") for p in r.json()["candidates"][0]["content"]["parts"]).strip() or None
    except Exception:
        return None

def execute_turn(
    store: Store,
    session: date,
    question: str,
    current_symbol: str = "GOOGL",
    context: list[dict[str, str]] | None = None,
    ui_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from . import ai_war_room
    from .black_box import inspect_research_day, research_sessions
    from .crucible import run_red_team
    from .ghost_desk import run_ghost_desk
    from .market_intel import historical_analogs, normalized_comparison, research_company, snapshot
    from .multiverse import Scenario, run_scenario
    from .explainability import explain_day, profit_bridge, replay_day, research_trial

    p = plan(question, current_symbol, context=context, ui_context=ui_context)
    route, symbol = p["route"], p["symbol"]
    result: dict[str, Any] = {
        "route": route,
        "plan": p,
        "symbol": symbol,
        "question": question,
        "sources": [],
        "tool_trace": _tool_trace(route),
    }

    if route == "company_research":
        r = research_company(symbol, question)
        result.update({
            "answer": r["answer"], "speech": r["answer"], "sources": r["sources"], "payload": r,
            "ui": {"type": "company_research", "symbol": symbol},
        })
    elif route == "market_snapshot":
        s = snapshot(symbol)
        result.update({
            "payload": s,
            "answer": (
                f"{symbol} is at {s['price']:.2f} as of {s['as_of']}. The latest daily move is {s['return_1d']:+.2%}, "
                f"the 20-session move is {s['return_20d']:+.2%}, and 20-day annualized realized volatility is {s['realized_vol_20d']:.1%}. "
                f"The latest move is {s['move_sigma_60d']:+.2f} standard deviations versus the recent 60-session distribution."
            ),
            "ui": {"type": "market_snapshot", "symbol": symbol},
        })
        result["speech"] = result["answer"]
    elif route == "compare":
        syms = list(dict.fromkeys(p.get("symbols") or [symbol, "NVDA"]))
        if len(syms) < 2:
            syms = [symbol, "QQQ"]
        df = normalized_comparison(syms, p.get("period") or "6mo")
        returns = (df.iloc[-1] / 100.0 - 1.0).sort_values(ascending=False)
        best, worst = returns.index[0], returns.index[-1]
        result.update({
            "payload": {"comparison": df, "returns": returns},
            "answer": f"Over the selected window, {best} leads at {returns.iloc[0]:+.1%}, while {worst} is {returns.iloc[-1]:+.1%}. I plotted all series normalized to 100 so the comparison is apples-to-apples.",
            "ui": {"type": "comparison", "symbols": list(df.columns)},
        })
        result["speech"] = result["answer"]
    elif route == "analogs":
        a = historical_analogs(symbol)
        adf = a["analogs"]
        pos20 = float((adf["fwd_20d"] > 0).mean()) if len(adf) else float("nan")
        med20 = float(adf["fwd_20d"].median()) if len(adf) else float("nan")
        result.update({
            "payload": a,
            "answer": f"I found {len(adf)} separated historical states closest to {symbol}'s current feature vector. {pos20:.0%} were positive 20 sessions later, with a median 20-session return of {med20:+.1%}. This is a small descriptive analogue set, not a forecast.",
            "ui": {"type": "analogs", "symbol": symbol},
        })
        result["speech"] = result["answer"]
    elif route == "crucible":
        c = run_red_team()
        result.update({
            "payload": c,
            "answer": f"Crucible verdict: {c['verdict']} with robustness score {c['score']}/100. " + " ".join(c["findings"][:3]),
            "ui": {"type": "crucible"},
        })
        result["speech"] = result["answer"]
    elif route == "multiverse":
        raw = p.get("scenario") or {}
        sc = Scenario(
            vix_multiplier=max(0.5, min(4.0, float(raw.get("vix_multiplier", 1.5)))),
            cost_multiplier=max(0.0, min(8.0, float(raw.get("cost_multiplier", 2.0)))),
            alpha_retention=max(0.0, min(1.5, float(raw.get("alpha_retention", 0.7)))),
            extra_slippage_bps=max(0.0, min(100.0, float(raw.get("extra_slippage_bps", 5.0)))),
            volatility_multiplier=max(0.5, min(4.0, float(raw.get("volatility_multiplier", 1.25)))),
            horizon_sessions=max(10, min(252, int(raw.get("horizon_sessions", 60)))),
        )
        m = run_scenario(sc)
        sm = m["stress_metrics"]
        result.update({
            "payload": m,
            "answer": f"In the stressed universe, historical net Sharpe becomes {sm['sharpe']:.2f}, mean return {sm['mean_bps']:+.2f} bps/day, and max drawdown {sm['max_drawdown']:.1%}. The {sc.horizon_sessions}-session bootstrap simulation has {m['stress_sim']['p_loss']:.1%} probability of finishing below its start.",
            "ui": {"type": "multiverse"},
        })
        result["speech"] = result["answer"]
    elif route == "black_box":
        worst = research_sessions(1).iloc[0]
        b = inspect_research_day(worst.name)
        result.update({
            "payload": b,
            "answer": f"Opening the black box for {b['date']}, one of the worst committed traded sessions. Gross was {b['gross_bps']:+.1f} bps, costs {b['cost_bps']:.1f} bps, and net {b['net_bps']:+.1f} bps. I only reconstruct evidence that exists in the daily research data.",
            "ui": {"type": "black_box"},
        })
        result["speech"] = result["answer"]
    elif route == "ghost":
        g = run_ghost_desk()
        sign = "added" if g["gate_net_value"] >= 0 else "cost"
        result.update({
            "payload": g,
            "answer": f"Ghost Desk estimates that the VIX gate {sign} ${abs(g['gate_net_value']):,.0f} versus an always-on counterfactual at the configured ${g['notional_per_side']:,.0f} per-side notional. It avoided ${g['avoided_losses']:,.0f} of losses on gate-off days while missing ${g['missed_gains']:,.0f} of gains.",
            "ui": {"type": "ghost"},
        })
        result["speech"] = result["answer"]
    elif route == "explain_day":
        d = explain_day(store, question, symbol, (ui_context or {}).get("date"))
        result.update({"payload": d, "answer": d["answer"], "speech": d["answer"], "ui": {"type": "explain_day"}})
    elif route == "profit_bridge":
        d = profit_bridge(store, question)
        result.update({"payload": d, "answer": d["answer"], "speech": d["answer"], "ui": {"type": "profit_bridge"}})
    elif route == "replay":
        d = replay_day(store, question, symbol, (ui_context or {}).get("date"))
        result.update({"payload": d, "answer": d["answer"], "speech": d["answer"], "ui": {"type": "replay"}})
    elif route == "research_trial":
        d = research_trial(question)
        result.update({
            "payload": d, "answer": d["answer"], "speech": d["answer"], "ui": {"type": "research_trial"},
            "sources": [{"title": x, "url": f"/api/document/{x}"} for x in d.get("documents", [])],
        })
    elif route == "project_state":
        # Keep the live-paper tool deterministic; the shared final Gemini pass below
        # turns this exact state into the natural-language answer. This removes an
        # unnecessary extra LLM call from the latency-critical voice path.
        state = ai_war_room.project_state(store, session)
        contract = state.get("strategy_contract") or {}
        gate = state.get("today") or {}
        gate_text = "The pre-open gate state is not recorded yet."
        if gate:
            gate_text = f"The gate is {'on' if gate.get('on') else 'off'}"
            if gate.get("vix") is not None and contract.get("vix_threshold") is not None:
                gate_text += f" with lagged VIX {float(gate['vix']):.2f} versus threshold {float(contract['vix_threshold']):.0f}."
            else:
                gate_text += "."
        answer = f"Live paper system: {contract.get('name', 'systematic strategy')}. {gate_text}"
        result.update({"payload": state, "answer": answer, "speech": answer, "ui": {"type": "project_state"}})
    elif route == "clarify":
        answer = "I caught the request, but not the target. Say live paper, gap-fade backtest, Massive study, or name the company/ticker you want me to investigate."
        result.update({"payload": {"needs_clarification": True}, "answer": answer, "speech": answer, "ui": {"type": "clarify"}})
    elif route == "scope_refusal":
        answer = "I’m specialized in Quant Crucible: quantitative trading research, market/company investigation, recorded strategy evidence, execution, risk, replay and stress testing. I can’t answer unrelated general-knowledge questions here. Ask me about a company as an investment, a trading day, our research, costs, risk controls, or the evidence behind a claim."
        result.update({"payload": {"scope": "quant-trading-only"}, "answer": answer, "speech": answer, "ui": {"type": "scope_refusal"}})
    else:
        raise RuntimeError(f"Unhandled analytical route: {route}")

    # Second Gemini pass: synthesize the deterministic result + repository evidence into a
    # question-specific answer. Voice and text both use this exact path.
    explained = _gemini_explain(question, result, context, ui_context)
    if explained:
        result["answer"] = explained
        result["speech"] = explained
        if "Repository evidence retrieval" not in result["tool_trace"]:
            result["tool_trace"].insert(1, "Repository evidence retrieval")
        result["tool_trace"].append("Gemini evidence-grounded synthesis")

    from .presentation import turn_to_view_model
    result["view_model"] = turn_to_view_model(result)
    return result
