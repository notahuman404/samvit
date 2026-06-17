"""
Stage 13 — Placement Engine
==============================
Assigns XY positions and rotation to each placed component on the PCB.

Strategy (deterministic, no Gemini):
  1. Power components → bottom-left cluster
  2. MCU/SBC          → centre
  3. Sensors          → top edge (close to the outside world)
  4. Actuators/Audio  → right cluster
  5. Comms            → top-right corner
  6. Passives         → scattered near their primary consumer

Output
------
  state.layout is populated with PlacedComponent list.
  StageResult.data["placed_count"]
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

from agent.core.models import (
    DesignRules, DesignState, Issue, PCBLayout, PlacedComponent,
    Severity, StageResult, StageStatus,
)

# ──────────────────────────────────────────────────────────────────────────────
# Placement zones (x_start, y_start)
# ──────────────────────────────────────────────────────────────────────────────

_ZONES: Dict[str, Tuple[float, float]] = {
    "POWER":      (5.0,  55.0),
    "MCU":        (35.0, 35.0),
    "SBC":        (35.0, 35.0),
    "SENSOR":     (5.0,  5.0),
    "ACTUATOR":   (70.0, 35.0),
    "AUDIO":      (70.0, 55.0),
    "COMMS":      (70.0, 5.0),
    "DISPLAY":    (35.0, 5.0),
    "MEMORY":     (5.0,  35.0),
    "INTERFACE":  (35.0, 55.0),
    "PASSIVE":    (50.0, 70.0),
    "PROTECTION": (5.0,  70.0),
}

_GRID = 2.54   # mm — standard KiCad 100mil grid


def _snap(v: float, grid: float = _GRID) -> float:
    return round(v / grid) * grid


def _place_components(
    selected_map: Dict[str, str],      # subsystem_name → part_number
    components: Dict[str, "Component"],
    board_w: float = 100.0,
    board_h: float = 80.0,
) -> List[PlacedComponent]:
    """
    Assign positions using zone clustering + offset within each zone.
    """
    placed: List[PlacedComponent] = []
    zone_counters: Dict[str, int] = {}

    for sub_name, pn in selected_map.items():
        comp = components.get(pn)
        cat  = comp.category if comp else "PASSIVE"

        x0, y0 = _ZONES.get(cat, (50.0, 50.0))
        idx = zone_counters.get(cat, 0)
        zone_counters[cat] = idx + 1

        # Offset within zone: zigzag 3-column grid
        col = idx % 3
        row = idx // 3
        x = _snap(min(x0 + col * 8.0, board_w - 10.0))
        y = _snap(min(y0 + row * 8.0, board_h - 10.0))

        footprint = comp.footprint if comp and comp.footprint else "Connector:Conn_01x02"

        placed.append(PlacedComponent(
            designator=_des_from_sub(sub_name, idx),
            footprint=footprint,
            x=x,
            y=y,
            rotation=0.0,
            layer="F.Cu",
        ))

    return placed


def _des_from_sub(sub_name: str, idx: int) -> str:
    prefix_map = {
        "power": "U", "regul": "U", "charge": "U",
        "mcu": "U", "sbc": "U", "compute": "U",
        "sensor": "S", "camera": "S", "depth": "S",
        "lidar": "S", "imu": "S", "haptic": "M",
        "actuator": "M", "motor": "M", "feedback": "M",
        "audio": "AMP", "speaker": "AMP", "mic": "MIC",
        "bluetooth": "RF", "comms": "RF", "wireless": "RF",
        "battery": "BAT", "display": "DSP",
    }
    for kw, prefix in prefix_map.items():
        if kw in sub_name.lower():
            return f"{prefix}{idx + 1}"
    return f"U{idx + 1}"


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    sel_result = state.stage_results.get("p08_part_selection")
    if sel_result is None:
        return StageResult(
            stage="p13_placement",
            status=StageStatus.FAILED,
            issues=[Issue("PLACE_NO_PARTS", Severity.ERROR,
                          "Part selection (stage 8) must run first.", "placement")],
            duration=time.monotonic() - t0,
        )

    selected_map: Dict[str, str] = sel_result.data.get("selected", {})
    rules = state.rules or DesignRules()

    placed = _place_components(selected_map, state.components)
    board_area = rules.board_thickness   # re-use model field as placeholder; real area below
    board_area = 100.0 * 80.0           # mm²

    if state.layout is None:
        state.layout = PCBLayout(board_width=100.0, board_height=80.0)
    state.layout.placed = placed

    return StageResult(
        stage="p13_placement",
        status=StageStatus.PASSED,
        data={
            "placed_count": len(placed),
            "board_area_mm2": board_area,
        },
        metrics={
            "placed_count":   float(len(placed)),
            "board_area_mm2": board_area,
        },
        issues=issues,
        duration=time.monotonic() - t0,
    )
