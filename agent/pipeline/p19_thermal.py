"""
Stage 19 — Thermal Estimator
==============================
Estimates junction and board temperatures for power-dissipating
components using simplified steady-state thermal models.

Model:
  T_junction = T_ambient + P_dissipated × θ_ja
  where θ_ja (thermal resistance junction-to-ambient) is looked up
  from a package database or estimated from package type.

Deterministic — no Gemini call.

Output
------
  StageResult.data["hotspots"]     = list of {component, T_j, risk}
  StageResult.data["max_temp_c"]   = float
  StageResult.metrics["max_temp_c"]
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.core.models import (
    Component, DesignState, Issue, Severity,
    StageResult, StageStatus,
)

# ──────────────────────────────────────────────────────────────────────────────
# Thermal resistance database (°C/W) by package type
# ──────────────────────────────────────────────────────────────────────────────

_THETA_JA: Dict[str, float] = {
    "SOT-23":    300.0,
    "SOT23":     300.0,
    "SOIC-8":    100.0,
    "SOP-8":     100.0,
    "QFN":        40.0,
    "DFN":        50.0,
    "VSON":       40.0,
    "TSSOP":      80.0,
    "LQFP":       50.0,
    "LGA":        45.0,
    "TO-220":     65.0,
    "TO220":      65.0,
    "Module":     30.0,
    "Board":      20.0,
    "default":   150.0,
}

T_AMBIENT    = 25.0    # °C
T_WARN_LIMIT = 85.0    # °C — consumer grade
T_ERR_LIMIT  = 105.0   # °C — approaching absolute max for most ICs


@dataclass
class ThermalResult:
    part_number:  str
    designator:   str
    power_mw:     float
    theta_ja:     float
    t_junction:   float
    risk:         str   # "OK" | "WARM" | "HOT" | "CRITICAL"


def _resolve_theta(comp: Component) -> float:
    pkg = comp.package.upper() if comp.package else ""
    for key, val in _THETA_JA.items():
        if key.upper() in pkg:
            return val
    return _THETA_JA["default"]


def _classify_risk(t_j: float) -> str:
    if t_j < T_WARN_LIMIT:
        return "OK"
    if t_j < T_ERR_LIMIT:
        return "WARM"
    if t_j < T_ERR_LIMIT + 20:
        return "HOT"
    return "CRITICAL"


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    sel_result = state.stage_results.get("p08_part_selection")
    selected = sel_result.data.get("selected", {}) if sel_result else {}

    # Build designator map
    des_map: Dict[str, str] = {}
    if state.layout:
        for pc in state.layout.placed:
            des_map[pc.designator] = pc.footprint
    if state.schematic:
        for sc in state.schematic.components:
            if sc.designator not in des_map:
                des_map[sc.designator] = sc.part_number

    # Reverse selected: sub_name → pn → find designator
    pn_set = set(selected.values())
    thermal_results: List[ThermalResult] = []
    max_temp = T_AMBIENT

    for sub_name, pn in selected.items():
        comp = state.components.get(pn)
        if comp is None:
            continue

        # Power dissipated: use I²R for regulators, or V×I for others
        if comp.category in ("POWER", "Charger IC", "Buck-Boost", "LDO"):
            # Estimate dropout dissipation: P = (Vin - Vout) × I_load
            v_in  = comp.voltage_max * 1.2   # rough input estimate
            v_out = comp.voltage_min if comp.voltage_min > 0 else comp.voltage_max * 0.66
            i_load = comp.current_ma / 1000.0
            p_mw = max((v_in - v_out) * i_load * 1000.0, 0)
        else:
            # Simple: P = V × I
            p_mw = comp.voltage_max * comp.current_ma

        # thermal_mitigation < 1.0 models an added heatsink / copper pour / fan
        # lowering the effective junction-to-ambient thermal resistance.
        mitigation = max(getattr(comp, "thermal_mitigation", 1.0), 0.05)
        theta = _resolve_theta(comp) * mitigation
        t_j   = T_AMBIENT + (p_mw / 1000.0) * theta

        max_temp = max(max_temp, t_j)
        risk     = _classify_risk(t_j)

        # Find designator from schematic
        des = next(
            (sc.designator for sc in (state.schematic.components if state.schematic else [])
             if sc.part_number == pn),
            sub_name[:3].upper(),
        )

        thermal_results.append(ThermalResult(
            part_number=pn,
            designator=des,
            power_mw=round(p_mw, 2),
            theta_ja=theta,
            t_junction=round(t_j, 1),
            risk=risk,
        ))

        if risk == "CRITICAL":
            issues.append(Issue(
                code="THERMAL_CRITICAL",
                severity=Severity.ERROR,
                message=(
                    f"Component '{pn}' (θ_ja={theta}°C/W) reaches "
                    f"{t_j:.1f}°C — exceeds safe limit of {T_ERR_LIMIT}°C. "
                    "Add heatsink, increase copper pour, or select lower-power part."
                ),
                source="thermal",
                objects=[des],
            ))
        elif risk in ("HOT", "WARM"):
            issues.append(Issue(
                code="THERMAL_WARNING",
                severity=Severity.WARNING,
                message=(
                    f"Component '{pn}' estimated at {t_j:.1f}°C (risk={risk}). "
                    "Monitor thermal performance in prototype."
                ),
                source="thermal",
                objects=[des],
            ))

    has_errors = any(i.is_error() for i in issues)
    return StageResult(
        stage="p19_thermal",
        status=StageStatus.PASSED if not has_errors else StageStatus.FAILED,
        data={
            "max_temp_c": round(max_temp, 1),
            "hotspots": [
                {
                    "part_number": r.part_number,
                    "designator":  r.designator,
                    "power_mw":    r.power_mw,
                    "theta_ja":    r.theta_ja,
                    "t_junction":  r.t_junction,
                    "risk":        r.risk,
                }
                for r in sorted(thermal_results, key=lambda x: x.t_junction, reverse=True)
            ],
        },
        issues=issues,
        metrics={"max_temp_c": round(max_temp, 1)},
        duration=time.monotonic() - t0,
    )
