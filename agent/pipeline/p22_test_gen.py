"""
Stage 22 — Test Scenario Generator
=====================================
Generates diverse test scenarios based on the requirements and
selected components, ensuring the simulation covers edge cases.

Deterministic — no Gemini call.

Scenarios generated:
  • Nominal operating conditions
  • Peak load (all subsystems active simultaneously)
  • Idle / standby power
  • Startup inrush current
  • Low battery (battery near cutoff voltage)
  • High temperature ambient (if outdoor environment)
  • Worst-case signal integrity (max capacitance)
  • Repeated power cycles (stress test)
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from agent.core.models import (
    DesignState, Issue, Severity,
    StageResult, StageStatus,
)


def generate_scenarios(state: DesignState) -> List[Dict[str, Any]]:
    """Build the scenario list based on requirements and architecture."""
    req  = state.requirements
    arch = state.architecture

    scenarios: List[Dict[str, Any]] = [
        {
            "name":        "nominal_load",
            "description": "All selected subsystems running at rated current",
            "load_factor": 1.0,
            "duration_ms": 100.0,
            "ambient_c":   25.0,
        },
        {
            "name":        "peak_simultaneous",
            "description": "All subsystems active simultaneously including burst modes",
            "load_factor": 1.4,
            "duration_ms": 30.0,
            "ambient_c":   25.0,
        },
        {
            "name":        "idle_standby",
            "description": "Only keep-alive logic running; sensors off",
            "load_factor": 0.08,
            "duration_ms": 5000.0,
            "ambient_c":   25.0,
        },
        {
            "name":        "startup_inrush",
            "description": "Cold boot: capacitors charging + all peripherals initialising",
            "load_factor": 2.5,
            "duration_ms": 8.0,
            "ambient_c":   25.0,
        },
        {
            "name":        "low_battery",
            "description": "Battery near cutoff voltage (3.0V for 18650)",
            "load_factor": 1.0,
            "duration_ms": 100.0,
            "ambient_c":   25.0,
            "battery_v":   3.0,
        },
        {
            "name":        "power_cycle_stress",
            "description": "100 rapid power cycles to stress power rail sequencing",
            "load_factor": 1.2,
            "duration_ms": 10.0,
            "cycles":      100,
            "ambient_c":   25.0,
        },
    ]

    # Environment-aware additions
    if req and req.environment in ("outdoor", "harsh", "automotive"):
        scenarios.append({
            "name":        "high_temp_outdoor",
            "description": "High ambient temperature (40°C outdoor conditions)",
            "load_factor": 1.0,
            "duration_ms": 100.0,
            "ambient_c":   40.0,
        })
        scenarios.append({
            "name":        "low_temp",
            "description": "Low ambient temperature (-10°C cold start)",
            "load_factor": 1.1,
            "duration_ms": 100.0,
            "ambient_c":   -10.0,
        })

    # Wearable-specific scenarios
    if req and req.form_factor == "wearable":
        scenarios.append({
            "name":        "motion_vibration",
            "description": "Vibration motor active + IMU active simultaneously",
            "load_factor": 1.3,
            "duration_ms": 200.0,
            "ambient_c":   37.0,   # body temperature
        })
        scenarios.append({
            "name":        "8h_continuous",
            "description": "8-hour continuous use battery drain simulation",
            "load_factor": 0.7,
            "duration_ms": 28800000.0,   # 8h in ms
            "ambient_c":   37.0,
        })

    # Signal-intensive scenario if comms subsystem present
    if arch and any(s.category == "COMMS" for s in arch.subsystems):
        scenarios.append({
            "name":        "comms_burst",
            "description": "BLE/LoRa transmitting at max power while sensors active",
            "load_factor": 1.5,
            "duration_ms": 50.0,
            "ambient_c":   25.0,
        })

    return scenarios


def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    scenarios = generate_scenarios(state)

    return StageResult(
        stage="p22_test_gen",
        status=StageStatus.PASSED,
        data={
            "scenarios":      scenarios,
            "scenario_count": len(scenarios),
        },
        metrics={"scenario_count": float(len(scenarios))},
        duration=time.monotonic() - t0,
    )
