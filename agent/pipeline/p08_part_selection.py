"""
Stage 8 — Part Selection Engine
==================================
Chooses the single best part for each subsystem from the ranked
candidates produced by Stage 7.

Pure deterministic scoring — no Gemini call.

Output
------
  StageResult.data["selected"] = dict mapping subsystem_name → part_number
  State: populates a "selected_parts" key in stage data for downstream stages.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from agent.core.models import (
    Component, DesignState, Issue, Severity,
    StageResult, StageStatus,
)


def _pick_best(
    candidates: List[Dict[str, Any]],
    components: Dict[str, Component],
    budget_usd: Optional[float],
) -> Optional[str]:
    """Return the part_number of the best candidate after budget re-check."""
    for c in candidates:
        pn = c["part_number"]
        comp = components.get(pn)
        if comp is None:
            continue
        if budget_usd is not None and comp.cost_usd > budget_usd:
            continue
        return pn
    return None


def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    if state.architecture is None:
        return StageResult(
            stage="p08_part_selection",
            status=StageStatus.FAILED,
            issues=[Issue("SELECT_NO_ARCH", Severity.ERROR,
                          "Architecture not set.", "part_selection")],
            duration=time.monotonic() - t0,
        )

    # Retrieve candidate data from Stage 7 result
    search_result = state.stage_results.get("p07_component_search")
    if search_result is None or "candidates" not in search_result.data:
        return StageResult(
            stage="p08_part_selection",
            status=StageStatus.FAILED,
            issues=[Issue("SELECT_NO_SEARCH", Severity.ERROR,
                          "Stage 7 (component search) must run before part selection.", "part_selection")],
            duration=time.monotonic() - t0,
        )

    candidates_map: Dict[str, List[Dict[str, Any]]] = search_result.data["candidates"]

    # Per-subsystem budget: total / n_subsystems as rough guide
    req = state.requirements
    total_budget = req.budget_usd if req else None
    n_subs = len(state.architecture.subsystems) or 1
    per_sub_budget = (total_budget / n_subs) if total_budget else None

    selected: Dict[str, str] = {}
    missing:  List[str]       = []

    for sub in state.architecture.subsystems:
        candidates = candidates_map.get(sub.name, [])
        best = _pick_best(candidates, state.components, per_sub_budget)

        if best:
            selected[sub.name] = best
        else:
            if sub.priority == 1:
                issues.append(Issue(
                    code="SELECT_NO_PART",
                    severity=Severity.ERROR,
                    message=f"Could not select a part for required subsystem '{sub.name}'.",
                    source="part_selection",
                    objects=[sub.name],
                ))
            else:
                issues.append(Issue(
                    code="SELECT_OPTIONAL_MISSING",
                    severity=Severity.WARNING,
                    message=f"Optional subsystem '{sub.name}' has no matching part within budget.",
                    source="part_selection",
                    objects=[sub.name],
                ))
            missing.append(sub.name)

    bom_cost = sum(
        state.components[pn].cost_usd
        for pn in selected.values()
        if pn in state.components
    )

    has_errors = any(i.is_error() for i in issues)
    return StageResult(
        stage="p08_part_selection",
        status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
        data={
            "selected":          selected,
            "missing_subsystems": missing,
            "bom_cost_usd":      round(bom_cost, 2),
        },
        metrics={
            "selected_count": float(len(selected)),
            "bom_cost_usd":   bom_cost,
        },
        issues=issues,
        duration=time.monotonic() - t0,
    )
