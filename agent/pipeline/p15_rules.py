"""
Stage 15 — Rule Engine
========================
Stores and evaluates board-level design rules (DRC constraints):
clearance, trace width, via drill size, layer count, copper weight.

Rules are derived from:
  1. IPC-2221 generic class B (default)
  2. Overrides from requirements constraints dict
  3. Fabricator-specific profiles (JLCPCB 2-layer budget)

Output
------
  state.rules populated (DesignRules).
  StageResult.data["rules"] = dict of active rule values.
"""

from __future__ import annotations

import time
from typing import Any, Dict

from agent.core.models import (
    DesignRules, DesignState, Issue, Severity,
    StageResult, StageStatus,
)

# ──────────────────────────────────────────────────────────────────────────────
# Fabricator profiles
# ──────────────────────────────────────────────────────────────────────────────

_PROFILES: Dict[str, DesignRules] = {
    "jlcpcb_2layer": DesignRules(
        min_trace_width=0.127,
        min_clearance=0.127,
        min_via_drill=0.3,
        min_via_annular=0.15,
        max_layers=2,
        copper_weight=1.0,
        board_thickness=1.6,
        keepout_margin=0.5,
    ),
    "oshpark_4layer": DesignRules(
        min_trace_width=0.1524,
        min_clearance=0.1524,
        min_via_drill=0.254,
        min_via_annular=0.127,
        max_layers=4,
        copper_weight=1.0,
        board_thickness=1.6,
        keepout_margin=0.5,
    ),
    "ipc2221_classB": DesignRules(
        min_trace_width=0.25,
        min_clearance=0.25,
        min_via_drill=0.3,
        min_via_annular=0.15,
        max_layers=2,
        copper_weight=1.0,
        board_thickness=1.6,
        keepout_margin=0.5,
    ),
}


def resolve_rules(constraints: Dict[str, Any]) -> DesignRules:
    """
    Build DesignRules from requirements constraints.
    Falls back to JLCPCB 2-layer profile if no profile specified.
    """
    profile_name = constraints.get("fab_profile", "jlcpcb_2layer")
    base = _PROFILES.get(profile_name, _PROFILES["jlcpcb_2layer"])

    # Allow per-key overrides from constraints dict
    overrides: Dict[str, Any] = {}
    field_map = {
        "min_trace_width":  "min_trace_width",
        "min_clearance":    "min_clearance",
        "min_via_drill":    "min_via_drill",
        "max_layers":       "max_layers",
        "copper_weight":    "copper_weight",
        "board_thickness":  "board_thickness",
    }
    for user_key, field in field_map.items():
        if user_key in constraints:
            overrides[field] = constraints[user_key]

    from dataclasses import replace
    return replace(base, **overrides)


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()

    constraints = {}
    if state.requirements:
        constraints = state.requirements.constraints

    rules = resolve_rules(constraints)
    state.rules = rules

    from dataclasses import asdict
    return StageResult(
        stage="p15_rules",
        status=StageStatus.PASSED,
        data={"rules": asdict(rules)},
        duration=time.monotonic() - t0,
    )
