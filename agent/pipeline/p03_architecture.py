"""
Stage 3 — System Architecture Planner
======================================
Uses Gemini to decompose the HardwareRequirements into a set of
Subsystems (power, sensing, compute, feedback, comms, …).

This is one of the four Gemini call points in the pipeline.
The prompt is deliberately large so that the model can:
  1. Identify all required subsystems
  2. Estimate voltages, currents, and interfaces
  3. Flag any ambiguous or missing requirements
  4. Produce a short design rationale

All of this happens in a SINGLE Gemini call, minimising API usage.

Output
------
  state.architecture set
  StageResult.data["subsystems"] = list of subsystem dicts
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Dict, List, Optional

from agent.core.models import (
    DesignState, Issue, Severity, StageResult, StageStatus,
    Subsystem, SystemArchitecture,
)

SYSTEM_PROMPT = """You are a senior embedded-hardware systems architect with 20 years of experience
designing wearable and IoT devices. You communicate in precise, machine-readable JSON only.
Never output prose outside the JSON block."""

PLAN_PROMPT_TEMPLATE = """
=== HARDWARE ARCHITECTURE PLANNING REQUEST ===

Project name : {name}
Description  : {description}
Goals        : {goals}
Budget (USD) : {budget}
Form factor  : {form_factor}
Power source : {power_source}
Op. voltage  : {voltage}
Environment  : {environment}
Success criteria: {criteria}

=== YOUR TASK (all in one response) ===

1. Decompose the project into hardware subsystems.
2. For EACH subsystem specify:
   - name         : short identifier (snake_case)
   - role         : one-sentence description
   - category     : one of [MCU, SBC, POWER, SENSOR, ACTUATOR, COMMS, AUDIO,
                            DISPLAY, MEMORY, INTERFACE, PASSIVE, PROTECTION]
   - voltage_min  : minimum supply voltage (V, float, must be finite)
   - voltage_max  : maximum supply voltage (V, float, must be finite)
   - current_ma   : estimated peak current draw (mA, float, must be finite)
   - interface    : primary bus this subsystem exposes (I2C, SPI, UART, USB, GPIO, PWM, …)
   - priority     : 1 = must-have, 2 = nice-to-have
   - notes        : any design constraints or special requirements
3. Estimate total power budget (mW).
4. List any requirements that are ambiguous or missing.

=== OUTPUT FORMAT ===

Respond with ONLY this JSON (no markdown fences, no extra text):

{{
  "subsystems": [
    {{
      "name":        "power_management",
      "role":        "Regulate and distribute power from battery to all rails",
      "category":    "POWER",
      "voltage_min": 3.0,
      "voltage_max": 5.5,
      "current_ma":  500.0,
      "interface":   "GPIO",
      "priority":    1,
      "notes":       "Must support LiPo single-cell charging"
    }}
  ],
  "power_budget_mw": 1500.0,
  "notes": "Free-form architect notes",
  "ambiguities": ["list", "of", "unclear", "requirements"]
}}
"""


# ──────────────────────────────────────────────────────────────────────────────
# JSON parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Dict[str, Any]:
    """Extract JSON from a model response that may contain extra text."""
    text = text.strip()
    # Strip markdown fences if present
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    # Find outermost { … }
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in model response.")
    return json.loads(text[start:end])


def _parse_architecture(raw: Dict[str, Any]) -> SystemArchitecture:
    subsystems: List[Subsystem] = []
    for s in raw.get("subsystems", []):
        subsystems.append(Subsystem(
            name=s.get("name", "unknown"),
            role=s.get("role", ""),
            category=s.get("category", "PASSIVE"),
            voltage_min=float(s.get("voltage_min", 0.0)),
            voltage_max=float(s.get("voltage_max", 5.0)),
            current_ma=float(s.get("current_ma", 100.0)),
            interface=s.get("interface", "GPIO"),
            priority=int(s.get("priority", 1)),
            notes=s.get("notes", ""),
        ))
    return SystemArchitecture(
        subsystems=subsystems,
        power_budget_mw=float(raw.get("power_budget_mw", 0.0)),
        notes=raw.get("notes", ""),
        raw_plan=json.dumps(raw, indent=2),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fallback: heuristic planner (no Gemini)
# ──────────────────────────────────────────────────────────────────────────────

_FALLBACK_SUBSYSTEMS = [
    Subsystem("power_management", "Power regulation and charging", "POWER",
              3.0, 5.5, 500, "GPIO", 1, "LiPo single-cell"),
    Subsystem("microcontroller", "Main control logic", "MCU",
              3.0, 3.6, 150, "GPIO", 1, ""),
    Subsystem("sensing", "Environmental / spatial sensing", "SENSOR",
              1.8, 5.0, 200, "I2C", 1, ""),
    Subsystem("feedback_output", "Haptic or audio feedback", "ACTUATOR",
              3.0, 5.0, 300, "I2C", 1, ""),
    Subsystem("wireless_comms", "Bluetooth / BLE link", "COMMS",
              1.7, 3.6, 50, "UART", 2, ""),
]


def _fallback_architecture(req: "HardwareRequirements") -> SystemArchitecture:
    return SystemArchitecture(
        subsystems=_FALLBACK_SUBSYSTEMS,
        power_budget_mw=2000.0,
        notes="Fallback heuristic plan (Gemini unavailable).",
        raw_plan="",
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point (async because it calls Gemini)
# ──────────────────────────────────────────────────────────────────────────────

async def run_async(
    state: DesignState,
    gemini_manager: Any,
) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    if state.requirements is None:
        return StageResult(
            stage="p03_architecture",
            status=StageStatus.FAILED,
            issues=[Issue("ARCH_NO_REQ", Severity.ERROR,
                          "Requirements not set before architecture stage.", "architecture")],
            duration=time.monotonic() - t0,
        )

    req = state.requirements

    prompt = PLAN_PROMPT_TEMPLATE.format(
        name=req.name,
        description=req.description,
        goals="\n  - " + "\n  - ".join(req.goals) if req.goals else "(none specified)",
        budget=f"${req.budget_usd:.2f}" if req.budget_usd else "unspecified",
        form_factor=req.form_factor or "unspecified",
        power_source=req.power_source or "unspecified",
        voltage=f"{req.operating_voltage}V" if req.operating_voltage else "unspecified",
        environment=req.environment or "unspecified",
        criteria="\n  - " + "\n  - ".join(req.success_criteria) if req.success_criteria else "(none)",
    )

    raw_response = ""
    arch: Optional[SystemArchitecture] = None

    try:
        raw_response = await gemini_manager.call_gemini(
            prompt=prompt,
            task="heavy",
            system_instruction=SYSTEM_PROMPT,
            temperature=0.15,
        )
        raw_dict = _extract_json(raw_response)
        arch = _parse_architecture(raw_dict)

        ambiguities = raw_dict.get("ambiguities", [])
        for amb in ambiguities:
            issues.append(Issue(
                code="ARCH_AMBIGUITY",
                severity=Severity.WARNING,
                message=f"Ambiguous requirement: {amb}",
                source="architecture",
            ))

    except Exception as exc:
        issues.append(Issue(
            code="ARCH_GEMINI_ERROR",
            severity=Severity.WARNING,
            message=f"Gemini call failed ({exc}). Using fallback heuristic plan.",
            source="architecture",
        ))
        arch = _fallback_architecture(req)

    if not arch.subsystems:
        issues.append(Issue(
            code="ARCH_NO_SUBSYSTEMS",
            severity=Severity.ERROR,
            message="Architecture planner produced no subsystems.",
            source="architecture",
        ))
        return StageResult(
            stage="p03_architecture",
            status=StageStatus.FAILED,
            issues=issues,
            duration=time.monotonic() - t0,
        )

    state.architecture = arch
    has_errors = any(i.is_error() for i in issues)

    return StageResult(
        stage="p03_architecture",
        status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
        data={
            "subsystems":     [vars(s) for s in arch.subsystems],
            "power_budget_mw": arch.power_budget_mw,
            "notes":          arch.notes,
        },
        issues=issues,
        metrics={"subsystem_count": float(len(arch.subsystems))},
        duration=time.monotonic() - t0,
    )


def run(state: DesignState, gemini_manager: Any) -> StageResult:
    """Synchronous wrapper for use outside an event loop."""
    return asyncio.run(run_async(state, gemini_manager))
