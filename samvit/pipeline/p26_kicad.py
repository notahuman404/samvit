"""
Stage 26 — KiCad Project Writer
==================================
Writes a complete KiCad 6/7 project from the current DesignState:
  • project.kicad_pro    — project configuration
  • schematic.kicad_sch  — schematic (from Stage 11)
  • layout.kicad_pcb     — PCB layout (from Stages 13–14)

All files are returned as strings in StageResult.data so the
CheckpointManager can save them without disk writes.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from samvit.core.models import (
    DesignRules, DesignState, Issue, PCBLayout, PlacedComponent,
    Severity, StageResult, StageStatus, TraceSegment,
)

# ──────────────────────────────────────────────────────────────────────────────
# KiCad project file
# ──────────────────────────────────────────────────────────────────────────────

def _make_pro(project_name: str, revision: str) -> str:
    cfg = {
        "meta": {"filename": f"{project_name}.kicad_pro", "version": 1},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "pcbnew": {
            "last_paths": {},
            "page_layout_descr_file": "",
            "plot_directory": "./gerbers/",
            "spice_adjust_passive_values": False,
        },
        "text_variables": {"REVISION": revision, "PROJECT": project_name},
    }
    return json.dumps(cfg, indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# KiCad PCB file
# ──────────────────────────────────────────────────────────────────────────────

_PCB_HEADER = """\
(kicad_pcb
  (version 20230121)
  (generator "samvit-hardware-agent")
  (general
    (thickness {thickness:.2f})
  )
  (paper "A4")
  (title_block
    (title "{title}")
    (rev "{revision}")
    (company "Samvit AI Pipeline")
  )
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user)
    (33 "F.Adhes" user)
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user)
    (37 "F.SilkS" user)
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (44 "Edge.Cuts" user)
  )
  (setup
    (pad_to_mask_clearance 0.051)
    (pcbplotparams
      (layerselection 0x00010fc_ffffffff)
      (outputdirectory "gerbers/")
    )
  )
"""

_PCB_FOOTER = ")\n"


def _pcb_edge_cuts(width: float, height: float) -> str:
    return (
        f'  (gr_rect (start 0 0) (end {width:.2f} {height:.2f}) '
        f'(layer "Edge.Cuts") (width 0.05))\n'
    )


def _pcb_footprint(comp: PlacedComponent) -> str:
    fp = comp.footprint.replace('"', '\\"')
    return (
        f'  (footprint "{fp}"\n'
        f'    (layer "{comp.layer}")\n'
        f'    (at {comp.x:.2f} {comp.y:.2f} {comp.rotation:.1f})\n'
        f'    (property "Reference" "{comp.designator}" (at 0 3 0) (layer "F.SilkS"))\n'
        f'    (property "Value"     "{comp.footprint}" (at 0 -3 0) (layer "F.Fab"))\n'
        f'  )\n'
    )


def _pcb_segment(seg: TraceSegment) -> str:
    return (
        f'  (segment (start {seg.x1:.3f} {seg.y1:.3f}) '
        f'(end {seg.x2:.3f} {seg.y2:.3f}) '
        f'(width {seg.width:.3f}) (layer "{seg.layer}") '
        f'(net 0))\n'
    )


def generate_kicad_pcb(layout: PCBLayout, rules: DesignRules, title: str, revision: str) -> str:
    parts = [_PCB_HEADER.format(thickness=rules.board_thickness, title=title, revision=revision)]
    parts.append(_pcb_edge_cuts(layout.board_width, layout.board_height))
    for comp in layout.placed:
        parts.append(_pcb_footprint(comp))
    for seg in layout.traces:
        parts.append(_pcb_segment(seg))
    parts.append(_PCB_FOOTER)
    return "".join(parts)


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    req      = state.requirements
    schematic = state.schematic
    layout    = state.layout
    rules     = state.rules or DesignRules()

    project_name = (req.name.replace(" ", "_").lower() if req else "samvit_hw")
    revision     = f"v{state.iteration + 1}.0"
    title        = req.name if req else "Samvit Hardware"

    files: Dict[str, str] = {}

    # 1. Project file
    files[f"{project_name}.kicad_pro"] = _make_pro(project_name, revision)

    # 2. Schematic — pull from Stage 11 if already generated
    sch_result = state.stage_results.get("p11_schematic_gen")
    if sch_result and "kicad_sch" in sch_result.data:
        files[f"{project_name}.kicad_sch"] = sch_result.data["kicad_sch"]
    elif schematic is None:
        issues.append(Issue("KIC_NO_SCH", Severity.WARNING,
                            "Schematic not available — .kicad_sch will be empty.", "kicad"))
        files[f"{project_name}.kicad_sch"] = "(kicad_sch (version 20230121))\n"
    else:
        files[f"{project_name}.kicad_sch"] = "(kicad_sch (version 20230121))\n"

    # 3. PCB
    if layout is None:
        issues.append(Issue("KIC_NO_PCB", Severity.WARNING,
                            "PCB layout not available — .kicad_pcb will be skeleton.", "kicad"))
        files[f"{project_name}.kicad_pcb"] = "(kicad_pcb (version 20230121))\n"
    else:
        files[f"{project_name}.kicad_pcb"] = generate_kicad_pcb(layout, rules, title, revision)

    has_errors = any(i.is_error() for i in issues)
    return StageResult(
        stage="p26_kicad",
        status=StageStatus.PASSED if not has_errors else StageStatus.FAILED,
        data={
            "files":        files,
            "file_names":   list(files.keys()),
            "project_name": project_name,
        },
        issues=issues,
        metrics={"kicad_file_count": float(len(files))},
        duration=time.monotonic() - t0,
    )
