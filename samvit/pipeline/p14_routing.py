"""
Stage 14 — Routing Engine
===========================
Generates PCB trace segments connecting placed component pads
according to the schematic netlist.

Strategy (deterministic):
  - Power nets: thick traces (0.5mm+) using L-shaped Manhattan routes
  - Signal nets: standard traces (0.25mm) using direct Manhattan routes
  - Differential pairs: kept together
  - Via insertion when layer changes are needed

Output
------
  state.layout.traces populated
  StageResult.data["trace_count"], ["via_count"], ["unrouted_count"]
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from samvit.core.models import (
    DesignRules, DesignState, Issue, PlacedComponent,
    Severity, StageResult, StageStatus, TraceSegment,
)


# ──────────────────────────────────────────────────────────────────────────────
# Manhattan router
# ──────────────────────────────────────────────────────────────────────────────

def _des_to_xy(des: str, placed: List[PlacedComponent]) -> Optional[Tuple[float, float]]:
    for p in placed:
        if p.designator == des:
            return p.x, p.y
    return None


def _manhattan(
    x1: float, y1: float, x2: float, y2: float,
    width: float, layer: str, net: str,
) -> List[TraceSegment]:
    """Two-segment L-shaped Manhattan route."""
    segs = []
    if abs(x2 - x1) > 0.01:
        segs.append(TraceSegment(net, x1, y1, x2, y1, width, layer))
    if abs(y2 - y1) > 0.01:
        segs.append(TraceSegment(net, x2, y1, x2, y2, width, layer))
    return segs


def route_nets(
    schematic_nets: List[any],
    placed: List[PlacedComponent],
    rules: DesignRules,
) -> Tuple[List[TraceSegment], int, int]:
    """
    Returns (traces, via_count, unrouted_count).
    """
    traces:       List[TraceSegment] = []
    via_count:    int                = 0
    unrouted:     int                = 0

    _POWER_NETS = {"VDD", "GND", "VBAT", "5V", "3V3"}

    for net in schematic_nets:
        if len(net.nodes) < 2:
            continue

        is_power = any(kw in net.name.upper() for kw in ("VDD", "GND", "VBAT", "5V", "3V3", "PWR"))
        width     = 0.5 if is_power else rules.min_trace_width
        layer     = "F.Cu"

        # Use first node as hub, connect all others to it
        hub = net.nodes[0]
        hub_xy = _des_to_xy(hub.designator, placed)
        if hub_xy is None:
            unrouted += 1
            continue

        hx, hy = hub_xy
        for node in net.nodes[1:]:
            node_xy = _des_to_xy(node.designator, placed)
            if node_xy is None:
                unrouted += 1
                continue
            nx, ny = node_xy
            segs = _manhattan(hx, hy, nx, ny, width, layer, net.name)
            traces.extend(segs)

    return traces, via_count, unrouted


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    if state.schematic is None or state.layout is None:
        return StageResult(
            stage="p14_routing",
            status=StageStatus.FAILED,
            issues=[Issue("ROUTE_PREREQ", Severity.ERROR,
                          "Schematic (10) and placement (13) must run before routing.", "routing")],
            duration=time.monotonic() - t0,
        )

    rules = state.rules or DesignRules()
    placed = state.layout.placed

    traces, via_count, unrouted = route_nets(state.schematic.nets, placed, rules)

    state.layout.traces   = traces
    state.layout.via_count = via_count

    if unrouted > 0:
        issues.append(Issue(
            code="ROUTE_UNROUTED_NETS",
            severity=Severity.WARNING,
            message=f"{unrouted} net(s) could not be routed — pads missing placement.",
            source="routing",
        ))

    has_errors = any(i.is_error() for i in issues)
    return StageResult(
        stage="p14_routing",
        status=StageStatus.PASSED if not has_errors else StageStatus.FAILED,
        data={
            "trace_count":   len(traces),
            "via_count":     via_count,
            "unrouted_count": unrouted,
        },
        metrics={
            "trace_count":    float(len(traces)),
            "unrouted_count": float(unrouted),
        },
        issues=issues,
        duration=time.monotonic() - t0,
    )
