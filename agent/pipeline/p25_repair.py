"""
Stage 25 — Repair / Iteration Agent
=======================================
Applies the RepairInstructions produced by Stage 24 to the DesignState.

Repair loop per instruction:
  1. Classify the repair scope (which stage is affected)
  2. Apply the minimum change to fix that specific issue
  3. Mark only the affected stages as needing re-run
  4. Return the set of stages that must be re-validated

This stage does NOT call Gemini — it applies concrete changes.
Gemini was already called in Stage 24 with the full context, so the
repair instructions are deterministic by the time we get here.

Output
------
  StageResult.data["applied_repairs"]  = list of applied instructions
  StageResult.data["stages_to_rerun"]  = list of stage IDs to re-validate
  StageResult.data["skipped_repairs"]  = list of instructions that couldn't apply
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set

from agent.core.models import (
    Component, DesignRules, DesignState, Issue, RepairInstruction,
    Severity, StageResult, StageStatus,
)


# ──────────────────────────────────────────────────────────────────────────────
# Repair handlers
# ──────────────────────────────────────────────────────────────────────────────

def _repair_replace_part(
    state: DesignState,
    instr: RepairInstruction,
) -> tuple[bool, str, Set[str]]:
    """
    Attempt to replace a part in the selected BOM.
    Returns (success, message, stages_to_rerun).
    """
    detail = instr.detail
    sub_name = instr.component
    new_part = detail.get("new_part", "")

    sel_result = state.stage_results.get("p08_part_selection")
    if sel_result is None:
        return False, "Part selection result not found.", set()

    selected: Dict[str, str] = sel_result.data.get("selected", {})

    # Find a match by subsystem name or partial part number
    matched_sub = None
    for s_name in selected:
        if sub_name.lower() in s_name.lower() or s_name.lower() in sub_name.lower():
            matched_sub = s_name
            break

    if matched_sub is None:
        # Try to match by part number
        old_part = detail.get("old_part", "")
        if old_part:
            for s_name, pn in selected.items():
                if old_part.lower() in pn.lower():
                    matched_sub = s_name
                    break

    if matched_sub is None:
        return False, f"Could not find subsystem '{sub_name}' in selected parts.", set()

    # Look for new_part in component database
    new_comp = state.components.get(new_part)
    if new_comp is None:
        # Try partial match
        for pn, comp in state.components.items():
            if new_part.lower() in pn.lower() or pn.lower() in new_part.lower():
                new_comp = comp
                new_part = pn
                break

    if new_comp is None:
        return (
            False,
            f"Replacement part '{new_part}' not found in component database.",
            set(),
        )

    # Apply the swap
    old_pn = selected[matched_sub]
    selected[matched_sub] = new_part
    sel_result.data["selected"] = selected

    # Invalidate downstream stages
    downstream = {
        "p09_compatibility", "p10_schematic_graph", "p11_schematic_gen",
        "p12_footprint", "p13_placement", "p14_routing",
        "p16_erc", "p17_drc", "p18_power", "p19_thermal",
        "p20_short_circuit", "p21_simulation", "p23_metrics",
    }
    for stage in downstream:
        if stage in state.stage_results:
            del state.stage_results[stage]

    return True, f"Replaced '{old_pn}' with '{new_part}' for subsystem '{matched_sub}'.", downstream


def _repair_add_component(
    state: DesignState,
    instr: RepairInstruction,
) -> tuple[bool, str, Set[str]]:
    """Add a missing component to the BOM (e.g. decoupling cap, protection diode)."""
    detail   = instr.detail
    new_part = detail.get("new_part", detail.get("part", ""))
    category = detail.get("category", "PASSIVE")
    sub_name = instr.component or f"added_{new_part[:8]}"

    # Create a minimal component record if not already in DB
    if new_part and new_part not in state.components:
        state.components[new_part] = Component(
            part_number=new_part,
            manufacturer="Generic",
            category=category,
            description=detail.get("reason", f"Added by repair agent: {new_part}"),
            voltage_min=0.0,
            voltage_max=5.0,
            current_ma=1.0,
            package=detail.get("package", "0402"),
            footprint=detail.get("footprint", "Resistor_SMD:R_0402_1005Metric"),
            cost_usd=float(detail.get("cost_usd", 0.10)),
            notes=detail.get("reason", ""),
            confidence=0.7,
        )

    # Add to selected BOM
    sel_result = state.stage_results.get("p08_part_selection")
    if sel_result and new_part:
        sel_result.data.setdefault("selected", {})[sub_name] = new_part
        sel_result.data["bom_cost_usd"] = round(
            sel_result.data.get("bom_cost_usd", 0.0) + state.components[new_part].cost_usd, 2
        )

    downstream = {
        "p09_compatibility", "p10_schematic_graph", "p11_schematic_gen",
        "p12_footprint", "p13_placement", "p14_routing",
        "p16_erc", "p17_drc", "p18_power", "p19_thermal",
        "p21_simulation", "p23_metrics",
    }
    for stage in downstream:
        state.stage_results.pop(stage, None)

    return True, f"Added component '{new_part}' ({category}) as '{sub_name}'.", downstream


def _repair_adjust_value(
    state: DesignState,
    instr: RepairInstruction,
) -> tuple[bool, str, Set[str]]:
    """Adjust a design rule value (trace width, clearance, etc.)."""
    detail = instr.detail
    field  = detail.get("field", "")
    value  = detail.get("value")

    if not field or value is None:
        return False, "adjust_value requires 'field' and 'value' in detail.", set()

    if state.rules and hasattr(state.rules, field):
        setattr(state.rules, field, float(value))
        downstream = {"p14_routing", "p17_drc", "p23_metrics"}
        for stage in downstream:
            state.stage_results.pop(stage, None)
        return True, f"Adjusted rule '{field}' to {value}.", downstream

    return False, f"Rule field '{field}' not found in DesignRules.", set()


def _repair_reroute_net(
    state: DesignState,
    instr: RepairInstruction,
) -> tuple[bool, str, Set[str]]:
    """Mark routing as needing a re-run (actual re-route happens in Stage 14)."""
    # Clear routing and DRC results so they re-run
    downstream = {"p14_routing", "p17_drc", "p20_short_circuit", "p21_simulation", "p23_metrics"}
    for stage in downstream:
        state.stage_results.pop(stage, None)
    # Clear layout traces
    if state.layout:
        state.layout.traces = []
        state.layout.via_count = 0
    return True, "Cleared routing for re-run.", downstream


def _repair_change_footprint(
    state: DesignState,
    instr: RepairInstruction,
) -> tuple[bool, str, Set[str]]:
    """Update a component's footprint."""
    detail    = instr.detail
    pn        = instr.component
    new_fp    = detail.get("new_footprint", "")
    comp      = state.components.get(pn)
    if comp and new_fp:
        comp.footprint = new_fp
        downstream = {"p12_footprint", "p13_placement", "p14_routing", "p17_drc", "p23_metrics"}
        for stage in downstream:
            state.stage_results.pop(stage, None)
        return True, f"Changed footprint of '{pn}' to '{new_fp}'.", downstream
    return False, f"Component '{pn}' not found or no new_footprint provided.", set()


# ──────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────────

_HANDLERS = {
    "replace_part":     _repair_replace_part,
    "add_component":    _repair_add_component,
    "adjust_value":     _repair_adjust_value,
    "reroute_net":      _repair_reroute_net,
    "change_footprint": _repair_change_footprint,
}


def apply_repairs(
    state: DesignState,
    repairs: List[RepairInstruction],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Set[str]]:
    applied:  List[Dict[str, Any]] = []
    skipped:  List[Dict[str, Any]] = []
    all_rerun: Set[str]            = set()

    for instr in repairs:
        handler = _HANDLERS.get(instr.action)
        if handler is None:
            skipped.append({
                "instruction": asdict(instr),
                "reason": f"Unknown action '{instr.action}'.",
            })
            continue

        try:
            success, msg, rerun = handler(state, instr)
            if success:
                applied.append({"instruction": asdict(instr), "message": msg})
                all_rerun |= rerun
            else:
                skipped.append({"instruction": asdict(instr), "reason": msg})
        except Exception as exc:
            skipped.append({"instruction": asdict(instr), "reason": str(exc)})

    return applied, skipped, all_rerun


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    if state.review is None:
        return StageResult(
            stage="p25_repair",
            status=StageStatus.FAILED,
            issues=[Issue("REPAIR_NO_REVIEW", Severity.ERROR,
                          "Reviewer (stage 24) must run before repair.", "repair")],
            duration=time.monotonic() - t0,
        )

    if state.review.passed:
        return StageResult(
            stage="p25_repair",
            status=StageStatus.SKIPPED,
            data={"applied_repairs": [], "stages_to_rerun": [], "skipped_repairs": []},
            duration=time.monotonic() - t0,
        )

    repairs = state.review.repairs
    applied, skipped, stages_to_rerun = apply_repairs(state, repairs)

    if skipped:
        issues.append(Issue(
            code="REPAIR_SKIPPED",
            severity=Severity.WARNING,
            message=f"{len(skipped)} repair instruction(s) could not be applied: "
                    f"{[s['reason'][:60] for s in skipped]}",
            source="repair",
        ))

    if not applied:
        issues.append(Issue(
            code="REPAIR_NONE_APPLIED",
            severity=Severity.ERROR,
            message="No repairs could be applied. Manual intervention required.",
            source="repair",
        ))

    state.iteration += 1
    has_errors = any(i.is_error() for i in issues)

    return StageResult(
        stage="p25_repair",
        status=StageStatus.REPAIRED if applied and not has_errors else StageStatus.FAILED,
        data={
            "applied_repairs":  applied,
            "skipped_repairs":  skipped,
            "stages_to_rerun":  sorted(stages_to_rerun),
            "new_iteration":    state.iteration,
        },
        issues=issues,
        metrics={
            "applied_count": float(len(applied)),
            "skipped_count": float(len(skipped)),
        },
        duration=time.monotonic() - t0,
    )
