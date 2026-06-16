"""
Stage 16 — Electrical Rules Check (ERC)
=========================================
Checks the schematic for electrical violations:
  • Unconnected pins
  • Output-to-output conflicts on the same net
  • Power pins not connected to a power net
  • Missing decoupling capacitors for ICs
  • Net with no driver

Deterministic — no Gemini call.

Output
------
  StageResult.data["erc_errors"], ["erc_warnings"]
  StageResult.data["is_clean"] = bool
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Set, Tuple

from samvit.core.models import (
    Component, DesignState, Issue, Net, NetNode,
    PinType, Schematic, Severity, StageResult, StageStatus,
)


# ──────────────────────────────────────────────────────────────────────────────
# ERC rules
# ──────────────────────────────────────────────────────────────────────────────

def _check_undriven_nets(
    nets: List[Net], components: Dict[str, Component],
    des_to_pn: Dict[str, str],
) -> List[Issue]:
    """Flag nets that have only passive / input pins and no driver."""
    issues = []
    for net in nets:
        driver_types = {PinType.POWER_OUT, PinType.DIGITAL_OUT, PinType.ANALOG_OUT}
        has_driver = False
        for node in net.nodes:
            pn   = des_to_pn.get(node.designator, "")
            comp = components.get(pn)
            if comp and node.pin in comp.pins:
                if comp.pins[node.pin].type in driver_types:
                    has_driver = True
                    break
        if not has_driver and len(net.nodes) > 1:
            # Power rail nets (GND, VDD) are self-driven — skip
            if any(kw in net.name.upper() for kw in ("GND", "VDD", "VCC", "VBAT", "5V", "3V3")):
                continue
            issues.append(Issue(
                code="ERC_UNDRIVEN_NET",
                severity=Severity.WARNING,
                message=f"Net '{net.name}' has no driving source (all pins are inputs or passive).",
                source="erc",
                objects=[n.designator for n in net.nodes],
            ))
    return issues


def _check_output_conflicts(
    nets: List[Net], components: Dict[str, Component],
    des_to_pn: Dict[str, str],
) -> List[Issue]:
    """Flag nets with multiple active output drivers (short-circuit hazard)."""
    issues = []
    output_types = {PinType.POWER_OUT, PinType.DIGITAL_OUT, PinType.ANALOG_OUT}
    for net in nets:
        drivers = []
        for node in net.nodes:
            pn   = des_to_pn.get(node.designator, "")
            comp = components.get(pn)
            if comp and node.pin in comp.pins:
                if comp.pins[node.pin].type in output_types:
                    drivers.append(f"{node.designator}.{node.pin}")
        if len(drivers) > 1:
            issues.append(Issue(
                code="ERC_OUTPUT_CONFLICT",
                severity=Severity.ERROR,
                message=(
                    f"Net '{net.name}' has {len(drivers)} active drivers: "
                    f"{', '.join(drivers)}. Risk of short-circuit."
                ),
                source="erc",
                objects=[d.split(".")[0] for d in drivers],
            ))
    return issues


def _check_power_pin_connectivity(
    nets: List[Net], components: Dict[str, Component],
    des_to_pn: Dict[str, str],
) -> List[Issue]:
    """Ensure every VDD pin is on a net that has at least one POWER_OUT."""
    issues = []
    # Build power_out_nets
    power_nets: Set[str] = set()
    for net in nets:
        for node in net.nodes:
            pn   = des_to_pn.get(node.designator, "")
            comp = components.get(pn)
            if comp and node.pin in comp.pins:
                if comp.pins[node.pin].type == PinType.POWER_OUT:
                    power_nets.add(net.name)

    for net in nets:
        vdd_pins = [
            node for node in net.nodes
            if (
                comp := components.get(des_to_pn.get(node.designator, ""))
            ) and node.pin in comp.pins
            and comp.pins[node.pin].type == PinType.POWER_IN
            and node.pin.upper() not in ("GND", "AGND", "PGND")
        ]
        if vdd_pins and net.name not in power_nets:
            issues.append(Issue(
                code="ERC_UNPOWERED_VDD",
                severity=Severity.ERROR,
                message=(
                    f"Net '{net.name}' has VDD pins but no power source connected: "
                    f"{[f'{n.designator}.{n.pin}' for n in vdd_pins]}."
                ),
                source="erc",
                objects=[n.designator for n in vdd_pins],
            ))
    return issues


def _check_missing_decoupling(
    components: Dict[str, Component],
    selected_pns: List[str],
) -> List[Issue]:
    """Warn if an IC (MCU/SBC/SENSOR) has no decoupling capacitor in the BOM."""
    issues = []
    ic_cats  = {"MCU", "SBC", "SENSOR", "COMMS", "AUDIO", "DISPLAY"}
    has_cap  = any(
        comp.category in ("Capacitor", "PASSIVE") and "nF" in comp.notes.upper()
        for pn in selected_pns
        if (comp := components.get(pn))
    )
    ic_count = sum(
        1 for pn in selected_pns
        if (comp := components.get(pn)) and comp.category in ic_cats
    )
    if ic_count > 0 and not has_cap:
        issues.append(Issue(
            code="ERC_MISSING_DECOUPLING",
            severity=Severity.WARNING,
            message=(
                f"{ic_count} IC(s) detected but no decoupling capacitor found in BOM. "
                "Add 100nF MLCC close to each IC's VDD pin."
            ),
            source="erc",
        ))
    return issues


def _check_floating_inputs(
    nets: List[Net], components: Dict[str, Component],
    des_to_pn: Dict[str, str],
    all_net_pins: Set[Tuple[str, str]],
) -> List[Issue]:
    """Flag input pins that appear in no net (floating)."""
    issues = []
    for pn, comp in components.items():
        for pin_name, pin_spec in comp.pins.items():
            if pin_spec.type in (PinType.DIGITAL_IN, PinType.ANALOG_IN):
                # Find designator (reverse lookup)
                for des, dp in des_to_pn.items():
                    if dp == pn:
                        if (des, pin_name) not in all_net_pins:
                            issues.append(Issue(
                                code="ERC_FLOATING_INPUT",
                                severity=Severity.WARNING,
                                message=(
                                    f"Input pin {des}.{pin_name} is not connected to any net. "
                                    "Add pull-up/pull-down resistor or connect to signal."
                                ),
                                source="erc",
                                objects=[des],
                            ))
    return issues


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    all_issues: List[Issue] = []

    if state.schematic is None:
        return StageResult(
            stage="p16_erc",
            status=StageStatus.FAILED,
            issues=[Issue("ERC_NO_SCH", Severity.ERROR,
                          "Schematic not available (run stages 10–11 first).", "erc")],
            duration=time.monotonic() - t0,
        )

    sel_result = state.stage_results.get("p08_part_selection")
    selected_pns: List[str] = list(
        sel_result.data.get("selected", {}).values()
    ) if sel_result else []

    # Build designator → part_number map from schematic components
    des_to_pn: Dict[str, str] = {
        sc.designator: sc.part_number
        for sc in state.schematic.components
    }

    # Build set of all (designator, pin) tuples that appear in any net
    all_net_pins: Set[Tuple[str, str]] = {
        (node.designator, node.pin)
        for net in state.schematic.nets
        for node in net.nodes
    }

    all_issues += _check_output_conflicts(state.schematic.nets, state.components, des_to_pn)
    all_issues += _check_power_pin_connectivity(state.schematic.nets, state.components, des_to_pn)
    all_issues += _check_undriven_nets(state.schematic.nets, state.components, des_to_pn)
    all_issues += _check_missing_decoupling(state.components, selected_pns)
    all_issues += _check_floating_inputs(
        state.schematic.nets, state.components, des_to_pn, all_net_pins
    )

    errors   = [i for i in all_issues if i.is_error()]
    warnings = [i for i in all_issues if not i.is_error()]
    is_clean = len(errors) == 0

    return StageResult(
        stage="p16_erc",
        status=StageStatus.PASSED if is_clean else StageStatus.FAILED,
        data={
            "is_clean":    is_clean,
            "erc_errors":  [e.to_dict() for e in errors],
            "erc_warnings": [w.to_dict() for w in warnings],
        },
        issues=all_issues,
        metrics={
            "erc_error_count":   float(len(errors)),
            "erc_warning_count": float(len(warnings)),
        },
        duration=time.monotonic() - t0,
    )
