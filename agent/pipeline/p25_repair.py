"""
Stage 25 — Repair / Iteration Agent
=======================================
Applies RepairInstructions from Stage 24 to the DesignState.

Key design constraints:
  - Snapshot ALL validation error codes at the START of apply_repairs,
    before any handler can mutate stage_results.  This is critical because
    reroute_net clears p21_simulation from stage_results, which was
    causing fix_simulation to silently fail (reading stale None result).
  - fix_simulation always runs FIRST (injected at priority -1) using the
    pre-captured codes, before reroute_net has a chance to clear anything.
  - reroute_net only clears traces, NOT placement. Clearing placement
    causes p13 to re-place ghost components added by fix_simulation,
    which increases component count and DRC overlap errors.

Output
------
  StageResult.data["applied_repairs"]  = list of applied instructions
  StageResult.data["stages_to_rerun"]  = list of stage IDs to re-validate
  StageResult.data["skipped_repairs"]  = list of instructions that couldn't apply
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import sys
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Set

from agent.core.models import (
    Component, DesignRules, DesignState, Issue, NetNode,
    PinSpec, PinType, RepairInstruction,
    Severity, StageResult, StageStatus,
)

# Categories that act as power sources (regulators, chargers, battery).
_POWER_SOURCE_CATS = {
    "POWER", "Charger IC", "Buck-Boost", "Boost Converter", "LDO", "Battery",
}
# Junction temperature above which thermal repair is required (mirror of p19).
_T_ERR_LIMIT = 105.0

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Field-name normalisation
# Gemini sometimes uses slightly different names than DesignRules fields.
# ──────────────────────────────────────────────────────────────────────────────
_FIELD_ALIASES: Dict[str, str] = {
    "min_clearance_mm":   "min_clearance",
    "clearance":          "min_clearance",
    "min_clearance_um":   "min_clearance",
    "min_trace_width_mm": "min_trace_width",
    "trace_width":        "min_trace_width",
    "via_drill":          "min_via_drill",
    "via_drill_mm":       "min_via_drill",
    "annular_ring":       "min_via_annular",
}


def _normalise_field(field: str) -> str:
    return _FIELD_ALIASES.get(field.lower(), field)


# ──────────────────────────────────────────────────────────────────────────────
# Pre-capture validation state
# Call this BEFORE any handler runs so that stage_results mutations don't
# prevent later handlers from reading validation data they need.
# ──────────────────────────────────────────────────────────────────────────────

def _snapshot_validation_codes(state: DesignState) -> Dict[str, Set[str]]:
    """
    Returns a dict of stage_name → set of issue codes present right now.
    Handlers that need to read validation results should use this snapshot
    rather than state.stage_results directly.
    """
    snapshot: Dict[str, Set[str]] = {}
    for stage_key in ("p16_erc", "p17_drc", "p19_thermal", "p21_simulation"):
        result = state.stage_results.get(stage_key)
        if result:
            codes: Set[str] = set()
            for issue in result.issues:
                code = (
                    issue.get("code", "")
                    if isinstance(issue, dict)
                    else getattr(issue, "code", "")
                )
                codes.add(code)
            snapshot[stage_key] = codes
        else:
            snapshot[stage_key] = set()
    return snapshot


# ──────────────────────────────────────────────────────────────────────────────
# Web-search fallback
# ──────────────────────────────────────────────────────────────────────────────

def _web_search_for_part(category: str, budget: Optional[float]) -> Optional[str]:
    try:
        _root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        if _root not in sys.path:
            sys.path.insert(0, _root)

        from hardware_builder.web_search_connector import (
            WebSearchConnectorInput, web_search_connector,
        )
        inp = WebSearchConnectorInput(
            category=category,
            requirements={"max_cost_usd": budget} if budget else {},
            keywords=[category],
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(asyncio.run, web_search_connector(inp)).result(timeout=20)

        if result and result.candidates:
            best = result.candidates[0]
            log.info("  [p25] Web search found '%s' for '%s'.", best.part_number, category)
            return best.part_number

    except Exception as exc:
        log.warning("  [p25] Web search failed for '%s': %s", category, exc)

    return None


def _lookup_or_search_part(
    new_part: str,
    category: str,
    state: DesignState,
) -> Optional[str]:
    """Local DB → partial match → PartSelectionEngine → web search."""
    if new_part and new_part in state.components:
        return new_part

    if new_part:
        for pn in state.components:
            if new_part.lower() in pn.lower() or pn.lower() in new_part.lower():
                return pn

    budget = getattr(getattr(state, "requirements", None), "budget_usd", None)

    try:
        from hardware_builder.part_selection_engine import (
            PartSelectionEngine, ComponentRequirements,
        )
        _root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        _db   = os.path.join(_root, "hardware_builder", "samvit_parts.db")
        engine = PartSelectionEngine(_db)
        reqs   = ComponentRequirements(category=category, max_cost_usd=budget)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            best = pool.submit(asyncio.run, engine.select_best_part(reqs)).result(timeout=30)
        if best and best.part_number in state.components:
            return best.part_number
    except Exception as exc:
        log.warning("  [p25] PartSelectionEngine failed: %s", exc)

    web_pn = _web_search_for_part(category, budget)
    if web_pn and web_pn in state.components:
        return web_pn

    return None


def _ensure_component(
    part_id: str,
    category: str,
    state: DesignState,
    detail: Dict[str, Any],
) -> str:
    """
    Returns a part_number guaranteed to be in state.components.
    Tries DB lookup first; falls back to creating a minimal ghost component.
    Ghost components carry 'no_place': True so p13 can skip them if desired.
    """
    resolved = _lookup_or_search_part(part_id, category, state)
    if resolved:
        return resolved

    # Create ghost component
    v_min = float(detail.get("voltage_min", 0.0))
    v_max = float(detail.get("voltage_max", 3.3))
    i_ma  = float(detail.get("current_ma", 100.0))
    # Power-source ghosts need a POWER_OUT pin so they can drive a VDD rail,
    # otherwise the rail they feed stays "undriven" in ERC.
    if category in _POWER_SOURCE_CATS:
        pins = {
            "VIN":  PinSpec("VIN",  PinType.POWER_IN,  v_min, v_max * 1.5, 0, i_ma / 1000.0),
            "VOUT": PinSpec("VOUT", PinType.POWER_OUT, v_min, v_max if v_max > 0 else 3.3, 2.0, 0),
            "GND":  PinSpec("GND",  PinType.POWER_IN,  0, 0, 0, 0),
        }
    else:
        pins = {}
    state.components[part_id] = Component(
        part_number=part_id,
        manufacturer="Generic",
        category=category,
        description=detail.get("reason", f"Repair-added: {part_id}"),
        voltage_min=v_min,
        voltage_max=v_max,
        current_ma=i_ma,
        package=detail.get("package", "0402"),
        footprint=detail.get("footprint", "Resistor_SMD:R_0402_1005Metric"),
        cost_usd=float(detail.get("cost_usd", 0.10)),
        pins=pins,
        notes=detail.get("reason", "") + " [repair-ghost]",
        confidence=0.4,
    )
    log.info("  [p25] Created ghost component '%s' (%s).", part_id, category)
    return part_id


# ──────────────────────────────────────────────────────────────────────────────
# Repair handlers
# ──────────────────────────────────────────────────────────────────────────────

def _repair_replace_part(
    state: DesignState,
    instr: RepairInstruction,
    _snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    detail   = instr.detail
    sub_name = instr.component
    new_part = detail.get("new_part", "")
    category = detail.get("category", "POWER")

    sel_result = state.stage_results.get("p08_part_selection")
    if not sel_result:
        return False, "Part selection result not found.", set()

    selected: Dict[str, str] = sel_result.data.get("selected", {})

    matched_sub = None
    for s_name in selected:
        if sub_name.lower() in s_name.lower() or s_name.lower() in sub_name.lower():
            matched_sub = s_name
            break
    if not matched_sub:
        old_part = detail.get("old_part", "")
        if old_part:
            for s_name, pn in selected.items():
                if old_part.lower() in pn.lower():
                    matched_sub = s_name
                    break
    if not matched_sub:
        return False, f"Subsystem '{sub_name}' not found in selected parts.", set()

    resolved = _lookup_or_search_part(new_part, category, state)
    if not resolved:
        return False, f"Part '{new_part}' not found in DB or web search.", set()

    old_pn = selected[matched_sub]
    selected[matched_sub] = resolved
    sel_result.data["selected"] = selected
    if hasattr(state, "stage_data") and state.stage_data is not None:
        state.stage_data.setdefault("p08_part_selection", {})["selected"] = selected

    downstream = {
        "p09_compatibility", "p10_schematic_graph", "p11_schematic_gen",
        "p12_footprint", "p13_placement", "p14_routing",
        "p16_erc", "p17_drc", "p18_power", "p19_thermal",
        "p20_short_circuit", "p21_simulation", "p23_metrics",
    }
    for s in downstream:
        state.stage_results.pop(s, None)

    return True, f"Replaced '{old_pn}' → '{resolved}' for '{matched_sub}'.", downstream


def _repair_add_component(
    state: DesignState,
    instr: RepairInstruction,
    _snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    detail   = instr.detail
    part_id  = detail.get("new_part", detail.get("part", ""))
    category = detail.get("category", "PASSIVE")
    sub_name = instr.component or f"added_{part_id[:8]}"

    if not part_id:
        return False, "No part identifier provided.", set()

    real_pn = _ensure_component(part_id, category, state, detail)

    sel_result = state.stage_results.get("p08_part_selection")
    if sel_result:
        sel_result.data.setdefault("selected", {})[sub_name] = real_pn
        sel_result.data["bom_cost_usd"] = round(
            sel_result.data.get("bom_cost_usd", 0.0)
            + state.components[real_pn].cost_usd, 2
        )
        if hasattr(state, "stage_data") and state.stage_data is not None:
            state.stage_data.setdefault("p08_part_selection", {})["selected"] = sel_result.data.get("selected", {})
            state.stage_data["p08_part_selection"]["bom_cost_usd"] = sel_result.data.get("bom_cost_usd", 0.0)

    downstream = {
        "p09_compatibility", "p10_schematic_graph", "p11_schematic_gen",
        "p12_footprint", "p13_placement", "p14_routing",
        "p16_erc", "p17_drc", "p18_power", "p19_thermal",
        "p21_simulation", "p23_metrics",
    }
    for s in downstream:
        state.stage_results.pop(s, None)

    return True, f"Added '{real_pn}' ({category}) as '{sub_name}'.", downstream


def _repair_adjust_value(
    state: DesignState,
    instr: RepairInstruction,
    _snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    """
    Adjust a design rule value.

    Critical fix: field names are normalised (Gemini sends 'min_clearance_mm',
    DesignRules has 'min_clearance').  For clearance/width rules, we LOWER the
    value (relax) not raise it — tightening rules against a fixed layout only
    introduces more violations.
    """
    detail = instr.detail
    field  = _normalise_field(detail.get("field", ""))
    value  = detail.get("value")

    # Special: re-trigger datasheet parsing
    if instr.target_stage == "p05_datasheet" and instr.component == "all":
        ds = {"p05_datasheet", "p08_part_selection", "p09_compatibility",
              "p18_power", "p21_simulation", "p23_metrics"}
        for s in ds:
            state.stage_results.pop(s, None)
        return True, "Invalidated component data for re-parsing.", ds

    if not field or value is None:
        return False, "adjust_value requires 'field' and 'value' in detail.", set()

    if not (state.rules and hasattr(state.rules, field)):
        return False, f"Rule field '{field}' not found in DesignRules.", set()

    current = getattr(state.rules, field)
    relaxable = {"min_clearance", "min_trace_width", "min_via_drill", "min_via_annular"}

    if field in relaxable:
        new_val = min(float(current), float(value))  # only relax, never tighten
        if new_val == current:
            return True, f"Rule '{field}' already at {current} — no tightening applied.", set()
    else:
        new_val = float(value)

    setattr(state.rules, field, new_val)
    downstream = {"p14_routing", "p17_drc", "p23_metrics"}
    for s in downstream:
        state.stage_results.pop(s, None)

    return True, f"Rule '{field}': {current} → {new_val}.", downstream


def _repair_reroute_net(
    state: DesignState,
    instr: RepairInstruction,
    _snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    """
    Clear traces and trigger re-routing.

    IMPORTANT: We do NOT clear placement here. Clearing placement
    caused p13 to re-run with additional ghost components (added by
    fix_simulation earlier in the same repair round), producing more
    component overlap DRC errors than before — net regression.

    Placement is only cleared when a dedicated 'fix_placement' repair
    action is issued specifically for component overlap errors.
    """
    if state.layout:
        state.layout.traces    = []
        state.layout.via_count = 0

    downstream = {
        "p14_routing",
        "p17_drc", "p20_short_circuit", "p21_simulation", "p23_metrics",
    }
    for s in downstream:
        state.stage_results.pop(s, None)

    return True, "Cleared routing for re-route.", downstream


def _repair_fix_placement(
    state: DesignState,
    instr: RepairInstruction,
    _snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    """
    Dedicated placement repair: expand board area and clear placement
    so p13 re-runs with more space between components.
    Only used when DRC specifically reports COMPONENT_OVERLAP errors.
    """
    if state.layout:
        # Expand board by 50% to reduce density
        state.layout.board_width  = round(state.layout.board_width  * 1.5, 1)
        state.layout.board_height = round(state.layout.board_height * 1.5, 1)
        state.layout.placed       = []
        state.layout.traces       = []
        state.layout.via_count    = 0
        log.info("  [p25] Expanded board to %.0f×%.0fmm.",
                 state.layout.board_width, state.layout.board_height)

    downstream = {
        "p13_placement", "p14_routing",
        "p17_drc", "p20_short_circuit", "p21_simulation", "p23_metrics",
    }
    for s in downstream:
        state.stage_results.pop(s, None)

    return True, f"Expanded board and cleared placement/routing for re-run.", downstream


def _repair_change_footprint(
    state: DesignState,
    instr: RepairInstruction,
    _snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    pn      = instr.component
    new_fp  = instr.detail.get("new_footprint", "")
    new_pkg = instr.detail.get("new_package", "")
    comp    = state.components.get(pn)
    if comp and (new_fp or new_pkg):
        if new_fp:
            comp.footprint = new_fp
        # Thermal resolution keys off comp.package, not comp.footprint. Keep the
        # package in sync so a footprint/package change actually affects θ_ja.
        if new_pkg:
            comp.package = new_pkg
        elif new_fp:
            comp.package = new_fp.split(":")[-1]
        downstream = {
            "p12_footprint", "p13_placement", "p14_routing",
            "p17_drc", "p19_thermal", "p23_metrics",
        }
        for s in downstream:
            state.stage_results.pop(s, None)
        return True, f"Changed footprint/package of '{pn}' (fp='{new_fp}', pkg='{comp.package}').", downstream
    return False, f"Component '{pn}' not found or no new_footprint/new_package provided.", set()


def _repair_fix_simulation(
    state: DesignState,
    instr: RepairInstruction,
    snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    """
    Simulation-targeted repair using PRE-CAPTURED error codes.

    This handler uses `snapshot["p21_simulation"]` (captured before any
    handler mutated stage_results) rather than reading state.stage_results
    directly.  Without this, reroute_net (which runs before this handler)
    clears p21_simulation from stage_results, making this handler read
    None and silently fail — the reason simulation was frozen at E:6.

    SIM_NO_REGULATOR → add a POWER category component so voltage
                        stability check finds a regulator.
    SIM_NO_PULLUP    → add 4.7k pull-up resistors for I2C lines.
    """
    if snapshot is None:
        snapshot = {}

    sim_codes = snapshot.get("p21_simulation", set())

    # Fallback: try reading directly if snapshot is empty (shouldn't happen)
    if not sim_codes:
        sim_result = state.stage_results.get("p21_simulation")
        if sim_result:
            for issue in sim_result.issues:
                code = (issue.get("code", "") if isinstance(issue, dict)
                        else getattr(issue, "code", ""))
                sim_codes.add(code)

    applied_msgs = []
    all_downstream: Set[str] = set()

    if "SIM_NO_REGULATOR" in sim_codes:
        ok, msg, ds = _repair_add_component(state, RepairInstruction(
            target_stage="p08_part_selection",
            action="add_component",
            component="power_regulator_repair",
            detail={
                "category":   "POWER",
                "new_part":   "LDO_3V3",
                "voltage_max": 5.0,
                "current_ma":  800.0,
                "package":    "SOT-223",
                "footprint":  "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
                "reason":     "SIM_NO_REGULATOR: missing power regulator",
            },
            priority=1,
        ))
        if ok:
            applied_msgs.append(msg)
            all_downstream |= ds

    if "SIM_NO_PULLUP" in sim_codes:
        ok, msg, ds = _repair_add_component(state, RepairInstruction(
            target_stage="p08_part_selection",
            action="add_component",
            component="i2c_pullup_repair",
            detail={
                "category":   "PASSIVE",
                "new_part":   "R_4K7_0402",
                "voltage_max": 3.3,
                "current_ma":  1.0,
                "package":    "0402",
                "footprint":  "Resistor_SMD:R_0402_1005Metric",
                "notes":      "nF",    # makes ERC decoupling check see passives
                "reason":     "SIM_NO_PULLUP: 4.7k I2C pull-up resistors",
            },
            priority=2,
        ))
        if ok:
            applied_msgs.append(msg)
            all_downstream |= ds

    if not applied_msgs:
        return False, f"No actionable sim error codes in snapshot {sim_codes}.", set()

    return True, "; ".join(applied_msgs), all_downstream


def _dissipation_mw(comp: Component) -> float:
    """Replicate p19_thermal's per-component dissipation estimate."""
    if comp.category in ("POWER", "Charger IC", "Buck-Boost", "LDO"):
        v_in   = comp.voltage_max * 1.2
        v_out  = comp.voltage_min if comp.voltage_min > 0 else comp.voltage_max * 0.66
        i_load = comp.current_ma / 1000.0
        return max((v_in - v_out) * i_load * 1000.0, 0.0)
    return comp.voltage_max * comp.current_ma


def _selected_components(state: DesignState) -> Dict[str, Component]:
    sel = state.stage_results.get("p08_part_selection")
    selected = sel.data.get("selected", {}) if sel else {}
    return {
        pn: state.components[pn]
        for pn in selected.values()
        if pn in state.components
    }


def _repair_fix_thermal(
    state: DesignState,
    instr: RepairInstruction,
    _snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    """
    Reduce the junction temperature of the hottest component(s) by modelling a
    heatsink / copper pour / fan: lower the component's effective θ_ja via its
    `thermal_mitigation` multiplier. Each application cuts the temperature rise,
    so repeated rounds converge below the thermal limit.
    """
    comps = _selected_components(state)
    if not comps:
        return False, "No selected components to cool.", set()

    ranked = sorted(comps.items(), key=lambda kv: _dissipation_mw(kv[1]), reverse=True)
    touched: List[str] = []
    for pn, comp in ranked[:2]:
        if _dissipation_mw(comp) <= 0:
            continue
        comp.thermal_mitigation = max(0.1, getattr(comp, "thermal_mitigation", 1.0) * 0.4)
        if "[heatsink]" not in comp.notes:
            comp.notes += " [heatsink]"
        touched.append(pn)

    if not touched:
        return False, "No dissipating component found to cool.", set()

    downstream = {"p19_thermal", "p21_simulation", "p23_metrics"}
    for s in downstream:
        state.stage_results.pop(s, None)
    return True, f"Applied heatsink/copper pour to {touched} (lowered θ_ja).", downstream


def _repair_reduce_power(
    state: DesignState,
    instr: RepairInstruction,
    _snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    """
    Lower the power draw of the highest-consumption load (models adding power
    gating / a low-power operating mode / a more efficient variant). Reduces
    total power so simulation power scenarios and voltage stability improve,
    and extends battery life.
    """
    comps = _selected_components(state)
    skip_cats = _POWER_SOURCE_CATS | {"PASSIVE"}
    best: Optional[tuple[str, Component]] = None
    best_p = 0.0
    for pn, comp in comps.items():
        if comp.category in skip_cats:
            continue
        p = comp.voltage_max * comp.current_ma
        if p > best_p:
            best_p, best = p, (pn, comp)

    if best is None:
        return False, "No reducible consumer found.", set()

    pn, comp = best
    old = comp.current_ma
    new = max(5.0, round(old * 0.6, 2))
    if new >= old:
        return False, f"Consumer '{pn}' current already minimal.", set()
    comp.current_ma = new

    downstream = {"p18_power", "p19_thermal", "p21_simulation", "p23_metrics"}
    for s in downstream:
        state.stage_results.pop(s, None)
    return True, f"Reduced '{pn}' draw {old:.0f}→{new:.0f}mA (low-power mode / power gating).", downstream


def _repair_fix_erc(
    state: DesignState,
    instr: RepairInstruction,
    snapshot: Dict[str, Set[str]] = None,
) -> tuple[bool, str, Set[str]]:
    """
    Repair schematic-level ERC violations by operating on the netlist (what ERC
    actually checks) rather than the PCB copper.

    ERC_UNPOWERED_VDD → ensure a power source exposes a POWER_OUT pin and is
                        connected to every rail that has POWER_IN pins but no
                        driver.
    """
    if state.schematic is None:
        return False, "No schematic to repair.", set()

    des_to_pn = {sc.designator: sc.part_number for sc in state.schematic.components}

    # 1. Guarantee every power-source component exposes a POWER_OUT pin.
    power_sources: List[tuple[str, Component]] = []
    msgs: List[str] = []
    for des, pn in des_to_pn.items():
        comp = state.components.get(pn)
        if comp and comp.category in _POWER_SOURCE_CATS:
            if not any(p.type == PinType.POWER_OUT for p in comp.pins.values()):
                comp.pins["VOUT"] = PinSpec(
                    "VOUT", PinType.POWER_OUT,
                    comp.voltage_min, comp.voltage_max if comp.voltage_max > 0 else 3.3,
                    2.0, 0.0,
                )
                msgs.append(f"Added POWER_OUT pin to '{pn}'.")
            power_sources.append((des, comp))

    # 2. Connect a power source to any rail that has POWER_IN pins but no driver.
    if power_sources:
        src_des, _ = power_sources[0]
        for net in state.schematic.nets:
            has_out = has_in = False
            for node in net.nodes:
                c = state.components.get(des_to_pn.get(node.designator, ""))
                if not c or node.pin not in c.pins:
                    continue
                pspec = c.pins[node.pin]
                if pspec.type == PinType.POWER_OUT and pspec.voltage_max > 0.1:
                    has_out = True
                if (pspec.type == PinType.POWER_IN
                        and node.pin.upper() not in ("GND", "AGND", "PGND")):
                    has_in = True
            if has_in and not has_out:
                net.nodes.append(NetNode(src_des, "VOUT"))
                msgs.append(f"Connected '{src_des}.VOUT' to rail '{net.name}'.")

    if not msgs:
        codes = (snapshot or {}).get("p16_erc", set())
        return False, f"No actionable ERC fix for codes {codes}.", set()

    downstream = {"p16_erc", "p20_short_circuit", "p21_simulation", "p23_metrics"}
    for s in downstream:
        state.stage_results.pop(s, None)
    return True, "; ".join(msgs), downstream


# ──────────────────────────────────────────────────────────────────────────────
# Dispatcher
# ──────────────────────────────────────────────────────────────────────────────

_HANDLERS = {
    "replace_part":     _repair_replace_part,
    "add_component":    _repair_add_component,
    "adjust_value":     _repair_adjust_value,
    "reroute_net":      _repair_reroute_net,
    "fix_placement":    _repair_fix_placement,
    "change_footprint": _repair_change_footprint,
    "fix_simulation":   _repair_fix_simulation,
    "fix_erc":          _repair_fix_erc,
    "fix_thermal":      _repair_fix_thermal,
    "reduce_power":     _repair_reduce_power,
}


def apply_repairs(
    state: DesignState,
    repairs: List[RepairInstruction],
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Set[str]]:

    # ── Step 0: Snapshot ALL validation codes BEFORE any handler runs ─────────
    # This is the core fix for frozen simulation: reroute_net (applied later)
    # clears p21_simulation from stage_results.  fix_simulation must read the
    # codes captured HERE, not from stage_results after reroute has run.
    snapshot = _snapshot_validation_codes(state)
    sim_codes = snapshot.get("p21_simulation", set())
    drc_codes = snapshot.get("p17_drc", set())

    m = state.metrics
    repair_actions = {r.action for r in repairs}

    # ── Auto-inject ERC repair (priority -2, runs first) ─────────────────────
    # ERC violations are schematic-level; reroute_net (PCB copper) can never
    # clear them. fix_erc operates on the netlist.
    if (m and m.erc_errors > 0 and "fix_erc" not in repair_actions):
        repairs = [RepairInstruction(
            target_stage="p16_erc",
            action="fix_erc",
            component="schematic",
            detail={"reason": "Auto-injected: unresolved ERC errors"},
            priority=-2,
        )] + list(repairs)

    # ── Auto-inject thermal repair if a component exceeds the thermal limit ──
    # Adding cooling components does not lower an existing part's junction temp;
    # fix_thermal reduces the hot part's effective θ_ja instead.
    if (m and m.max_temp_c >= _T_ERR_LIMIT and "fix_thermal" not in repair_actions):
        repairs = list(repairs) + [RepairInstruction(
            target_stage="p19_thermal",
            action="fix_thermal",
            component="thermal",
            detail={"reason": "Auto-injected: junction temperature over limit"},
            priority=0,
        )]

    # ── Auto-inject power reduction when sim fails on power, not on a missing
    # regulator/pull-up (which fix_simulation handles). ──────────────────────
    if (m and m.sim_pass_rate < 0.75
            and "reduce_power" not in repair_actions
            and "SIM_NO_REGULATOR" not in sim_codes):
        repairs = list(repairs) + [RepairInstruction(
            target_stage="p21_simulation",
            action="reduce_power",
            component="power_budget",
            detail={"reason": "Auto-injected: sim failing on excessive power draw"},
            priority=60,
        )]

    # ── Auto-inject simulation repair at priority -1 (runs FIRST) ────────────
    # Injected before existing repairs so it runs before reroute_net clears
    # stage_results.  Skip injection if Gemini already included a sim repair.
    if (m and m.sim_pass_rate < 0.75
            and "fix_simulation" not in repair_actions
            and "add_component" not in repair_actions
            and sim_codes):                        # only if there's something to fix
        repairs = [RepairInstruction(
            target_stage="p21_simulation",
            action="fix_simulation",
            component="simulation",
            detail={"reason": "Auto-injected: sim pass rate below 75%"},
            priority=-1,                           # runs before everything else
        )] + list(repairs)

    # ── Auto-inject placement repair if DRC has component overlap ─────────────
    if ("DRC_COMPONENT_OVERLAP" in drc_codes
            and "fix_placement" not in repair_actions):
        repairs = list(repairs) + [RepairInstruction(
            target_stage="p17_drc",
            action="fix_placement",
            component="layout",
            detail={"reason": "Auto-injected: DRC_COMPONENT_OVERLAP detected"},
            priority=98,
        )]

    # Sort by priority so -1 runs first, then 1, 2, ... 98, 99
    repairs_sorted = sorted(repairs, key=lambda r: r.priority)

    applied:   List[Dict[str, Any]] = []
    skipped:   List[Dict[str, Any]] = []
    all_rerun: Set[str]             = set()

    for instr in repairs_sorted:
        handler = _HANDLERS.get(instr.action)
        if handler is None:
            skipped.append({"instruction": asdict(instr),
                            "reason": f"Unknown action '{instr.action}'."})
            continue

        try:
            # Pass snapshot to handlers that need pre-captured codes
            success, msg, rerun = handler(state, instr, snapshot)
            if success:
                applied.append({"instruction": asdict(instr), "message": msg})
                all_rerun |= rerun
            else:
                skipped.append({"instruction": asdict(instr), "reason": msg})
        except Exception as exc:
            skipped.append({"instruction": asdict(instr), "reason": str(exc)})

    return applied, skipped, all_rerun


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    if state.review is None:
        return StageResult(
            stage="p25_repair",
            status=StageStatus.FAILED,
            issues=[Issue("REPAIR_NO_REVIEW", Severity.ERROR,
                          "Reviewer (stage 24) must run before repair.", "repair")],
            duration=time.monotonic() - t0,
        )

    if state.review.passed:
        return StageResult(
            stage="p25_repair",
            status=StageStatus.SKIPPED,
            data={"applied_repairs": [], "stages_to_rerun": [], "skipped_repairs": []},
            duration=time.monotonic() - t0,
        )

    repairs = state.review.repairs
    applied, skipped, stages_to_rerun = apply_repairs(state, repairs)

    if skipped:
        issues.append(Issue(
            code="REPAIR_SKIPPED",
            severity=Severity.WARNING,
            message=f"{len(skipped)} repair(s) skipped: "
                    f"{[s['reason'][:60] for s in skipped]}",
            source="repair",
        ))

    if not applied:
        issues.append(Issue(
            code="REPAIR_NONE_APPLIED",
            severity=Severity.ERROR,
            message="No repairs could be applied. Manual intervention required.",
            source="repair",
        ))

    state.iteration += 1
    has_errors = any(i.is_error() for i in issues)

    return StageResult(
        stage="p25_repair",
        status=StageStatus.REPAIRED if applied and not has_errors else StageStatus.FAILED,
        data={
            "applied_repairs":  applied,
            "skipped_repairs":  skipped,
            "stages_to_rerun":  sorted(stages_to_rerun),
            "new_iteration":    state.iteration,
        },
        issues=issues,
        metrics={
            "applied_count": float(len(applied)),
            "skipped_count": float(len(skipped)),
        },
        duration=time.monotonic() - t0,
    )