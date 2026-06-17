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

_DEFAULT_ZONE = "PASSIVE"   # fallback zone for unrecognised categories


# Reverse map: fine-grained DB category (e.g. "Depth Sensor", "LDO") → coarse
# zone category (e.g. "SENSOR", "POWER").  Built from the same alias table that
# part selection (p08) uses, so the two stages stay in sync.
def _build_db_to_zone() -> Dict[str, str]:
    try:
        from agent.pipeline.p08_part_selection import _CATEGORY_DB_ALIASES
    except Exception:
        return {}
    mapping: Dict[str, str] = {}
    for coarse, db_cats in _CATEGORY_DB_ALIASES.items():
        zone = coarse.upper()
        if zone not in _ZONES:
            continue
        for db_cat in db_cats:
            mapping.setdefault(db_cat.upper(), zone)
    return mapping


_DB_CATEGORY_TO_ZONE: Dict[str, str] = _build_db_to_zone()


def _resolve_zone(arch_category: Optional[str], db_category: Optional[str]) -> str:
    """
    Resolve the placement zone for a component.

    The zone table is keyed by coarse architecture categories (SENSOR, POWER,
    ...), but a selected component carries its fine-grained DB category
    ("Depth Sensor", "LDO", ...).  Prefer the subsystem's architecture category;
    fall back to mapping the DB category back to its coarse zone; finally use a
    default zone.  Without this, fine-grained categories miss the zone table and
    every component collapses onto one coordinate, producing permanent
    DRC_COMPONENT_OVERLAP errors that no repair can clear.
    """
    if arch_category and arch_category.upper() in _ZONES:
        return arch_category.upper()
    if db_category and db_category.upper() in _ZONES:
        return db_category.upper()
    if db_category and db_category.upper() in _DB_CATEGORY_TO_ZONE:
        return _DB_CATEGORY_TO_ZONE[db_category.upper()]
    return _DEFAULT_ZONE


def _snap(v: float, grid: float = _GRID) -> float:
    return round(v / grid) * grid


def _place_components(
    selected_map: Dict[str, str],      # subsystem_name → part_number
    components: Dict[str, "Component"],
    board_w: float,
    board_h: float,
    sub_category_map: Optional[Dict[str, str]] = None,  # subsystem_name → arch category
) -> List[PlacedComponent]:
    """
    Assign positions using zone clustering + offset within each zone.
    """
    sub_category_map = sub_category_map or {}
    placed: List[PlacedComponent] = []
    zone_counters: Dict[str, int] = {}
    des_counter: int = 0

    for sub_name, pn in selected_map.items():
        comp = components.get(pn)
        zone = _resolve_zone(sub_category_map.get(sub_name),
                             comp.category if comp else None)

        x0, y0 = _ZONES[zone]
        idx = zone_counters.get(zone, 0)
        zone_counters[zone] = idx + 1

        # Offset within zone: zigzag 3-column grid
        col = idx % 3
        row = idx // 3
        x = _snap(min(x0 + col * 8.0, board_w - 10.0))
        y = _snap(min(y0 + row * 8.0, board_h - 10.0))

        footprint = comp.footprint if comp and comp.footprint else "Connector:Conn_01x02"

        des_counter += 1
        placed.append(PlacedComponent(
            designator=_des_from_sub(sub_name, des_counter - 1),
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

    sub_category_map: Dict[str, str] = {}
    if state.architecture:
        sub_category_map = {
            sub.name: sub.category for sub in state.architecture.subsystems
        }

    if state.layout is None:
        state.layout = PCBLayout(board_width=100.0, board_height=80.0)

    board_w = state.layout.board_width
    board_h = state.layout.board_height
    placed = _place_components(
        selected_map, state.components, board_w, board_h, sub_category_map,
    )
    board_area = board_w * board_h

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
