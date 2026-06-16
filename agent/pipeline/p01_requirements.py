"""
Stage 1 — Requirements Schema
==============================
Parses and validates hardware requirements from natural language text
or a structured dict. Produces a HardwareRequirements object consumed
by every downstream stage.

Design contract
---------------
  Input:  raw_text (str) OR structured dict
  Output: StageResult with data["requirements"] = HardwareRequirements
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict
from typing import Any, Dict, Optional

from agent.core.models import (
    DesignState, HardwareRequirements, Issue, Severity,
    StageResult, StageStatus,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _extract_float(text: str, *patterns: str) -> Optional[float]:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, IndexError):
                continue
    return None


def _extract_list(text: str, *triggers: str) -> list[str]:
    """Return bullet / comma-separated items found after a trigger phrase."""
    items: list[str] = []
    for trigger in triggers:
        m = re.search(rf"{trigger}[:\s]+(.+?)(?:\n\n|\Z)", text, re.IGNORECASE | re.DOTALL)
        if m:
            block = m.group(1)
            candidates = re.split(r"[;\n,•\-]", block)
            items = [c.strip() for c in candidates if len(c.strip()) > 3]
            if items:
                break
    return items[:10]   # cap to 10


# ──────────────────────────────────────────────────────────────────────────────
# Parsers
# ──────────────────────────────────────────────────────────────────────────────

def parse_from_text(raw_text: str) -> HardwareRequirements:
    """Heuristic extraction of structured requirements from free-form text."""
    text = raw_text.strip()

    # Name
    name_m = re.search(r"(?:project|device|system|name)[:\s]+([^\n]{3,60})", text, re.I)
    name = name_m.group(1).strip() if name_m else "Unnamed Hardware Project"

    # Budget
    budget = _extract_float(text, r"budget[^\$\d]*\$?([\d.]+)")

    # Voltage
    operating_voltage = _extract_float(
        text,
        r"([\d.]+)\s*[Vv]olt",
        r"voltage[:\s]+([\d.]+)",
        r"([\d.]+)\s*V\b",
    )

    # Current
    target_current = _extract_float(
        text,
        r"([\d.]+)\s*mA",
        r"current[:\s]+([\d.]+)",
    )

    # Goals
    goals = _extract_list(text, "goal", "objective", "purpose", "requirement", "need")
    if not goals:
        # Fall back to first 3 sentences
        sentences = re.split(r"(?<=[.!?])\s+", text)
        goals = [s.strip() for s in sentences[:3] if len(s.strip()) > 10]

    # Success criteria
    criteria = _extract_list(text, "success", "criteria", "must", "shall")

    # Form factor
    ff_m = re.search(r"(wearable|handheld|desktop|board|module|embedded|portable)", text, re.I)
    form_factor = ff_m.group(1).lower() if ff_m else None

    # Power source
    ps_m = re.search(r"(battery|lipo|lithium|usb|mains|solar|PoE|AA|AAA|18650)", text, re.I)
    power_source = ps_m.group(1).lower() if ps_m else None

    # Environment
    env_m = re.search(r"(indoor|outdoor|harsh|waterproof|military|automotive|consumer)", text, re.I)
    environment = env_m.group(1).lower() if env_m else None

    return HardwareRequirements(
        name=name,
        description=text[:200],
        goals=goals,
        budget_usd=budget,
        form_factor=form_factor,
        power_source=power_source,
        operating_voltage=operating_voltage,
        target_current_ma=target_current,
        environment=environment,
        success_criteria=criteria,
        raw_text=raw_text,
    )


def parse_from_dict(d: Dict[str, Any]) -> HardwareRequirements:
    """Direct construction from a structured dict (already validated upstream)."""
    return HardwareRequirements(
        name=d.get("name", "Unnamed"),
        description=d.get("description", ""),
        goals=d.get("goals", []),
        constraints=d.get("constraints", {}),
        budget_usd=d.get("budget_usd"),
        form_factor=d.get("form_factor"),
        power_source=d.get("power_source"),
        operating_voltage=d.get("operating_voltage"),
        target_current_ma=d.get("target_current_ma"),
        environment=d.get("environment"),
        success_criteria=d.get("success_criteria", []),
        raw_text=d.get("raw_text", ""),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────────────────────────────────────

def validate_requirements(req: HardwareRequirements) -> list[Issue]:
    issues: list[Issue] = []

    if not req.name or req.name == "Unnamed Hardware Project":
        issues.append(Issue(
            code="REQ_NO_NAME",
            severity=Severity.WARNING,
            message="No project name detected — using default.",
            source="requirements",
        ))

    if not req.goals:
        issues.append(Issue(
            code="REQ_NO_GOALS",
            severity=Severity.ERROR,
            message="No design goals extracted. Cannot plan subsystems.",
            source="requirements",
        ))

    if req.budget_usd is not None and req.budget_usd <= 0:
        issues.append(Issue(
            code="REQ_INVALID_BUDGET",
            severity=Severity.WARNING,
            message=f"Budget {req.budget_usd} USD is not positive.",
            source="requirements",
        ))

    if req.operating_voltage is not None:
        if req.operating_voltage < 1.0 or req.operating_voltage > 48.0:
            issues.append(Issue(
                code="REQ_UNUSUAL_VOLTAGE",
                severity=Severity.WARNING,
                message=f"Operating voltage {req.operating_voltage}V is outside typical range [1–48V].",
                source="requirements",
            ))

    return issues


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState, raw_input: Any = None) -> StageResult:
    """
    Stage 1 entry point.

    Parameters
    ----------
    state:     Current DesignState (may be empty on first run).
    raw_input: str (free text) or dict (structured). If None, uses
               state.requirements.raw_text if already set.
    """
    t0 = time.monotonic()
    issues: list[Issue] = []

    try:
        if isinstance(raw_input, str):
            req = parse_from_text(raw_input)
        elif isinstance(raw_input, dict):
            req = parse_from_dict(raw_input)
        elif state.requirements is not None:
            req = state.requirements
        else:
            return StageResult(
                stage="p01_requirements",
                status=StageStatus.FAILED,
                issues=[Issue(
                    code="REQ_NO_INPUT",
                    severity=Severity.ERROR,
                    message="No input provided to requirements stage.",
                    source="requirements",
                )],
                duration=time.monotonic() - t0,
            )

        issues = validate_requirements(req)
        has_errors = any(i.is_error() for i in issues)

        state.requirements = req

        return StageResult(
            stage="p01_requirements",
            status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
            data={"requirements": req.to_dict()},
            issues=issues,
            duration=time.monotonic() - t0,
        )

    except Exception as exc:
        issues.append(Issue(
            code="REQ_EXCEPTION",
            severity=Severity.ERROR,
            message=f"Requirements parsing failed: {exc}",
            source="requirements",
        ))
        return StageResult(
            stage="p01_requirements",
            status=StageStatus.FAILED,
            issues=issues,
            duration=time.monotonic() - t0,
        )
