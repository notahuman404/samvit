"""
Stage 24 — Reviewer / Critic Agent
=====================================
Gemini call #3 — the entire critique pipeline in ONE call:
  1. Failure Classification  — what type of failure is this?
  2. Root Cause Analysis     — why did it fail?
  3. Impact Analysis         — what else does this affect?
  4. Repair Plan             — concrete, scoped fix instructions

The prompt includes the full design state summary + all validation
results so that Gemini can reason across the whole picture at once.

Output
------
  state.review populated (ReviewReport)
  StageResult.data["review"] = review dict
  StageResult.data["repair_instructions"] = list of RepairInstruction dicts
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from agent.core.models import (
    DesignMetrics, DesignState, Issue, RepairInstruction,
    ReviewReport, Severity, StageResult, StageStatus,
)

SYSTEM_PROMPT = """You are a senior PCB design reviewer and fault-analysis engineer.
You receive a complete hardware design snapshot and all validation results.
Your job is to identify every problem, classify it, trace it to its root cause,
assess cascading impact, and produce a precise, scoped repair plan.
You communicate only in valid JSON. No prose outside the JSON block."""

REVIEW_PROMPT_TEMPLATE = """
=== HARDWARE DESIGN REVIEW REQUEST ===

Iteration: {iteration}

--- Design Summary ---
Project      : {project_name}
Components   : {component_count}
Nets         : {net_count}
Board area   : {board_area_mm2} mm²
BOM cost     : ${bom_cost_usd}

--- Validation Results ---
ERC errors   : {erc_errors}
DRC errors   : {drc_errors}
Power draw   : {power_mw} mW
Battery life : {battery_h} h
Max temp     : {max_temp_c} °C
Sim pass rate: {sim_pass_rate}

--- ERC Error Details ---
{erc_detail}

--- DRC Error Details ---
{drc_detail}

--- Simulation Results ---
{sim_detail}

--- Thermal Hotspots ---
{thermal_detail}

--- Power Analysis ---
{power_detail}

--- Short-Circuit Checks ---
{sc_detail}

--- Compatibility Issues ---
{compat_detail}

=== YOUR TASK (all four steps in ONE response) ===

1. FAILURE CLASSIFICATION
   For each distinct failure: classify as one of
   [POWER_ISSUE | SIGNAL_INTEGRITY | COMPONENT_MISMATCH |
    LAYOUT_VIOLATION | MISSING_COMPONENT | THERMAL_RISK |
    SHORT_CIRCUIT | SIMULATION_FAILURE | OTHER]

2. ROOT CAUSE ANALYSIS
   Trace each failure to its actual cause in the design.

3. IMPACT ANALYSIS
   List every other stage/component/net that is affected by each root cause.

4. REPAIR PLAN
   For each failure, produce a specific, smallest-scope repair instruction:
   - Which stage to target
   - What action to take (replace_part | reroute_net | add_component | adjust_value | change_footprint | split_net)
   - Which component / net / rule is affected
   - Exact new value / replacement part / connection change

=== OUTPUT FORMAT ===

Respond with ONLY this JSON (no markdown fences, no extra text):

{{
  "passed": false,
  "summary": "One paragraph summary of the design's overall state",
  "root_causes": ["list", "of", "root", "cause", "strings"],
  "failures": [
    {{
      "id": "F001",
      "classification": "POWER_ISSUE",
      "description": "...",
      "root_cause": "...",
      "impact": ["stage_or_component_affected", "..."],
      "severity": "ERROR"
    }}
  ],
  "repairs": [
    {{
      "failure_id": "F001",
      "target_stage": "p08_part_selection",
      "action": "replace_part",
      "component": "power_management",
      "priority": 1,
      "detail": {{
        "old_part": "TPS63020",
        "new_part": "TPS62740",
        "reason": "Lower quiescent current reduces idle power from 50µA to 360nA"
      }}
    }}
  ]
}}
"""


def _format_issues(issues: List[Dict[str, Any]], limit: int = 10) -> str:
    if not issues:
        return "(none)"
    lines = []
    for i in issues[:limit]:
        lines.append(f"  [{i.get('code','?')}] {i.get('severity','?')}: {i.get('message','')[:120]}")
    if len(issues) > limit:
        lines.append(f"  ... and {len(issues) - limit} more")
    return "\n".join(lines)


def _build_prompt(state: DesignState) -> str:
    m    = state.metrics
    erc  = state.stage_results.get("p16_erc")
    drc  = state.stage_results.get("p17_drc")
    sim  = state.stage_results.get("p21_simulation")
    thr  = state.stage_results.get("p19_thermal")
    pwr  = state.stage_results.get("p18_power")
    sc   = state.stage_results.get("p20_short_circuit")
    compat = state.stage_results.get("p09_compatibility")

    def _issues(result: Optional[StageResult], key: str) -> str:
        if result is None:
            return "(not run)"
        return _format_issues(result.data.get(key, []))

    return REVIEW_PROMPT_TEMPLATE.format(
        iteration=state.iteration,
        project_name=state.requirements.name if state.requirements else "Unknown",
        component_count=m.component_count if m else "?",
        net_count=m.net_count if m else "?",
        board_area_mm2=m.board_area_mm2 if m else "?",
        bom_cost_usd=m.bom_cost_usd if m else "?",
        erc_errors=m.erc_errors if m else "?",
        drc_errors=m.drc_errors if m else "?",
        power_mw=m.power_draw_mw if m else "?",
        battery_h=m.estimated_battery_h if m else "?",
        max_temp_c=m.max_temp_c if m else "?",
        sim_pass_rate=m.sim_pass_rate if m else "?",
        erc_detail=_issues(erc, "erc_errors"),
        drc_detail=_issues(drc, "drc_errors"),
        sim_detail=json.dumps(sim.data.get("results", [])[:5], indent=2) if sim else "(not run)",
        thermal_detail=json.dumps(
            (thr.data.get("hotspots", [])[:5] if thr else []), indent=2
        ),
        power_detail=json.dumps(
            {k: v for k, v in (pwr.data if pwr else {}).items()
             if k != "per_rail"}, indent=2
        ) if pwr else "(not run)",
        sc_detail=_issues(sc, "sc_errors"),
        compat_detail=_issues(compat, "issues") if compat else "(not run)",
    )


def _parse_review(raw: Dict[str, Any], iteration: int) -> ReviewReport:
    repairs: List[RepairInstruction] = []
    for r in raw.get("repairs", []):
        repairs.append(RepairInstruction(
            target_stage=r.get("target_stage", "unknown"),
            action=r.get("action", "adjust_value"),
            component=r.get("component", ""),
            detail=r.get("detail", {}),
            priority=int(r.get("priority", 1)),
        ))
    repairs.sort(key=lambda x: x.priority)

    return ReviewReport(
        passed=bool(raw.get("passed", False)),
        summary=raw.get("summary", ""),
        root_causes=[f.get("root_cause", "") for f in raw.get("failures", [])],
        repairs=repairs,
        iteration=iteration,
    )


def _extract_json(text: str) -> Dict[str, Any]:
    text = re.sub(r"```json\s*", "", text.strip())
    text = re.sub(r"```\s*", "", text)
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1:
        raise ValueError("No JSON in reviewer response.")
    return json.loads(text[start:end])


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

async def run_async(state: DesignState, gemini_manager: Any) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    if state.metrics is None:
        return StageResult(
            stage="p24_reviewer",
            status=StageStatus.FAILED,
            issues=[Issue("REV_NO_METRICS", Severity.ERROR,
                          "Metrics (stage 23) must run before reviewer.", "reviewer")],
            duration=time.monotonic() - t0,
        )

    # Fast-pass: if everything is clean, skip expensive Gemini call
    m = state.metrics
    if (m.erc_errors == 0 and m.drc_errors == 0 and
            m.sim_pass_rate >= 0.9 and m.max_temp_c < 85.0):
        review = ReviewReport(
            passed=True,
            summary="All checks passed. Design looks good.",
            root_causes=[],
            repairs=[],
            iteration=state.iteration,
        )
        state.review = review
        return StageResult(
            stage="p24_reviewer",
            status=StageStatus.PASSED,
            data={"review": asdict(review), "repair_instructions": []},
            duration=time.monotonic() - t0,
        )

    prompt = _build_prompt(state)

    try:
        raw_response = await gemini_manager.call_gemini(
            prompt=prompt,
            task="heavy",
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
        )
        raw_dict = _extract_json(raw_response)
        review   = _parse_review(raw_dict, state.iteration)

    except Exception as exc:
        issues.append(Issue(
            code="REV_GEMINI_ERROR",
            severity=Severity.WARNING,
            message=f"Reviewer Gemini call failed: {exc}. Using heuristic review.",
            source="reviewer",
        ))
        # Heuristic fallback: generate repairs from stage errors directly
        repairs: List[RepairInstruction] = []
        if m.erc_errors > 0:
            repairs.append(RepairInstruction(
                target_stage="p10_schematic_graph",
                action="reroute_net",
                component="all",
                detail={"reason": "ERC errors detected — revisit net connections"},
                priority=1,
            ))
        if m.drc_errors > 0:
            repairs.append(RepairInstruction(
                target_stage="p13_placement",
                action="adjust_value",
                component="all",
                detail={"reason": "DRC errors detected — spacing/clearance issue"},
                priority=2,
            ))
        if m.sim_pass_rate < 0.75:
            repairs.append(RepairInstruction(
                target_stage="p08_part_selection",
                action="replace_part",
                component="power_management",
                detail={"reason": "Simulation failures — power rail may be undersized"},
                priority=1,
            ))
        if m.estimated_battery_h >= 87600:
            repairs.append(RepairInstruction(
                target_stage="p05_datasheet",
                action="adjust_value",
                component="all",
                detail={"reason": "Unrealistic battery life — verify component current draw specs in datasheets"},
                priority=1,
            ))
        review = ReviewReport(
            passed=False,
            summary="Heuristic review (Gemini unavailable). Multiple issues detected.",
            root_causes=["Gemini call failed; using rule-based root cause analysis."],
            repairs=repairs,
            iteration=state.iteration,
        )

    state.review = review

    return StageResult(
        stage="p24_reviewer",
        status=StageStatus.PASSED if review.passed else StageStatus.FAILED,
        data={
            "review":              asdict(review),
            "repair_instructions": [asdict(r) for r in review.repairs],
            "repair_count":        len(review.repairs),
        },
        issues=issues,
        metrics={"repair_count": float(len(review.repairs))},
        duration=time.monotonic() - t0,
    )


def run(state: DesignState, gemini_manager: Any) -> StageResult:
    return asyncio.run(run_async(state, gemini_manager))
