"""
Stage 30 — Human Override Layer
==================================
Lets the operator inject forced decisions at any point in the pipeline:
  • Force a specific part selection for a subsystem
  • Lock a design rule value (prevent the repair agent from changing it)
  • Skip a specific stage (mark it as passed without running)
  • Inject a custom net or connection into the schematic
  • Set any DesignState field directly

Overrides are loaded from:
  1. A JSON file (human_overrides.json in the working directory)
  2. Direct Python dict passed to run()

Override format:
  {
    "force_parts": {"subsystem_name": "part_number"},
    "lock_rules":  {"min_trace_width": 0.25},
    "skip_stages": ["p19_thermal"],
    "force_nets":  [{"name": "FORCE_NET", "nodes": [["U1","VDD"],["U2","VDD"]]}],
    "notes":       "Why these overrides were applied"
  }
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set

from agent.core.models import (
    DesignRules, DesignState, Issue, Net, NetNode,
    Severity, StageResult, StageStatus,
)

OVERRIDE_FILE = "human_overrides.json"


def load_overrides(path: str = OVERRIDE_FILE) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def apply_overrides(state: DesignState, overrides: Dict[str, Any]) -> List[str]:
    """Apply all override directives. Returns list of applied action messages."""
    applied: List[str] = []

    # Force part selections
    force_parts: Dict[str, str] = overrides.get("force_parts", {})
    if force_parts:
        sel_result = state.stage_results.get("p08_part_selection")
        if sel_result:
            for sub, pn in force_parts.items():
                sel_result.data.setdefault("selected", {})[sub] = pn
                applied.append(f"[FORCE_PART] {sub} → {pn}")

    # Lock design rules
    lock_rules: Dict[str, Any] = overrides.get("lock_rules", {})
    if lock_rules:
        if state.rules is None:
            state.rules = DesignRules()
        for field, value in lock_rules.items():
            if hasattr(state.rules, field):
                setattr(state.rules, field, float(value))
                applied.append(f"[LOCK_RULE] {field} = {value}")

    # Force net injections
    force_nets: List[Dict] = overrides.get("force_nets", [])
    if force_nets and state.schematic:
        for net_def in force_nets:
            nodes = [NetNode(n[0], n[1]) for n in net_def.get("nodes", [])]
            new_net = Net(name=net_def["name"], nodes=nodes)
            # Remove existing net with same name if present
            state.schematic.nets = [n for n in state.schematic.nets if n.name != new_net.name]
            state.schematic.nets.append(new_net)
            applied.append(f"[FORCE_NET] {new_net.name} with {len(nodes)} nodes")

    # Stage skip flags
    skip_stages: List[str] = overrides.get("skip_stages", [])
    for stage in skip_stages:
        if stage not in state.stage_results:
            # Inject a synthetic SKIPPED result
            state.stage_results[stage] = StageResult(
                stage=stage,
                status=StageStatus.SKIPPED,
                data={"reason": "Human override — stage skipped"},
            )
            applied.append(f"[SKIP_STAGE] {stage}")

    return applied


def run(
    state: DesignState,
    overrides: Optional[Dict[str, Any]] = None,
    override_file: str = OVERRIDE_FILE,
) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    # Load from file if available
    file_overrides = load_overrides(override_file)
    effective = {**file_overrides, **(overrides or {})}

    if not effective:
        return StageResult(
            stage="p30_human_override",
            status=StageStatus.SKIPPED,
            data={"applied": [], "notes": "No overrides configured."},
            duration=time.monotonic() - t0,
        )

    applied = apply_overrides(state, effective)
    notes   = effective.get("notes", "")

    # After overrides, mark affected downstream stages as needing re-run
    if effective.get("force_parts") or effective.get("force_nets"):
        for stage in ["p09_compatibility", "p10_schematic_graph", "p16_erc",
                      "p17_drc", "p18_power", "p21_simulation", "p23_metrics"]:
            state.stage_results.pop(stage, None)

    return StageResult(
        stage="p30_human_override",
        status=StageStatus.PASSED,
        data={
            "applied":  applied,
            "notes":    notes,
            "override_count": len(applied),
        },
        issues=issues,
        metrics={"override_count": float(len(applied))},
        duration=time.monotonic() - t0,
    )
