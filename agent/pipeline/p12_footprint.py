"""
Stage 12 — Footprint Mapper
==============================
Maps each selected component to a valid KiCad PCB footprint string.
Falls back to package-name heuristics when no footprint is stored.

Deterministic — no Gemini call.

Output
------
  StageResult.data["footprint_map"] = {part_number: kicad_footprint}
  StageResult.data["missing"]       = [part_numbers without footprint]
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from agent.core.models import (
    Component, DesignState, Issue, Severity,
    StageResult, StageStatus,
)

# ──────────────────────────────────────────────────────────────────────────────
# Footprint lookup tables
# ──────────────────────────────────────────────────────────────────────────────

# Known part_number → exact KiCad footprint
_EXACT: Dict[str, str] = {
    "ESP32-WROOM-32":       "RF_Module:ESP32-WROOM-32",
    "STM32F103C8T6":        "Package_QFP:LQFP-48_7x7mm_P0.5mm",
    "Arduino Nano":         "Module:Arduino_Nano",
    "Raspberry Pi 4B":      "Module:RPi4B",
    "Raspberry Pi Zero 2W": "Module:RPiZero2",
    "Intel RealSense D435": "Connector:Conn_01x04_Female",
    "OAK-D Lite":           "Connector:Conn_01x04_Female",
    "TF-Luna LiDAR":        "Module:TF-Luna",
    "VL53L1X":              "OptoDevice:ST_VL53L1x_SXGA",
    "DRV2605L":             "Package_SON:WSON-10_3x3mm_P0.5mm",
    "ERM Vibration Motor 10mm": "Connector:Conn_01x02",
    "LRA Linear Resonant Actuator": "Connector:Conn_01x02",
    "PAM8403":              "Package_SO:SOP-16_3.9x9.9mm_P1.27mm",
    "MAX98357A":            "Package_DFN_QFN:DFN-8_2x2mm_P0.5mm",
    "TP4056":               "Package_SO:SOP-8_3.9x4.9mm_P1.27mm",
    "BQ24295":              "Package_DFN_QFN:VQFN-24_4x4mm_P0.5mm",
    "TPS63020":             "Package_SON:VSON-10_3x3mm_P0.5mm",
    "MT3608":               "Package_TO_SOT_SMD:SOT-23-6",
    "18650 Li-Ion Cell":    "Battery:BatteryHolder_18650_Horizontal",
    "MPU-6050":             "Package_LCC:CLCC-24",
    "ICM-42688-P":          "Package_LGA:LGA-14_3x2.5mm_P0.65mm",
    "BNO055":               "Package_LGA:LGA-28_5.2x3.8mm_P0.65mm",
    "BMP280":               "Package_LGA:LGA-8_2x2.5mm_P0.65mm",
    "HC-05 Bluetooth":      "Module:HC-05",
    "nRF52840":             "Package_DFN_QFN:AQFN-73",
    "SIM7600G-H":           "Module:SIM7600",
    "LoRa Ra-02 SX1278":    "Module:Ra-02",
    "INMP441":              "Package_LCC:LCC-6",
    "SPH0645LM4H":          "Package_LCC:LCC-6",
    "MAX9814":              "Package_DFN_QFN:TDFN-8_2x2mm_P0.5mm",
    "SSD1306 OLED 0.96\"":  "Display_OLED:SSD1306",
    "WS2812B":              "LED_SMD:LED_5050_PLCC6_5.3x5.3mm",
    "W25Q128":              "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
    "MicroSD Module":       "Connector:Conn_MicroSD",
    "TXS0108E":             "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    "PCA9685":              "Package_SO:TSSOP-28_4.4x9.7mm_P0.65mm",
    "MCP23017":             "Package_SO:SOIC-28W_7.5x18.16mm_P1.27mm",
    "74AHCT125":            "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    "USB-C Receptacle":     "Connector_USB:USB_C_Receptacle_GCT_USB4085",
    "JST PH 2-pin":         "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical",
    "100nF MLCC 0402":      "Capacitor_SMD:C_0402_1005Metric",
    "10uF Electrolytic":    "Capacitor_THT:CP_Radial_D5.0mm_P2.50mm",
    "10k Resistor 0402":    "Resistor_SMD:R_0402_1005Metric",
    "1N4007 Diode":         "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal",
    "SS34 Schottky":        "Diode_SMD:D_SMA",
    "AMS1117-3.3":          "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
    "IRF540N MOSFET":       "Package_TO_SOT_THT:TO-220-3_Vertical",
    "IRLML6244 MOSFET":     "Package_TO_SOT_SMD:SOT-23",
    "Raspberry Pi Camera v3": "Connector:Conn_01x02",
}

# Package suffix → generic KiCad footprint
_PACKAGE_MAP: Dict[str, str] = {
    "QFN":     "Package_DFN_QFN:QFN-{n}_{w}x{h}mm",
    "DFN":     "Package_DFN_QFN:DFN-{n}_{w}x{h}mm",
    "TSSOP":   "Package_SO:TSSOP-{n}_4.4x{h}mm_P0.65mm",
    "SOIC":    "Package_SO:SOIC-{n}_3.9x{h}mm_P1.27mm",
    "SOP":     "Package_SO:SOP-{n}_3.9x{h}mm_P1.27mm",
    "SOT-23":  "Package_TO_SOT_SMD:SOT-23",
    "SOT23":   "Package_TO_SOT_SMD:SOT-23",
    "TO-220":  "Package_TO_SOT_THT:TO-220-3_Vertical",
    "LGA":     "Package_LGA:LGA-{n}",
    "LQFP":    "Package_QFP:LQFP-{n}_7x7mm_P0.5mm",
    "VSON":    "Package_SON:VSON-{n}_3x3mm_P0.5mm",
    "DO-41":   "Diode_THT:D_DO-41_SOD81_P10.16mm_Horizontal",
    "SMA":     "Diode_SMD:D_SMA",
    "0402":    "Resistor_SMD:R_0402_1005Metric",
    "0603":    "Resistor_SMD:R_0603_1608Metric",
    "Module":  "Connector:Conn_01x04_Female",
    "Board":   "Connector:Conn_01x04_Female",
}


def _resolve_footprint(comp: Component) -> Optional[str]:
    # 1. Exact match by part number
    fp = _EXACT.get(comp.part_number)
    if fp:
        return fp

    # 2. Stored footprint (from DB or datasheet parser)
    if comp.footprint and comp.footprint not in ("-", ""):
        # If it already looks like a KiCad lib:fp string, trust it
        if ":" in comp.footprint:
            return comp.footprint
        # Otherwise try package-map lookup using the footprint as package hint
        pkg = comp.footprint

    else:
        pkg = comp.package

    if not pkg:
        return None

    # 3. Package string heuristic
    pkg_upper = pkg.upper()
    for suffix, template in _PACKAGE_MAP.items():
        if suffix.upper() in pkg_upper:
            import re
            n_m = re.search(r"-(\d+)", pkg)
            n   = n_m.group(1) if n_m else "8"
            return template.replace("{n}", n).replace("{w}", "3").replace("{h}", "3")

    # 4. Last resort: generic connector
    return "Connector:Conn_01x02"


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    sel_result = state.stage_results.get("p08_part_selection")
    if sel_result is None:
        return StageResult(
            stage="p12_footprint",
            status=StageStatus.FAILED,
            issues=[Issue("FP_NO_PARTS", Severity.ERROR,
                          "Part selection (stage 8) must run first.", "footprint")],
            duration=time.monotonic() - t0,
        )

    selected_pns = list(sel_result.data.get("selected", {}).values())
    footprint_map: Dict[str, str] = {}
    missing: List[str] = []

    for pn in selected_pns:
        comp = state.components.get(pn)
        if comp is None:
            missing.append(pn)
            continue
        fp = _resolve_footprint(comp)
        if fp:
            footprint_map[pn] = fp
            # Update component record
            comp.footprint = fp
        else:
            missing.append(pn)
            issues.append(Issue(
                code="FP_NOT_FOUND",
                severity=Severity.WARNING,
                message=f"No KiCad footprint found for '{pn}' (package='{comp.package}'). Using generic.",
                source="footprint",
                objects=[pn],
            ))
            footprint_map[pn] = "Connector:Conn_01x02"
            comp.footprint = "Connector:Conn_01x02"

    has_errors = any(i.is_error() for i in issues)
    return StageResult(
        stage="p12_footprint",
        status=StageStatus.PASSED if not has_errors else StageStatus.FAILED,
        data={
            "footprint_map": footprint_map,
            "missing":       missing,
        },
        metrics={
            "mapped_count":  float(len(footprint_map)),
            "missing_count": float(len(missing)),
        },
        issues=issues,
        duration=time.monotonic() - t0,
    )
