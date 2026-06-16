"""
Stage 29 — Visualization / Debug View
========================================
Generates human-readable debug reports:
  • ASCII schematic summary (component list + net list)
  • Stage pipeline status table
  • Metrics dashboard (text)
  • Error/Warning digest

All output is plain text — usable in terminal or logged to file.

No Gemini call. No external dependencies.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from agent.core.models import (
    DesignState, StageResult, StageStatus,
)

_COL = 60   # column width for text reports


def _bar(label: str, value: float, max_val: float, width: int = 20) -> str:
    filled = int((value / max_val) * width) if max_val > 0 else 0
    bar    = "█" * min(filled, width) + "░" * max(0, width - filled)
    return f"{label:<20} [{bar}] {value:.1f}/{max_val:.1f}"


def render_pipeline_status(state: DesignState) -> str:
    lines = [
        "=" * _COL,
        f"  SAMVIT PIPELINE STATUS  —  Iteration {state.iteration}",
        "=" * _COL,
    ]
    stage_order = [
        "p01_requirements", "p03_architecture",
        "p05_datasheet",    "p06_component_db",
        "p07_component_search", "p08_part_selection",
        "p09_compatibility",
        "p10_schematic_graph", "p11_schematic_gen",
        "p12_footprint", "p13_placement", "p14_routing",
        "p15_rules",
        "p16_erc", "p17_drc",
        "p18_power", "p19_thermal", "p20_short_circuit",
        "p21_simulation", "p22_test_gen", "p23_metrics",
        "p24_reviewer", "p25_repair",
        "p26_kicad", "p27_exporter", "p28_logging",
    ]
    status_icon = {
        "PASSED":  "✅",
        "FAILED":  "❌",
        "RUNNING": "⏳",
        "PENDING": "⬜",
        "REPAIRED":"🔧",
        "SKIPPED": "⏭️",
    }
    for stage in stage_order:
        result = state.stage_results.get(stage)
        if result:
            icon   = status_icon.get(result.status.value, "❓")
            e_cnt  = len([i for i in result.issues if i.is_error()])
            w_cnt  = len([i for i in result.issues if not i.is_error()])
            detail = f"  E:{e_cnt} W:{w_cnt}  {result.duration:.2f}s" if (e_cnt + w_cnt) else f"  {result.duration:.2f}s"
            lines.append(f"  {icon} {stage:<30} {result.status.value:<8}{detail}")
        else:
            lines.append(f"  ⬜ {stage:<30} NOT RUN")
    return "\n".join(lines)


def render_metrics_dashboard(state: DesignState) -> str:
    m = state.metrics
    if m is None:
        return "  (metrics not yet computed)"

    lines = [
        "",
        "─" * _COL,
        "  METRICS DASHBOARD",
        "─" * _COL,
        _bar("Power draw",    m.power_draw_mw,        5000.0),
        _bar("Sim pass rate", m.sim_pass_rate * 100,   100.0),
        _bar("Battery life",  m.estimated_battery_h,   24.0),
        _bar("Max temp",      m.max_temp_c,            125.0),
        _bar("BOM cost",      m.bom_cost_usd,          200.0),
        "",
        f"  ERC errors    : {m.erc_errors}",
        f"  DRC errors    : {m.drc_errors}",
        f"  Components    : {m.component_count}",
        f"  Nets          : {m.net_count}",
        f"  Board area    : {m.board_area_mm2:.0f} mm²",
        f"  BOM cost      : ${m.bom_cost_usd:.2f}",
    ]
    return "\n".join(lines)


def render_issue_digest(state: DesignState) -> str:
    all_issues = []
    for stage_name, result in state.stage_results.items():
        for issue in result.issues:
            all_issues.append((stage_name, issue))

    if not all_issues:
        return "\n  ✅ No issues found."

    lines = ["", "─" * _COL, "  ISSUE DIGEST", "─" * _COL]
    errors   = [(s, i) for s, i in all_issues if i.is_error()]
    warnings = [(s, i) for s, i in all_issues if not i.is_error()]

    if errors:
        lines.append(f"\n  ❌ ERRORS ({len(errors)}):")
        for s, i in errors[:15]:
            lines.append(f"    [{i.code}] {s}: {i.message[:90]}")

    if warnings:
        lines.append(f"\n  ⚠️  WARNINGS ({len(warnings)}):")
        for s, i in warnings[:10]:
            lines.append(f"    [{i.code}] {s}: {i.message[:90]}")

    return "\n".join(lines)


def render_schematic_summary(state: DesignState) -> str:
    if state.schematic is None:
        return "\n  (schematic not available)"
    sch = state.schematic
    lines = ["", "─" * _COL, "  SCHEMATIC SUMMARY", "─" * _COL]
    lines.append(f"  Components ({len(sch.components)}):")
    for comp in sch.components[:20]:
        lines.append(f"    {comp.designator:<8} {comp.part_number:<25} @ ({comp.position[0]:.0f},{comp.position[1]:.0f})")
    if len(sch.components) > 20:
        lines.append(f"    ... and {len(sch.components) - 20} more")
    lines.append(f"\n  Nets ({len(sch.nets)}):")
    for net in sch.nets[:15]:
        node_str = ", ".join(f"{n.designator}.{n.pin}" for n in net.nodes[:4])
        lines.append(f"    {net.name:<20} → {node_str}")
    return "\n".join(lines)


def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()

    report = (
        render_pipeline_status(state)
        + render_metrics_dashboard(state)
        + render_issue_digest(state)
        + render_schematic_summary(state)
        + "\n" + "=" * _COL + "\n"
    )

    return StageResult(
        stage="p29_visualizer",
        status=StageStatus.PASSED,
        data={"report": report},
        duration=time.monotonic() - t0,
    )
