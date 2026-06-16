"""
  Stage 10b — HWDL Validation
  =============================
  Serialises the current DesignState into Hardware Description Language (HWDL)
  source text, then compiles it through hardware_parser.

    • Compiler ERRORS   → pipeline ERRORS
    • Compiler WARNINGS → pipeline WARNINGS
    • Import failure    → SKIPPED (never blocks pipeline)

  No Gemini call — fully deterministic.

  Output
  ------
    data["hwdl_source"]   — generated HWDL text
    data["ir"]            — compiler IR dict (or None on parse error)
    data["diagnostics"]   — list of {code, severity, message, line, col}
  """
  from __future__ import annotations

  import time
  from typing import Any, Dict, List

  from agent.core.models import (
      Component, DesignState, Issue, Severity,
      StageResult, StageStatus,
  )


  # ─────────────────────────────────────────────────────────────────────────────
  # HWDL serialiser
  # ─────────────────────────────────────────────────────────────────────────────

  def _pin_direction(pin_type_str: str) -> str:
      return {
          "POWER_IN":    "power_in",
          "POWER_OUT":   "power_out",
          "GND":         "power_gnd",
          "DIGITAL_IN":  "input",
          "DIGITAL_OUT": "output",
          "DIGITAL_BIDI":"bidir",
          "BIDIR":       "bidir",
          "PASSIVE":     "passive",
          "ANALOG_IN":   "input",
          "ANALOG_OUT":  "output",
          "NO_CONNECT":  "no_connect",
          "OPEN_DRAIN":  "open_drain",
      }.get(str(pin_type_str).upper(), "passive")


  def _ident(name: str) -> str:
      """Sanitise a string to a valid HWDL identifier."""
      safe = ""
      for ch in str(name):
          safe += ch if (ch.isalnum() or ch == "_") else "_"
      if safe and safe[0].isdigit():
          safe = "p_" + safe
      return safe or "unnamed"


  def _serialise(state: DesignState) -> str:
      lines: List[str] = []
      project = _ident(state.requirements.name if state.requirements else "design")

      lines.append(f"hwdl 1.0;  // project: {project}")
      lines.append("")

      # ── Part declarations ──────────────────────────────────────────────────────
      emitted_parts: set = set()
      part_map: Dict[str, Component] = {}

      if state.schematic and state.schematic.components:
          for sc in state.schematic.components:
              pn = sc.part_number or sc.designator or ""
              if pn and pn in state.components and pn not in emitted_parts:
                  part_map[pn] = state.components[pn]
                  emitted_parts.add(pn)
      if not part_map and state.components:
          part_map = dict(state.components)

      for pn, comp in part_map.items():
          pid = _ident(pn)
          lines.append(f'part "{pid}" {{')
          lines.append(f'    category = "{comp.category}";')
          if comp.voltage_max > 0:
              lines.append(f'    voltage = "{comp.voltage_min:.1f}-{comp.voltage_max:.1f}V";')
          if comp.cost_usd > 0:
              lines.append(f'    cost = {comp.cost_usd:.2f};')
          if comp.description:
              esc = comp.description.replace('"', "'")[:120]
              lines.append(f'    description = "{esc}";')
          if comp.pins:
              lines.append("    pins {")
              for pin_name, pin_spec in comp.pins.items():
                  direction = _pin_direction(str(pin_spec.type))
                  lines.append(f"        {_ident(pin_name)} {direction};")
              lines.append("    }")
          lines.append("}")
          lines.append("")

      # ── Power domain declarations ──────────────────────────────────────────────
      emitted_domains: set = set()
      if state.schematic and state.schematic.nets:
          for net in state.schematic.nets:
              n = net.name.upper()
              if net.kind in ("power", "supply") or "VCC" in n or "VDD" in n or "GND" in n:
                  did = _ident(net.name)
                  if did not in emitted_domains:
                      emitted_domains.add(did)
                      lines.append(f"power {did} {{")
                      lines.append(f'    kind = "{net.kind}";')
                      lines.append("}")
                      lines.append("")

      # ── Module ────────────────────────────────────────────────────────────────
      if state.schematic and state.schematic.components:
          lines.append(f'module "{project}" {{')

          for sc in state.schematic.components:
              ref = sc.reference or sc.designator or sc.part_number or "U"
              pn  = sc.part_number or ref
              lines.append(f'    {_ident(ref)} = "{_ident(pn)}";')

          lines.append("")

          # Signal nets
          if state.schematic.nets:
              for net in state.schematic.nets:
                  n = net.name.upper()
                  if net.kind not in ("power", "supply") and "VCC" not in n and "GND" not in n:
                      lines.append(f"    net {_ident(net.name)};")

          lines.append("")

          # Connections
          if state.schematic.nets:
              for net in state.schematic.nets:
                  if not net.nodes or len(net.nodes) < 2:
                      continue
                  src = net.nodes[0]
                  nid = _ident(net.name)
                  n   = net.name.upper()
                  is_power = net.kind in ("power", "supply") or "VCC" in n or "GND" in n
                  for dst in net.nodes[1:]:
                      lhs = f"{_ident(src.reference)}.{_ident(src.pin)}"
                      if is_power:
                          lines.append(f"    connect {lhs} -> power.{nid};")
                      else:
                          rhs = f"{_ident(dst.reference)}.{_ident(dst.pin)}"
                          lines.append(f"    connect {lhs} -> {rhs};")

          lines.append("")
          lines.append("    constraint {")
          if state.requirements:
              if getattr(state.requirements, "budget_usd", None):
                  lines.append(f"        max_cost = {state.requirements.budget_usd:.2f};")
              if getattr(state.requirements, "voltage_v", None):
                  lines.append(f'        voltage = "{state.requirements.voltage_v}V";')
          lines.append("    }")
          lines.append("}")

      return "\n".join(lines)


  # ─────────────────────────────────────────────────────────────────────────────
  # Stage entry point
  # ─────────────────────────────────────────────────────────────────────────────

  def run(state: DesignState) -> StageResult:
      t0 = time.monotonic()
      issues: List[Issue] = []
      data: Dict[str, Any] = {}

      try:
          from hardware_parser import compile_hwdl  # type: ignore[import]
      except ImportError as exc:
          issues.append(Issue(
              code="HWDL_IMPORT_SKIP",
              severity=Severity.WARNING,
              message=f"hardware_parser not importable — HWDL validation skipped. ({exc})",
              source="hwdl_validate",
          ))
          return StageResult(
              stage="p10b_hwdl_validate",
              status=StageStatus.SKIPPED,
              issues=issues,
              data={"hwdl_source": None, "ir": None, "diagnostics": []},
              duration=time.monotonic() - t0,
          )

      hwdl_source = _serialise(state)
      data["hwdl_source"] = hwdl_source

      try:
          ir, diags = compile_hwdl(hwdl_source, source_path="<pipeline-generated>")
      except Exception as exc:
          issues.append(Issue(
              code="HWDL_COMPILE_CRASH",
              severity=Severity.ERROR,
              message=f"HWDL compiler crashed: {exc}",
              source="hwdl_validate",
          ))
          return StageResult(
              stage="p10b_hwdl_validate",
              status=StageStatus.FAILED,
              issues=issues,
              data=data,
              duration=time.monotonic() - t0,
          )

      data["ir"] = ir
      diag_dicts = []
      for d in diags.items:
          sev = Severity.ERROR if d.severity.value == "error" else Severity.WARNING
          issues.append(Issue(
              code=d.code,
              severity=sev,
              message=f"[HWDL {d.loc.line}:{d.loc.col}] {d.message}",
              source="hwdl_validate",
          ))
          diag_dicts.append({
              "code": d.code,
              "severity": d.severity.value,
              "line": d.loc.line,
              "col": d.loc.col,
              "message": d.message,
          })
      data["diagnostics"] = diag_dicts

      has_errors = any(i.is_error() for i in issues)
      return StageResult(
          stage="p10b_hwdl_validate",
          status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
          issues=issues,
          data=data,
          duration=time.monotonic() - t0,
      )
  