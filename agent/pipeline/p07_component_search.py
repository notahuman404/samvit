"""
  Stage 7 — Component Search / Retrieval
  ========================================
  Searches for components that match each subsystem in state.architecture.

  Primary:  hardware_builder.component_retrival  (keyword + category DB search)
  Fallback: in-memory scoring on state.components already loaded by Stage 6

  No Gemini call — fully deterministic.

  Output
  ------
    StageResult.data["candidates"] = {subsystem_name: [{part_number, score}, ...]}
  """
  from __future__ import annotations

  import re
  import time
  from typing import Any, Dict, List, Optional, Tuple

  from agent.core.models import (
      Component, DesignState, Issue, Severity,
      StageResult, StageStatus, Subsystem,
  )

  CATEGORY_KEYWORDS: Dict[str, List[str]] = {
      "MCU":        ["MCU", "Microcontroller"],
      "SBC":        ["SBC"],
      "POWER":      ["Charger IC", "Buck-Boost", "Boost Converter", "LDO", "Battery", "POWER"],
      "SENSOR":     ["Depth Sensor", "ToF Sensor", "LiDAR", "Barometer", "IMU", "Camera", "Microphone"],
      "ACTUATOR":   ["Actuator", "Haptic Driver", "PWM Driver", "MOTOR"],
      "COMMS":      ["BT Module", "BLE SoC", "LoRa", "LTE Module", "COMMS"],
      "AUDIO":      ["Audio Amp", "Mic Amp", "Microphone", "AUDIO"],
      "DISPLAY":    ["Display", "LED", "DISPLAY"],
      "MEMORY":     ["Flash", "Storage", "MEMORY"],
      "INTERFACE":  ["Level Shifter", "IO Expander", "Buffer", "PWM Driver", "INTERFACE"],
      "PASSIVE":    ["Capacitor", "Resistor", "Diode", "MOSFET", "Connector", "PASSIVE"],
      "PROTECTION": ["Diode", "MOSFET", "PROTECTION"],
  }


  # ─────────────────────────────────────────────────────────────────────────────
  # hardware_builder.component_retrival bridge
  # ─────────────────────────────────────────────────────────────────────────────

  def _search_via_retrival(sub: Subsystem, top_n: int = 5) -> List[Tuple[str, float]]:
      """
      Use hardware_builder.component_retrival to search the DB directly with
      keyword + category scoring.  Returns (part_number, score) pairs.
      Falls back to empty list if the module is unavailable.
      """
      try:
          import os, sys
          # Ensure hardware_builder is importable from the repo root
          repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
          if repo_root not in sys.path:
              sys.path.insert(0, repo_root)

          from hardware_builder.component_retrival import (  # type: ignore[import]
              load_db, CATEGORY_ALIASES, DB_PATH,
          )
          parts = load_db(DB_PATH)
      except Exception:
          return []

      # Build keyword list from subsystem
      keywords = [sub.name.lower(), sub.category.lower(), sub.interface.lower()]
      if sub.interface:
          keywords.append(sub.interface.lower())

      # Expand keywords via CATEGORY_ALIASES
      db_categories: set = set()
      for kw in keywords:
          for alias_key, cats in CATEGORY_ALIASES.items():
              if alias_key in kw or kw in alias_key:
                  db_categories.update(cats)
      # Direct category match
      direct_cats = CATEGORY_KEYWORDS.get(sub.category, [sub.category])
      db_categories.update(direct_cats)

      results: List[Tuple[str, float]] = []
      for part in parts:
          score = 0.0

          # Category match
          for cat in db_categories:
              if cat.lower() == part.category.lower():
                  score += 10.0
                  break
              if cat.lower() in part.category.lower():
                  score += 5.0
                  break

          if score == 0.0:
              continue

          # Voltage check (hard filter)
          try:
              v_str = part.voltage_v.replace("V", "").strip()
              # Handle ranges like "3.3-5V" or "1.8-5.5V"
              if "-" in v_str:
                  parts_v = v_str.split("-")
                  v_min, v_max = float(parts_v[0]), float(parts_v[1])
              elif "/" in v_str:
                  vals = [float(p) for p in v_str.split("/")]
                  v_min, v_max = min(vals), max(vals)
              else:
                  v_min = v_max = float(v_str) if v_str else 0.0
          except (ValueError, IndexError):
              v_min, v_max = 0.0, 99.0

          if sub.voltage_min > 0 and v_max < sub.voltage_min:
              continue
          if sub.voltage_max > 0 and v_min > sub.voltage_max:
              continue
          score += 5.0

          # Cost bonus
          if part.cost_usd > 0:
              score -= part.cost_usd * 0.1

          results.append((part.name, max(score, 0.0)))

      results.sort(key=lambda x: x[1], reverse=True)
      return results[:top_n]


  # ─────────────────────────────────────────────────────────────────────────────
  # In-memory fallback scorer (uses state.components already loaded)
  # ─────────────────────────────────────────────────────────────────────────────

  def _score_component(comp: Component, sub: Subsystem) -> float:
      score = 0.0
      db_cats = CATEGORY_KEYWORDS.get(sub.category, [sub.category])
      for cat in db_cats:
          if cat.lower() == comp.category.lower():
              score += 10.0
          elif cat.lower() in comp.category.lower() or comp.category.lower() in cat.lower():
              score += 5.0
      if sub.voltage_min > 0 and comp.voltage_max < sub.voltage_min:
          return -1.0
      if sub.voltage_max > 0 and comp.voltage_min > sub.voltage_max:
          return -1.0
      if comp.voltage_min <= sub.voltage_min and comp.voltage_max >= sub.voltage_max:
          score += 5.0
      if sub.current_ma > 0 and comp.current_ma > 0:
          ratio = comp.current_ma / sub.current_ma
          score += min(5.0, ratio) if ratio >= 1.0 else -5.0
      if sub.interface.upper() in (comp.notes + " " + comp.description).upper():
          score += 3.0
      score += comp.confidence * 2.0
      if comp.cost_usd > 0:
          score -= comp.cost_usd * 0.1
      return max(score, 0.0)


  def _search_in_memory(
      sub: Subsystem,
      components: Dict[str, Component],
      top_n: int = 5,
  ) -> List[Tuple[str, float]]:
      scored = [
          (pn, _score_component(comp, sub))
          for pn, comp in components.items()
      ]
      scored = [(pn, s) for pn, s in scored if s > 0]
      scored.sort(key=lambda x: x[1], reverse=True)
      return scored[:top_n]


  # ─────────────────────────────────────────────────────────────────────────────
  # Stage entry point
  # ─────────────────────────────────────────────────────────────────────────────

  def run(state: DesignState) -> StageResult:
      t0 = time.monotonic()
      issues: List[Issue] = []

      if state.architecture is None:
          return StageResult(
              stage="p07_component_search",
              status=StageStatus.FAILED,
              issues=[Issue("SEARCH_NO_ARCH", Severity.ERROR,
                            "Architecture not set before component search.", "search")],
              duration=time.monotonic() - t0,
          )

      candidates: Dict[str, List[Dict[str, Any]]] = {}
      unfilled: List[str] = []

      for sub in state.architecture.subsystems:
          # Try hardware_builder retrival first (direct DB keyword search)
          results = _search_via_retrival(sub)

          # Fall back to in-memory scoring if retrival found nothing
          if not results and state.components:
              results = _search_in_memory(sub, state.components)

          if not results:
              unfilled.append(sub.name)
              issues.append(Issue(
                  code="SEARCH_NO_MATCH",
                  severity=Severity.WARNING if sub.priority == 2 else Severity.ERROR,
                  message=f"No components found for subsystem '{sub.name}' ({sub.category}).",
                  source="component_search",
                  objects=[sub.name],
              ))
          else:
              candidates[sub.name] = [
                  {"part_number": pn, "score": round(s, 2)} for pn, s in results
              ]

      # Merge retrival results into state.components (register any newly found parts)
      for sub_name, cands in candidates.items():
          for c in cands:
              if c["part_number"] not in state.components:
                  # Part was found via DB retrival but not yet in state — load it now
                  try:
                      from hardware_builder.component_retrival import load_db, DB_PATH  # type: ignore[import]
                      db_parts = load_db(DB_PATH)
                      for p in db_parts:
                          if p.name == c["part_number"] and p.name not in state.components:
                              from agent.core.models import Component
                              try:
                                  v_min = float(p.voltage_v.split("-")[0].replace("V", "").strip())
                                  v_max = float(p.voltage_v.split("-")[-1].replace("V", "").strip())
                              except Exception:
                                  v_min = v_max = 0.0
                              state.components[p.name] = Component(
                                  part_number=p.name,
                                  category=p.category,
                                  description=p.description,
                                  voltage_min=v_min,
                                  voltage_max=v_max,
                                  current_ma=float(p.current_ma) if p.current_ma.replace(".", "").isdigit() else 0.0,
                                  package=p.package,
                                  footprint=p.footprint,
                                  cost_usd=p.cost_usd,
                                  notes=p.notes,
                                  confidence=0.9,
                              )
                  except Exception:
                      pass

      has_errors = any(i.is_error() for i in issues)
      return StageResult(
          stage="p07_component_search",
          status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
          data={"candidates": candidates, "unfilled_subsystems": unfilled},
          issues=issues,
          duration=time.monotonic() - t0,
      )
  