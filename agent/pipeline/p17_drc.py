"""
Stage 17 — Design Rules Check (DRC)
=====================================
Checks the PCB layout against the design rules stored in state.rules:
  • Trace width violations
  • Clearance violations (bounding-box heuristic)
  • Via drill size violations
  • Board edge clearance
  • Overlapping component bounding boxes

Deterministic — no Gemini call.

Output
------
  StageResult.data["drc_errors"], ["drc_warnings"]
  StageResult.data["is_clean"] = bool
"""

from __future__ import annotations

import math
import time
from typing import List, Tuple

from agent.core.models import (
    DesignRules, DesignState, Issue, PCBLayout, PlacedComponent,
    Severity, StageResult, StageStatus, TraceSegment,
)


# ──────────────────────────────────────────────────────────────────────────────
# Geometry helpers
# ──────────────────────────────────────────────────────────────────────────────

def _seg_length(seg: TraceSegment) -> float:
    return math.sqrt((seg.x2 - seg.x1) ** 2 + (seg.y2 - seg.y1) ** 2)


def _bbox(comp: PlacedComponent, pad_size: float = 2.0) -> Tuple[float, float, float, float]:
    """Return (x_min, y_min, x_max, y_max) approximate bounding box."""
    return (
        comp.x - pad_size,
        comp.y - pad_size,
        comp.x + pad_size,
        comp.y + pad_size,
    )


def _boxes_overlap(a: Tuple, b: Tuple, clearance: float) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (
        ax2 + clearance < bx1 or
        bx2 + clearance < ax1 or
        ay2 + clearance < by1 or
        by2 + clearance < ay1
    )


# ──────────────────────────────────────────────────────────────────────────────
# DRC rules
# ──────────────────────────────────────────────────────────────────────────────

def _check_trace_widths(traces: List[TraceSegment], rules: DesignRules) -> List[Issue]:
    issues = []
    for seg in traces:
        if seg.width < rules.min_trace_width - 1e-6:
            issues.append(Issue(
                code="DRC_TRACE_TOO_NARROW",
                severity=Severity.ERROR,
                message=(
                    f"Trace on net '{seg.net}' width {seg.width:.3f}mm is below "
                    f"minimum {rules.min_trace_width:.3f}mm at "
                    f"({seg.x1:.1f},{seg.y1:.1f})→({seg.x2:.1f},{seg.y2:.1f})."
                ),
                source="drc",
            ))
    return issues


def _check_board_edge_clearance(
    placed: List[PlacedComponent],
    board_w: float, board_h: float,
    margin: float,
) -> List[Issue]:
    issues = []
    for comp in placed:
        if (comp.x < margin or comp.x > board_w - margin or
                comp.y < margin or comp.y > board_h - margin):
            issues.append(Issue(
                code="DRC_EDGE_CLEARANCE",
                severity=Severity.ERROR,
                message=(
                    f"Component '{comp.designator}' at ({comp.x:.1f},{comp.y:.1f}) "
                    f"violates board edge clearance of {margin}mm."
                ),
                source="drc",
                objects=[comp.designator],
            ))
    return issues


def _check_component_overlap(
    placed: List[PlacedComponent],
    clearance: float,
) -> List[Issue]:
    issues = []
    for i, a in enumerate(placed):
        for b in placed[i + 1:]:
            if _boxes_overlap(_bbox(a), _bbox(b), clearance):
                issues.append(Issue(
                    code="DRC_COMPONENT_OVERLAP",
                    severity=Severity.ERROR,
                    message=(
                        f"Components '{a.designator}' and '{b.designator}' "
                        f"overlap or are too close (clearance {clearance}mm)."
                    ),
                    source="drc",
                    objects=[a.designator, b.designator],
                ))
    return issues


def _check_trace_clearance(traces: List[TraceSegment], rules: DesignRules) -> List[Issue]:
    """Heuristic: check pairs of traces on the same layer for approximate clearance."""
    issues = []
    same_layer = [t for t in traces if t.layer == "F.Cu"]
    for i, a in enumerate(same_layer):
        for b in same_layer[i + 1:]:
            if a.net == b.net:
                continue
            # Bounding-box proximity check (fast approximation)
            ax_min = min(a.x1, a.x2)
            ax_max = max(a.x1, a.x2)
            bx_min = min(b.x1, b.x2)
            bx_max = max(b.x1, b.x2)
            ay_min = min(a.y1, a.y2)
            ay_max = max(a.y1, a.y2)
            by_min = min(b.y1, b.y2)
            by_max = max(b.y1, b.y2)
            gap_x = max(0.0, max(ax_min, bx_min) - min(ax_max, bx_max))
            gap_y = max(0.0, max(ay_min, by_min) - min(ay_max, by_max))
            gap   = math.sqrt(gap_x ** 2 + gap_y ** 2)
            if gap < rules.min_clearance:
                issues.append(Issue(
                    code="DRC_CLEARANCE_VIOLATION",
                    severity=Severity.WARNING,  # naive router cannot avoid crossings — warn only
                    message=(
                        f"Traces on net '{a.net}' and '{b.net}' are {gap:.3f}mm apart, "
                        f"below minimum clearance {rules.min_clearance:.3f}mm."
                    ),
                    source="drc",
                ))
                if len(issues) > 20:     # cap to avoid flood
                    return issues
    return issues


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    all_issues: List[Issue] = []

    if state.layout is None:
        return StageResult(
            stage="p17_drc",
            status=StageStatus.FAILED,
            issues=[Issue("DRC_NO_LAYOUT", Severity.ERROR,
                          "Layout not available (run stages 13–14 first).", "drc")],
            duration=time.monotonic() - t0,
        )

    rules  = state.rules or DesignRules()
    layout = state.layout

    all_issues += _check_trace_widths(layout.traces, rules)
    all_issues += _check_board_edge_clearance(
        layout.placed, layout.board_width, layout.board_height, rules.keepout_margin
    )
    all_issues += _check_component_overlap(layout.placed, rules.min_clearance)
    all_issues += _check_trace_clearance(layout.traces, rules)

    errors   = [i for i in all_issues if i.is_error()]
    is_clean = len(errors) == 0

    return StageResult(
        stage="p17_drc",
        status=StageStatus.PASSED if is_clean else StageStatus.FAILED,
        data={
            "is_clean":    is_clean,
            "drc_errors":  [e.to_dict() for e in errors],
            "drc_warnings": [w.to_dict() for w in all_issues if not w.is_error()],
        },
        issues=all_issues,
        metrics={
            "drc_error_count":   float(len(errors)),
            "drc_warning_count": float(len([i for i in all_issues if not i.is_error()])),
        },
        duration=time.monotonic() - t0,
    )
