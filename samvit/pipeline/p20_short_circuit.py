"""
Stage 20 — Short-Circuit Detector
=====================================
Flags invalid power paths and short-circuit conditions:
  • Power rails of different voltages connected to the same net
  • Output-to-output drivers on a net (caught also by ERC but
    repeated here at layout level for trace-level shorts)
  • Ground plane merges that bypass protection
  • Net with both POWER_OUT and GND pins (power rail to GND short)

Deterministic — no Gemini call.
"""

from __future__ import annotations

import time
from typing import Dict, List, Set, Tuple

from samvit.core.models import (
    Component, DesignState, Issue, Net, PinType,
    Severity, StageResult, StageStatus,
)


def _check_power_to_gnd_short(
    nets: List[Net],
    components: Dict[str, Component],
    des_to_pn: Dict[str, str],
) -> List[Issue]:
    """Flag any net that contains both a POWER_OUT pin and a GND pin."""
    issues = []
    for net in nets:
        has_power_out = False
        has_gnd       = False
        power_pins    = []
        gnd_pins      = []
        for node in net.nodes:
            pn   = des_to_pn.get(node.designator, "")
            comp = components.get(pn)
            if not comp or node.pin not in comp.pins:
                continue
            pspec = comp.pins[node.pin]
            if pspec.type == PinType.POWER_OUT and pspec.voltage_max > 0.1:
                has_power_out = True
                power_pins.append(f"{node.designator}.{node.pin}")
            if pspec.type == PinType.POWER_IN and pspec.voltage_max == 0.0:
                has_gnd = True
                gnd_pins.append(f"{node.designator}.{node.pin}")

        if has_power_out and has_gnd:
            issues.append(Issue(
                code="SHORT_POWER_TO_GND",
                severity=Severity.ERROR,
                message=(
                    f"Net '{net.name}' contains POWER_OUT pins {power_pins} "
                    f"AND GND pins {gnd_pins}. This is a power-to-ground short circuit."
                ),
                source="short_circuit",
                objects=[p.split(".")[0] for p in power_pins + gnd_pins],
            ))
    return issues


def _check_cross_rail_shorts(
    nets: List[Net],
    components: Dict[str, Component],
    des_to_pn: Dict[str, str],
) -> List[Issue]:
    """Flag nets where two POWER_OUT pins drive different voltages."""
    issues = []
    for net in nets:
        drivers: List[Tuple[str, float]] = []
        for node in net.nodes:
            pn   = des_to_pn.get(node.designator, "")
            comp = components.get(pn)
            if not comp or node.pin not in comp.pins:
                continue
            pspec = comp.pins[node.pin]
            if pspec.type == PinType.POWER_OUT and pspec.voltage_max > 0.1:
                drivers.append((f"{node.designator}.{node.pin}", pspec.voltage_max))

        if len(drivers) > 1:
            voltages = set(v for _, v in drivers)
            if len(voltages) > 1:
                issues.append(Issue(
                    code="SHORT_CROSS_RAIL",
                    severity=Severity.ERROR,
                    message=(
                        f"Net '{net.name}' has {len(drivers)} power outputs at "
                        f"different voltages {sorted(voltages)}V. "
                        f"Drivers: {[d for d, _ in drivers]}."
                    ),
                    source="short_circuit",
                    objects=[d.split(".")[0] for d, _ in drivers],
                ))
    return issues


def _check_missing_protection(
    components: Dict[str, Component],
    selected_pns: List[str],
) -> List[Issue]:
    """Warn if no reverse-polarity or overvoltage protection is present."""
    issues = []
    has_battery = any(
        "battery" in components[pn].category.lower()
        for pn in selected_pns if pn in components
    )
    has_protection = any(
        components[pn].category in ("Diode", "PROTECTION", "MOSFET")
        for pn in selected_pns if pn in components
    )
    if has_battery and not has_protection:
        issues.append(Issue(
            code="SHORT_NO_PROTECTION",
            severity=Severity.WARNING,
            message=(
                "Battery detected but no reverse-polarity or overvoltage protection "
                "component found. Add a Schottky diode or P-MOSFET for battery protection."
            ),
            source="short_circuit",
        ))
    return issues


def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    all_issues: List[Issue] = []

    if state.schematic is None:
        return StageResult(
            stage="p20_short_circuit",
            status=StageStatus.FAILED,
            issues=[Issue("SC_NO_SCH", Severity.ERROR,
                          "Schematic not available.", "short_circuit")],
            duration=time.monotonic() - t0,
        )

    des_to_pn: Dict[str, str] = {
        sc.designator: sc.part_number
        for sc in state.schematic.components
    }

    sel_result = state.stage_results.get("p08_part_selection")
    selected_pns = list(sel_result.data.get("selected", {}).values()) if sel_result else []

    all_issues += _check_power_to_gnd_short(state.schematic.nets, state.components, des_to_pn)
    all_issues += _check_cross_rail_shorts(state.schematic.nets, state.components, des_to_pn)
    all_issues += _check_missing_protection(state.components, selected_pns)

    errors   = [i for i in all_issues if i.is_error()]
    is_clean = len(errors) == 0

    return StageResult(
        stage="p20_short_circuit",
        status=StageStatus.PASSED if is_clean else StageStatus.FAILED,
        data={
            "is_clean":      is_clean,
            "sc_errors":     [e.to_dict() for e in errors],
            "sc_warnings":   [w.to_dict() for w in all_issues if not w.is_error()],
        },
        issues=all_issues,
        metrics={"sc_error_count": float(len(errors))},
        duration=time.monotonic() - t0,
    )
