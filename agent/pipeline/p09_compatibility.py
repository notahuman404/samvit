"""
  Stage 9 — Compatibility Checker
  =================================
  Validates selected parts against each other using two layers:

  Layer A — hardware_builder.compatibility_checker
      Deterministic, rule-based validator with pin-level electrical checks:
      voltage domain validation, short-circuit detection, current
      oversubscription, interface mismatch, dependency completeness, and
      metadata completeness.  Requires ComponentSpec objects; we build a
      lightweight bridge from the pipeline's Component model.

  Layer B — inline budget & voltage-domain heuristics
      Simple checks that work even when Layer A cannot be imported.

  Output
  ------
    StageResult.data["is_valid"]  = bool
    StageResult.data["issues"]    = list of issue dicts
  """
  from __future__ import annotations

  import time
  from typing import Any, Dict, List, Optional, Set

  from agent.core.models import (
      Component, DesignState, Issue, PinSpec, PinType,
      Severity, StageResult, StageStatus,
  )


  # ─────────────────────────────────────────────────────────────────────────────
  # Layer A — hardware_builder.compatibility_checker bridge
  # ─────────────────────────────────────────────────────────────────────────────

  def _build_component_spec(pn: str, comp: Component):
      """Convert a pipeline Component → compatibility_checker.ComponentSpec."""
      from hardware_builder.compatibility_checker import (  # type: ignore[import]
          ComponentSpec, PinSpec as CkPinSpec, PinType as CkPinType,
          InterfaceSpec, InterfaceType,
      )

      def _ck_pin_type(pt: Any) -> "CkPinType":
          mapping = {
              "POWER_IN":    CkPinType.POWER_IN,
              "POWER_OUT":   CkPinType.POWER_OUT,
              "DIGITAL_IN":  CkPinType.DIGITAL_IN,
              "DIGITAL_OUT": CkPinType.DIGITAL_OUT,
              "DIGITAL_BIDI":CkPinType.DIGITAL_BIDI,
              "ANALOG_IN":   CkPinType.ANALOG_IN,
              "ANALOG_OUT":  CkPinType.ANALOG_OUT,
              "PASSIVE":     CkPinType.PASSIVE,
          }
          return mapping.get(str(pt).upper(), CkPinType.PASSIVE)

      pins_dict = {}
      if comp.pins:
          for pin_name, pspec in comp.pins.items():
              pins_dict[pin_name] = CkPinSpec(
                  name=pin_name,
                  type=_ck_pin_type(pspec.type),
                  voltage_min=pspec.voltage_min if hasattr(pspec, "voltage_min") else comp.voltage_min,
                  voltage_max=pspec.voltage_max if hasattr(pspec, "voltage_max") else comp.voltage_max,
                  current_max=pspec.current_max if hasattr(pspec, "current_max") else comp.current_ma / 1000.0,
                  current_draw=pspec.current_draw if hasattr(pspec, "current_draw") else comp.current_ma / 1000.0,
              )

      return ComponentSpec(
          part_number=pn,
          category=comp.category,
          description=comp.description or "",
          pins=pins_dict,
          footprint=comp.footprint or None,
          package=comp.package or None,
      )


  def _run_checker_layer_a(selected_components: Dict[str, Component]) -> List[Issue]:
      """Run hardware_builder.compatibility_checker on the selected parts."""
      try:
          import os, sys
          repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
          if repo_root not in sys.path:
              sys.path.insert(0, repo_root)

          from hardware_builder.compatibility_checker import (  # type: ignore[import]
              CompatibilityChecker, ArchitectureSpec, SelectedPart, Connection,
          )

          # Build component DB dict for the checker
          component_db = {}
          for pn, comp in selected_components.items():
              try:
                  component_db[pn] = _build_component_spec(pn, comp)
              except Exception:
                  continue

          # Build SelectedPart dict (designator → SelectedPart)
          ck_parts = {}
          for i, (pn, comp) in enumerate(selected_components.items()):
              prefix = {"MCU": "U", "SBC": "U", "SENSOR": "S", "ACTUATOR": "M",
                        "POWER": "PS", "COMMS": "RF", "AUDIO": "A",
                        "DISPLAY": "D", "MEMORY": "U", "INTERFACE": "IC",
                        "PASSIVE": "C", "PROTECTION": "D"}.get(comp.category, "X")
              des = f"{prefix}{i + 1}"
              ck_parts[des] = SelectedPart(designator=des, part_number=pn)

          arch = ArchitectureSpec(components=ck_parts, connections=[])
          checker = CompatibilityChecker(arch, component_db)
          report = checker.run()

          pipeline_issues: List[Issue] = []
          for err in report.errors:
              pipeline_issues.append(Issue(
                  code=err.get("code", "COMPAT_ERROR"),
                  severity=Severity.ERROR,
                  message=err.get("message", "Compatibility error"),
                  source="compatibility_checker",
                  objects=err.get("objects", []),
              ))
          for warn in report.warnings:
              pipeline_issues.append(Issue(
                  code=warn.get("code", "COMPAT_WARN"),
                  severity=Severity.WARNING,
                  message=warn.get("message", "Compatibility warning"),
                  source="compatibility_checker",
                  objects=warn.get("objects", []),
              ))
          return pipeline_issues

      except Exception as exc:
          # Layer A unavailable — not a fatal error, Layer B will still run
          return [Issue(
              code="COMPAT_CHECKER_SKIP",
              severity=Severity.WARNING,
              message=f"hardware_builder compatibility_checker skipped: {exc}",
              source="compatibility",
          )]


  # ─────────────────────────────────────────────────────────────────────────────
  # Layer B — inline heuristic checks (always run)
  # ─────────────────────────────────────────────────────────────────────────────

  def _check_voltage_domains(selected: Dict[str, Component]) -> List[Issue]:
      issues: List[Issue] = []
      parts = list(selected.items())
      for i, (pn_a, a) in enumerate(parts):
          for pn_b, b in parts[i + 1:]:
              if abs(a.voltage_max - b.voltage_max) > 1.5:
                  issues.append(Issue(
                      code="VOLTAGE_DOMAIN_MISMATCH",
                      severity=Severity.WARNING,
                      message=(
                          f"{pn_a} (max {a.voltage_max}V) and "
                          f"{pn_b} (max {b.voltage_max}V) operate in different voltage domains — "
                          "ensure a level-shifter or regulator bridges them."
                      ),
                      source="compatibility",
                      objects=[pn_a, pn_b],
                  ))
      return issues


  def _check_power_budget(selected: Dict[str, Component], budget_mw: float) -> List[Issue]:
      issues: List[Issue] = []
      total_mw = sum(
          c.current_ma * max(c.voltage_max, c.voltage_min) / 1000.0 * 1000.0
          for c in selected.values()
      )
      if budget_mw > 0 and total_mw > budget_mw * 1.2:
          issues.append(Issue(
              code="POWER_OVERBUDGET",
              severity=Severity.ERROR,
              message=(
                  f"Estimated draw {total_mw:.0f}mW exceeds budget "
                  f"{budget_mw:.0f}mW by {total_mw - budget_mw:.0f}mW."
              ),
              source="compatibility",
          ))
      elif budget_mw > 0 and total_mw > budget_mw:
          issues.append(Issue(
              code="POWER_NEAR_LIMIT",
              severity=Severity.WARNING,
              message=f"Estimated draw {total_mw:.0f}mW is close to budget {budget_mw:.0f}mW.",
              source="compatibility",
          ))
      return issues


  def _check_missing_categories(
      selected: Dict[str, Component],
      subsystem_categories: Set[str],
  ) -> List[Issue]:
      """Warn about common missing companion chips."""
      issues: List[Issue] = []
      cats = {c.category.upper() for c in selected.values()}
      cats.update(s.upper() for s in subsystem_categories)

      needs_charger  = any("BATTERY" in c for c in cats)
      has_charger    = any("CHARGER" in c or "CHARGE" in c for c in cats)
      needs_regulator = (
          any(c in cats for c in ("MCU", "SBC", "SENSOR")) and
          not any(c in cats for c in ("LDO", "BUCK", "BOOST", "REGULATOR", "POWER"))
      )

      if needs_charger and not has_charger:
          issues.append(Issue(
              code="MISSING_CHARGER",
              severity=Severity.WARNING,
              message="Battery selected but no charger IC found in design.",
              source="compatibility",
          ))
      if needs_regulator:
          issues.append(Issue(
              code="MISSING_REGULATOR",
              severity=Severity.WARNING,
              message="Active components detected but no power regulator (LDO/Buck-Boost) found.",
              source="compatibility",
          ))
      return issues


  # ─────────────────────────────────────────────────────────────────────────────
  # Stage entry point
  # ─────────────────────────────────────────────────────────────────────────────

  def run(state: DesignState) -> StageResult:
      t0 = time.monotonic()
      issues: List[Issue] = []

      if state.architecture is None:
          return StageResult(
              stage="p09_compatibility",
              status=StageStatus.FAILED,
              issues=[Issue("COMPAT_NO_ARCH", Severity.ERROR,
                            "Architecture not set.", "compatibility")],
              duration=time.monotonic() - t0,
          )

      # Resolve selected components from Stage 8 data
      selected_pn: Dict[str, str] = {}
      if hasattr(state, "stage_data") and state.stage_data:
          selected_pn = state.stage_data.get("p08_part_selection", {}).get("selected", {})

      selected: Dict[str, Component] = {}
      for sub_name, pn in selected_pn.items():
          if pn in state.components:
              selected[pn] = state.components[pn]

      # Fallback: use all loaded components
      if not selected:
          selected = dict(state.components)

      if not selected:
          issues.append(Issue(
              code="COMPAT_NO_PARTS",
              severity=Severity.WARNING,
              message="No selected parts to validate — skipping compatibility checks.",
              source="compatibility",
          ))
          return StageResult(
              stage="p09_compatibility",
              status=StageStatus.PASSED,
              issues=issues,
              data={"is_valid": True, "issues": []},
              duration=time.monotonic() - t0,
          )

      # ── Layer A: hardware_builder.compatibility_checker ───────────────────────
      issues.extend(_run_checker_layer_a(selected))

      # ── Layer B: inline heuristics ─────────────────────────────────────────────
      issues.extend(_check_voltage_domains(selected))

      power_budget_mw = 0.0
      if state.requirements and hasattr(state.requirements, "power_budget_mw"):
          power_budget_mw = state.requirements.power_budget_mw or 0.0
      issues.extend(_check_power_budget(selected, power_budget_mw))

      sub_cats = {sub.category for sub in state.architecture.subsystems}
      issues.extend(_check_missing_categories(selected, sub_cats))

      has_errors = any(i.is_error() for i in issues)
      return StageResult(
          stage="p09_compatibility",
          status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
          data={
              "is_valid": not has_errors,
              "issues": [{"code": i.code, "severity": i.severity.value,
                          "message": i.message} for i in issues],
          },
          issues=issues,
          duration=time.monotonic() - t0,
      )
  