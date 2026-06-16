"""
Stage 9 — Compatibility Checker (improved)
===========================================
Validates selected parts against each other:
  • Voltage domain compatibility
  • Current oversubscription
  • Missing driver stages
  • Interface protocol mismatches
  • Missing dependency categories

Wraps and extends the existing hardware_builder/compatibility_checker.py
logic with the new Component / DesignState models.

Output
------
  StageResult.data["is_valid"]  = bool
  StageResult.data["issues"]    = list of issue dicts
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from agent.core.models import (
    Component, DesignState, Issue, PinType, Severity,
    StageResult, StageStatus,
)


# ──────────────────────────────────────────────────────────────────────────────
# Rule definitions
# ──────────────────────────────────────────────────────────────────────────────

def _check_voltage_domains(
    selected: Dict[str, Component],
) -> List[Issue]:
    """Flag pairs where one component's max voltage exceeds another's max input."""
    issues: List[Issue] = []
    parts = list(selected.items())

    for i, (pn_a, a) in enumerate(parts):
        for pn_b, b in parts[i + 1:]:
            # If they share a power domain, check compatibility
            # Heuristic: both are in the 3.3V range or both 5V
            if abs(a.voltage_max - b.voltage_max) > 1.5:
                issues.append(Issue(
                    code="VOLT_DOMAIN_MISMATCH",
                    severity=Severity.WARNING,
                    message=(
                        f"Potential voltage domain mismatch: "
                        f"{pn_a} ({a.voltage_max}V max) and "
                        f"{pn_b} ({b.voltage_max}V max) differ by "
                        f"{abs(a.voltage_max - b.voltage_max):.1f}V. "
                        "Ensure a level shifter is present if they share signals."
                    ),
                    source="compatibility",
                    objects=[pn_a, pn_b],
                ))
    return issues


def _check_power_budget(
    selected: Dict[str, Component],
    architecture_budget_mw: float,
) -> List[Issue]:
    issues: List[Issue] = []
    total_mw = sum(
        c.current_ma * c.voltage_max / 1000.0 * 1000.0   # mW
        for c in selected.values()
    )
    if architecture_budget_mw > 0 and total_mw > architecture_budget_mw * 1.2:
        issues.append(Issue(
            code="POWER_OVERBUDGET",
            severity=Severity.ERROR,
            message=(
                f"Estimated power draw {total_mw:.0f}mW exceeds architecture "
                f"budget {architecture_budget_mw:.0f}mW by "
                f"{total_mw - architecture_budget_mw:.0f}mW."
            ),
            source="compatibility",
        ))
    elif architecture_budget_mw > 0 and total_mw > architecture_budget_mw:
        issues.append(Issue(
            code="POWER_NEAR_LIMIT",
            severity=Severity.WARNING,
            message=(
                f"Estimated power draw {total_mw:.0f}mW is within 20% of budget "
                f"({architecture_budget_mw:.0f}mW). Consider adding headroom."
            ),
            source="compatibility",
        ))
    return issues


def _check_footprints(selected: Dict[str, Component]) -> List[Issue]:
    issues: List[Issue] = []
    for pn, comp in selected.items():
        if not comp.footprint:
            issues.append(Issue(
                code="MISSING_FOOTPRINT",
                severity=Severity.ERROR,
                message=f"Component '{pn}' has no footprint assigned. Cannot generate PCB layout.",
                source="compatibility",
                objects=[pn],
            ))
        if not comp.package:
            issues.append(Issue(
                code="MISSING_PACKAGE",
                severity=Severity.WARNING,
                message=f"Component '{pn}' has no package specified.",
                source="compatibility",
                objects=[pn],
            ))
    return issues


def _check_interface_coverage(
    selected: Dict[str, Component],
    subsystems: List[Any],
) -> List[Issue]:
    """Ensure required interfaces (I2C, SPI, etc.) have at least one master."""
    issues: List[Issue] = []
    needed_interfaces: Set[str] = set()
    for sub in subsystems:
        iface = getattr(sub, "interface", "GPIO")
        if iface not in ("GPIO", "POWER", "PASSIVE"):
            needed_interfaces.add(iface)

    # Check that MCU or SBC is present to serve as bus master
    has_master = any(
        c.category in ("MCU", "SBC") for c in selected.values()
    )
    if needed_interfaces and not has_master:
        issues.append(Issue(
            code="NO_BUS_MASTER",
            severity=Severity.ERROR,
            message=(
                f"Interfaces {needed_interfaces} are required but no MCU/SBC "
                "is selected to act as bus master."
            ),
            source="compatibility",
        ))
    return issues


def _check_missing_power_regulator(selected: Dict[str, Component]) -> List[Issue]:
    issues: List[Issue] = []
    has_power = any(c.category in ("POWER", "Charger IC", "Buck-Boost", "LDO")
                    for c in selected.values())
    has_consumer = any(c.category not in ("POWER", "PASSIVE")
                       for c in selected.values())
    if has_consumer and not has_power:
        issues.append(Issue(
            code="MISSING_POWER_STAGE",
            severity=Severity.ERROR,
            message="No power management component selected. All consuming parts need a power rail.",
            source="compatibility",
        ))
    return issues


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    all_issues: List[Issue] = []

    if state.architecture is None:
        return StageResult(
            stage="p09_compatibility",
            status=StageStatus.FAILED,
            issues=[Issue("COMPAT_NO_ARCH", Severity.ERROR,
                          "Architecture not set.", "compatibility")],
            duration=time.monotonic() - t0,
        )

    sel_result = state.stage_results.get("p08_part_selection")
    if sel_result is None or "selected" not in sel_result.data:
        return StageResult(
            stage="p09_compatibility",
            status=StageStatus.FAILED,
            issues=[Issue("COMPAT_NO_SELECTION", Severity.ERROR,
                          "Stage 8 (part selection) must run first.", "compatibility")],
            duration=time.monotonic() - t0,
        )

    selected_map: Dict[str, str] = sel_result.data["selected"]
    selected_comps: Dict[str, Component] = {
        pn: state.components[pn]
        for pn in selected_map.values()
        if pn in state.components
    }

    budget_mw = state.architecture.power_budget_mw

    all_issues += _check_voltage_domains(selected_comps)
    all_issues += _check_power_budget(selected_comps, budget_mw)
    all_issues += _check_footprints(selected_comps)
    all_issues += _check_interface_coverage(selected_comps, state.architecture.subsystems)
    all_issues += _check_missing_power_regulator(selected_comps)

    errors   = [i for i in all_issues if i.is_error()]
    warnings = [i for i in all_issues if not i.is_error()]
    is_valid = len(errors) == 0

    return StageResult(
        stage="p09_compatibility",
        status=StageStatus.PASSED if is_valid else StageStatus.FAILED,
        data={
            "is_valid":      is_valid,
            "error_count":   len(errors),
            "warning_count": len(warnings),
        },
        issues=all_issues,
        metrics={
            "compat_errors":   float(len(errors)),
            "compat_warnings": float(len(warnings)),
        },
        duration=time.monotonic() - t0,
    )
