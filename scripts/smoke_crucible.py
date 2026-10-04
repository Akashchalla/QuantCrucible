"""Offline smoke test for Quant Crucible's five deterministic hero systems.

No API keys and no network calls are required. The script also validates that every
result can be converted into the browser JSON view-model used by text and voice.
"""
from __future__ import annotations

import json

from live.black_box import inspect_research_day, research_sessions
from live.crucible import run_red_team
from live.ghost_desk import run_ghost_desk
from live.multiverse import Scenario, run_scenario
from live.presentation import turn_to_view_model


def check(route, payload, answer):
    vm = turn_to_view_model({
        "route": route, "payload": payload, "answer": answer, "speech": answer,
        "symbol": "SPY", "question": f"smoke {route}", "tool_trace": ["offline smoke"],
    })
    json.dumps(vm)
    return {"route": route, "metrics": len(vm["metrics"]), "charts": len(vm["charts"]), "tables": len(vm["tables"])}


def main():
    crucible = run_red_team()
    multi = run_scenario(Scenario(n_paths=150, horizon_sessions=20))
    worst = research_sessions(1).index[0]
    black = inspect_research_day(worst)
    ghost = run_ghost_desk()
    results = [
        check("crucible", crucible, f"{crucible['verdict']} {crucible['score']}/100"),
        check("multiverse", multi, "scenario complete"),
        check("black_box", black, "black box complete"),
        check("ghost", ghost, "ghost desk complete"),
    ]
    vision_contract = turn_to_view_model({
        "route": "vision", "symbol": "GOOGL", "answer": "visual contract ready",
        "payload": {"snapshot": {"price": 1, "return_1d": 0, "return_20d": 0, "realized_vol_20d": 0, "move_sigma_60d": 0},
                    "observed_visual_features": ["chart"], "cautions": ["visual context only"], "suggested_next_actions": ["verify numerically"]}
    })
    json.dumps(vision_contract)
    results.append({"route": "vision-contract", "metrics": len(vision_contract["metrics"]), "charts": 0, "tables": len(vision_contract["tables"])})
    print(json.dumps({"ok": True, "crucible_verdict": crucible["verdict"], "routes": results}, indent=2))


if __name__ == "__main__":
    main()
