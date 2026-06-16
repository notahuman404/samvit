"""
Stage 11 — Schematic Generator
================================
Converts the schematic graph into a KiCad 6/7 schematic intermediate
representation (text format .kicad_sch) that can be opened directly
in KiCad.

Deterministic — no Gemini call.

Output
------
  StageResult.data["kicad_sch"] = KiCad schematic text
  StageResult.data["symbol_count"]
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from samvit.core.models import (
    DesignState, Issue, Net, Schematic, SchematicComponent,
    Severity, StageResult, StageStatus,
)

# KiCad 6 schematic skeleton
_SCH_HEADER = """\
(kicad_sch
  (version 20230121)
  (generator "samvit-hardware-agent")
  (paper "A4")
  (title_block
    (title "{title}")
    (rev "{revision}")
    (company "Samvit AI Pipeline")
  )
"""

_SCH_FOOTER = ")\n"


def _sym_lib_ref(category: str) -> str:
    """Map category to a KiCad symbol library reference."""
    mapping = {
        "MCU":       "MCU_Espressif:ESP32-WROOM-32",
        "SBC":       "Connector:Conn_01x04",
        "POWER":     "power:VDD",
        "SENSOR":    "Device:Sensor",
        "ACTUATOR":  "Device:Motor",
        "COMMS":     "RF_Module:HM-11",
        "AUDIO":     "Amplifier_Audio:PAM8403",
        "DISPLAY":   "Display_OLED:SSD1306",
        "MEMORY":    "Memory_Flash:W25Q128JVxIM",
        "INTERFACE": "Interface_Expansion:MCP23017_SP",
        "PASSIVE":   "Device:R",
        "PROTECTION":"Device:D",
    }
    return mapping.get(category, "Device:R")


def _sch_symbol(comp: SchematicComponent, category: str, idx: int) -> str:
    """Render one component symbol block in KiCad s-expr format."""
    lib_ref = _sym_lib_ref(category)
    lib, part = (lib_ref.split(":", 1) + ["?"])[:2]
    x, y = comp.position
    return f"""
  (symbol (lib_id "{lib_ref}")
    (at {x:.2f} {y:.2f} 0)
    (unit 1)
    (in_bom yes) (on_board yes)
    (property "Reference" "{comp.designator}" (at {x:.2f} {y + 2:.2f} 0))
    (property "Value"     "{comp.value}"      (at {x:.2f} {y - 2:.2f} 0))
    (property "Footprint" ""                  (at 0 0 0))
  )"""


def _sch_wire(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"""
  (wire (pts (xy {x1:.2f} {y1:.2f}) (xy {x2:.2f} {y2:.2f}))
    (stroke (width 0) (type default))
  )"""


def _sch_label(name: str, x: float, y: float) -> str:
    return f"""
  (net_tie_pad_groups "")
  (global_label "{name}"
    (shape input) (at {x:.2f} {y:.2f} 0) (fields_autoplaced)
    (effects (font (size 1.27 1.27)))
  )"""


def generate_kicad_sch(schematic: Schematic, categories: Dict[str, str]) -> str:
    parts: List[str] = [_SCH_HEADER.format(
        title=schematic.title, revision=schematic.revision
    )]

    for i, comp in enumerate(schematic.components):
        cat = categories.get(comp.part_number, "PASSIVE")
        parts.append(_sch_symbol(comp, cat, i))

    # Simple bus wire stubs for each net
    for i, net in enumerate(schematic.nets):
        if len(net.nodes) >= 2:
            # Draw a wire from first node position to second (approximate)
            parts.append(_sch_wire(0, float(i * 5), 10, float(i * 5)))
            parts.append(_sch_label(net.name, 10, float(i * 5)))

    parts.append(_SCH_FOOTER)
    return "".join(parts)


def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    if state.schematic is None:
        return StageResult(
            stage="p11_schematic_gen",
            status=StageStatus.FAILED,
            issues=[Issue("SCHGEN_NO_GRAPH", Severity.ERROR,
                          "Schematic graph (stage 10) must run first.", "schematic_gen")],
            duration=time.monotonic() - t0,
        )

    # Build category map: part_number → category
    categories: Dict[str, str] = {
        pn: comp.category for pn, comp in state.components.items()
    }

    try:
        kicad_text = generate_kicad_sch(state.schematic, categories)
        return StageResult(
            stage="p11_schematic_gen",
            status=StageStatus.PASSED,
            data={
                "kicad_sch":    kicad_text,
                "symbol_count": len(state.schematic.components),
                "net_count":    len(state.schematic.nets),
            },
            metrics={
                "symbol_count": float(len(state.schematic.components)),
            },
            duration=time.monotonic() - t0,
        )
    except Exception as exc:
        return StageResult(
            stage="p11_schematic_gen",
            status=StageStatus.FAILED,
            issues=[Issue("SCHGEN_ERROR", Severity.ERROR,
                          f"Schematic generation failed: {exc}", "schematic_gen")],
            duration=time.monotonic() - t0,
        )
