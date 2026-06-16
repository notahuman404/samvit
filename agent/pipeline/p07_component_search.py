"""
Stage 7 — Component Search / Retrieval
========================================
Searches state.components (already loaded from DB + datasheet parser)
for candidates that match each subsystem in state.architecture.

Pure deterministic Python — no Gemini call needed here.

Output
------
  StageResult.data["candidates"] = dict mapping subsystem_name → list of part_numbers
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Tuple

from agent.core.models import (
    Component, DesignState, Issue, Severity,
    StageResult, StageStatus, Subsystem,
)

# Category keyword → list of DB category strings
CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "MCU":        ["MCU", "Microcontroller"],
    "SBC":        ["SBC"],
    "POWER":      ["Charger IC", "Buck-Boost", "Boost Converter", "LDO", "Battery", "POWER"],
    "SENSOR":     ["Depth Sensor", "ToF Sensor", "LiDAR", "Barometer", "IMU", "Camera", "Microphone"],
    "ACTUATOR":   ["Actuator", "Haptic Driver", "PWM Driver", "MOTOR"],
    "COMMS":      ["BT Module", "BLE SoC", "LoRa", "LTE Module", "COMMS"],
    "AUDIO":      ["Audio Amp", "Mic Amp", "Microphone", "AUDIO"],
    "DISPLAY":    ["Display", "LED", "DISPLAY"],
    "MEMORY":     ["Flash", "Storage", "MEMORY"],
    "INTERFACE":  ["Level Shifter", "IO Expander", "Buffer", "PWM Driver", "INTERFACE"],
    "PASSIVE":    ["Capacitor", "Resistor", "Diode", "MOSFET", "Connector", "PASSIVE"],
    "PROTECTION": ["Diode", "MOSFET", "PROTECTION"],
}


def _score(comp: Component, sub: Subsystem) -> float:
    score = 0.0

    # Category match
    db_cats = CATEGORY_KEYWORDS.get(sub.category, [sub.category])
    for cat in db_cats:
        if cat.lower() == comp.category.lower():
            score += 10.0
        elif cat.lower() in comp.category.lower() or comp.category.lower() in cat.lower():
            score += 5.0

    # Voltage compatibility (hard filter: skip if fails)
    if sub.voltage_min > 0 and comp.voltage_max < sub.voltage_min:
        return -1.0
    if sub.voltage_max > 0 and comp.voltage_min > sub.voltage_max:
        return -1.0

    # Voltage match bonus
    if comp.voltage_min <= sub.voltage_min and comp.voltage_max >= sub.voltage_max:
        score += 5.0

    # Current adequacy
    if sub.current_ma > 0 and comp.current_ma > 0:
        ratio = comp.current_ma / sub.current_ma
        if ratio >= 1.0:
            score += min(5.0, ratio)   # More headroom = better (cap at 5)
        else:
            score -= 5.0  # Under-rated

    # Interface match (keyword check)
    if sub.interface.upper() in (comp.notes + " " + comp.description).upper():
        score += 3.0

    # Confidence bonus
    score += comp.confidence * 2.0

    # Cost bonus (lower = better)
    if comp.cost_usd > 0:
        score -= comp.cost_usd * 0.1

    return max(score, 0.0)


def search_for_subsystem(
    sub: Subsystem,
    components: Dict[str, Component],
    top_n: int = 5,
) -> List[Tuple[str, float]]:
    """Return top_n (part_number, score) pairs for a subsystem."""
    scored: List[Tuple[str, float]] = []
    for pn, comp in components.items():
        s = _score(comp, sub)
        if s > 0:
            scored.append((pn, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]


def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    if state.architecture is None:
        return StageResult(
            stage="p07_component_search",
            status=StageStatus.FAILED,
            issues=[Issue("SEARCH_NO_ARCH", Severity.ERROR,
                          "Architecture not set before component search.", "search")],
            duration=time.monotonic() - t0,
        )

    if not state.components:
        return StageResult(
            stage="p07_component_search",
            status=StageStatus.FAILED,
            issues=[Issue("SEARCH_EMPTY_DB", Severity.ERROR,
                          "Component DB is empty. Run stages 5 and 6 first.", "search")],
            duration=time.monotonic() - t0,
        )

    candidates: Dict[str, List[Dict[str, Any]]] = {}
    unfilled: List[str] = []

    for sub in state.architecture.subsystems:
        results = search_for_subsystem(sub, state.components)
        if not results:
            unfilled.append(sub.name)
            issues.append(Issue(
                code="SEARCH_NO_MATCH",
                severity=Severity.WARNING if sub.priority == 2 else Severity.ERROR,
                message=f"No components found for subsystem '{sub.name}' ({sub.category}).",
                source="component_search",
                objects=[sub.name],
            ))
        else:
            candidates[sub.name] = [
                {"part_number": pn, "score": round(s, 2)} for pn, s in results
            ]

    has_errors = any(i.is_error() for i in issues)
    return StageResult(
        stage="p07_component_search",
        status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
        data={"candidates": candidates, "unfilled_subsystems": unfilled},
        metrics={
            "subsystems_filled": float(len(candidates)),
            "subsystems_total":  float(len(state.architecture.subsystems)),
        },
        issues=issues,
        duration=time.monotonic() - t0,
    )
