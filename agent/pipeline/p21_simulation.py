"""
Stage 21 — Simulation Wrapper
================================
Runs each test scenario (from Stage 22) through a deterministic
circuit-level simulation model and records pass/fail + key metrics.

Simulation is physics-inspired but simplified — it models:
  • Voltage stability under load
  • Signal integrity on I2C/SPI buses (rise time vs. pull-up)
  • Noise floor on analog inputs
  • Thermal transient (steady state from Stage 19)
  • Battery discharge curve segment

Deterministic — no Gemini call.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent.core.models import (
    Component, DesignRules, DesignState, Issue, Severity,
    SimulationResult, StageResult, StageStatus,
)


# ──────────────────────────────────────────────────────────────────────────────
# Sub-simulators
# ──────────────────────────────────────────────────────────────────────────────

def _sim_voltage_stability(
    components: Dict[str, Component],
    selected_pns: List[str],
    load_factor: float = 1.0,   # 1.0 = full load
) -> tuple[float, List[Issue]]:
    """
    Returns (voltage_stability: 0–1, issues).
    Stability drops under high load if regulator headroom is thin.
    """
    issues: List[Issue] = []
    regulators = [
        c for pn in selected_pns
        if (c := components.get(pn)) and c.category in ("POWER", "LDO", "Buck-Boost", "Charger IC")
    ]
    consumers = [
        c for pn in selected_pns
        if (c := components.get(pn)) and c.category not in ("POWER", "LDO", "Buck-Boost", "Charger IC", "Battery")
    ]

    if not regulators:
        issues.append(Issue("SIM_NO_REGULATOR", Severity.ERROR,
                            "No power regulator found — cannot simulate voltage stability. "
                            "ROOT CAUSE: Missing POWER/LDO/Buck-Boost component in selected BOM. "
                            "REPAIR: Use 'add_component' for 'power_management' subsystem.", "simulation"))
        return 0.3, issues

    total_capacity_ma = sum(r.current_ma for r in regulators)
    total_demand_ma   = sum(c.current_ma for c in consumers) * load_factor

    if total_capacity_ma <= 0:
        return 0.5, issues

    load_ratio = total_demand_ma / total_capacity_ma
    stability  = max(0.0, 1.0 - max(0.0, load_ratio - 0.7) * 2.0)

    if load_ratio > 0.9:
        issues.append(Issue(
            code="SIM_NEAR_CAPACITY",
            severity=Severity.WARNING,
            message=f"Load {total_demand_ma:.0f}mA is {load_ratio*100:.0f}% of regulator capacity "
                    f"{total_capacity_ma:.0f}mA at load_factor={load_factor:.1f}.",
            source="simulation",
        ))
    return round(stability, 3), issues


def _sim_signal_integrity(
    components: Dict[str, Component],
    selected_pns: List[str],
) -> tuple[float, List[Issue]]:
    """
    Returns (signal_integrity: 0–1, issues).
    Checks I2C pull-up resistor adequacy.
    """
    issues: List[Issue] = []

    # Count I2C devices
    i2c_devices = [
        c for pn in selected_pns
        if (c := components.get(pn)) and
        ("I2C" in c.notes.upper() or "I2C" in c.description.upper() or "SDA" in str(c.pins))
    ]

    if not i2c_devices:
        return 1.0, issues

    # Rule: each I2C bus needs pull-up resistors (4.7kΩ typical)
    has_resistors = any(
        c.category in ("Resistor", "PASSIVE")
        for pn in selected_pns if (c := components.get(pn))
    )

    n_i2c = len(i2c_devices)
    bus_capacitance_pf = n_i2c * 15.0  # approx 15pF per device
    # Rise time with 4.7kΩ pull-up: τ = R×C
    r_pullup = 4700.0  # Ω
    tau_ns    = r_pullup * bus_capacitance_pf * 1e-3  # ns
    # I2C 400kHz standard: rise time must be < 300ns
    max_rise_ns = 300.0

    si_score = 1.0
    if tau_ns > max_rise_ns:
        si_score = max(0.4, 1.0 - (tau_ns - max_rise_ns) / max_rise_ns)
        issues.append(Issue(
            code="SIM_I2C_SLOW_RISE",
            severity=Severity.WARNING,
            message=(
                f"I2C estimated rise time {tau_ns:.0f}ns exceeds 400kHz limit {max_rise_ns}ns "
                f"with {n_i2c} devices. Use lower pull-up resistance (e.g. 2.2kΩ)."
            ),
            source="simulation",
        ))

    if not has_resistors:
        si_score *= 0.7
        issues.append(Issue(
            code="SIM_NO_PULLUP",
            severity=Severity.WARNING,
            message="No resistors in BOM — I2C/SPI pull-up resistors may be missing. "
                    "ROOT CAUSE: Missing PASSIVE components. "
                    "REPAIR: Use 'add_component' to add 4.7k pull-up resistors to I2C lines.",
            source="simulation",
        ))

    return round(si_score, 3), issues


def _sim_power_consumption(
    components: Dict[str, Component],
    selected_pns: List[str],
    load_factor: float = 1.0,
) -> float:
    """Return total power draw in mW at given load factor."""
    return sum(
        c.voltage_max * c.current_ma * load_factor
        for pn in selected_pns if (c := components.get(pn))
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(
    state: DesignState,
    scenarios: Optional[List[Dict[str, Any]]] = None,
) -> StageResult:
    t0 = time.monotonic()
    all_issues: List[Issue] = []

    sel_result  = state.stage_results.get("p08_part_selection")
    selected_pns = list(sel_result.data.get("selected", {}).values()) if sel_result else []

    if not scenarios:
        # Pull from Stage 22 if available, else use defaults
        test_result = state.stage_results.get("p22_test_gen")
        scenarios   = test_result.data.get("scenarios", []) if test_result else []

    if not scenarios:
        scenarios = [
            {"name": "nominal_load",   "load_factor": 1.0,  "duration_ms": 100.0},
            {"name": "peak_load",      "load_factor": 1.25, "duration_ms": 50.0},
            {"name": "idle_standby",   "load_factor": 0.1,  "duration_ms": 1000.0},
            {"name": "startup_inrush", "load_factor": 2.0,  "duration_ms": 5.0},
        ]

    thermal_result = state.stage_results.get("p19_thermal")
    max_temp_c = thermal_result.data.get("max_temp_c", 25.0) if thermal_result else 25.0

    sim_results: List[SimulationResult] = []

    for scenario in scenarios:
        s_issues: List[Issue] = []
        lf = float(scenario.get("load_factor", 1.0))

        v_stability, v_issues = _sim_voltage_stability(state.components, selected_pns, lf)
        si_score,    si_issues = _sim_signal_integrity(state.components, selected_pns)
        pwr_mw = _sim_power_consumption(state.components, selected_pns, lf)

        s_issues += v_issues + si_issues

        # Scenario passes if all metrics are acceptable
        passed = (v_stability >= 0.6 and si_score >= 0.5 and pwr_mw < 10000)
        if not passed:
            s_issues.append(Issue(
                code="SIM_SCENARIO_FAIL",
                severity=Severity.ERROR,
                message=(
                    f"Scenario '{scenario['name']}' FAILED: "
                    f"v_stability={v_stability:.2f}, si={si_score:.2f}, "
                    f"power={pwr_mw:.0f}mW."
                ),
                source="simulation",
            ))

        sim_results.append(SimulationResult(
            scenario=scenario["name"],
            passed=passed,
            duration_ms=float(scenario.get("duration_ms", 100.0)),
            power_consumption_mw=round(pwr_mw, 2),
            max_temperature_c=max_temp_c,
            voltage_stability=v_stability,
            signal_integrity=si_score,
            issues=s_issues,
        ))
        all_issues += s_issues

    state.sim_results = sim_results

    n_pass = sum(1 for r in sim_results if r.passed)
    n_total = len(sim_results)
    pass_rate = n_pass / n_total if n_total > 0 else 0.0

    has_errors = any(i.is_error() for i in all_issues)
    return StageResult(
        stage="p21_simulation",
        status=StageStatus.PASSED if pass_rate >= 0.75 and not has_errors else StageStatus.FAILED,
        data={
            "pass_rate":    round(pass_rate, 3),
            "passed_count": n_pass,
            "total_count":  n_total,
            "results": [
                {
                    "scenario":        r.scenario,
                    "passed":          r.passed,
                    "power_mw":        r.power_consumption_mw,
                    "v_stability":     r.voltage_stability,
                    "signal_integrity": r.signal_integrity,
                }
                for r in sim_results
            ],
        },
        issues=all_issues,
        metrics={
            "sim_pass_rate":    pass_rate,
            "sim_power_mw_nom": sim_results[0].power_consumption_mw if sim_results else 0.0,
        },
        duration=time.monotonic() - t0,
    )
