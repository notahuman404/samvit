"""
  Stage 8 — Part Selection Engine
  ==================================
  Selects the single best part for each subsystem from Stage 7 candidates.

  Primary:  hardware_builder.part_selection_engine.PartSelectionEngine
            (runs offline DB query + voltage/current/cost scoring)
  Fallback: simple pick-first-by-score from candidates list

  No Gemini call — fully deterministic.

  Output
  ------
    StageResult.data["selected"] = {subsystem_name: part_number}
  """
  from __future__ import annotations

  import asyncio
  import time
  from typing import Any, Dict, List, Optional

  from agent.core.models import (
      Component, DesignState, Issue, Severity,
      StageResult, StageStatus,
  )


  # ─────────────────────────────────────────────────────────────────────────────
  # PartSelectionEngine bridge
  # ─────────────────────────────────────────────────────────────────────────────

  def _select_via_engine(
      category: str,
      voltage_min: float,
      voltage_max: float,
      current_ma: float,
      budget_usd: Optional[float],
  ) -> Optional[str]:
      """
      Ask PartSelectionEngine to search the offline DB for the best match.
      Returns part_number string or None.
      """
      try:
          import os, sys
          repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
          if repo_root not in sys.path:
              sys.path.insert(0, repo_root)

          from hardware_builder.part_selection_engine import (  # type: ignore[import]
              PartSelectionEngine, ComponentRequirements,
          )

          db_path = os.path.join(repo_root, "hardware_builder", "samvit_parts.db")
          engine = PartSelectionEngine(db_path)

          reqs = ComponentRequirements(
              category=category,
              voltage_min=voltage_min if voltage_min > 0 else None,
              voltage_max=voltage_max if voltage_max > 0 else None,
              current_min_ma=current_ma if current_ma > 0 else None,
              max_cost_usd=budget_usd,
          )

          # select_best_part is async; run it in a temporary event loop
          best = asyncio.run(engine.select_best_part(reqs))
          return best.part_number if best else None

      except Exception:
          return None


  # ─────────────────────────────────────────────────────────────────────────────
  # Fallback: pick best from Stage 7 candidate list (already scored)
  # ─────────────────────────────────────────────────────────────────────────────

  def _pick_from_candidates(
      candidates: List[Dict[str, Any]],
      components: Dict[str, Component],
      budget_usd: Optional[float],
  ) -> Optional[str]:
      for c in candidates:
          pn = c["part_number"]
          comp = components.get(pn)
          if comp is None:
              continue
          if budget_usd is not None and comp.cost_usd > budget_usd:
              continue
          return pn
      return None


  # ─────────────────────────────────────────────────────────────────────────────
  # Stage entry point
  # ─────────────────────────────────────────────────────────────────────────────

  def run(state: DesignState) -> StageResult:
      t0 = time.monotonic()
      issues: List[Issue] = []

      if state.architecture is None:
          return StageResult(
              stage="p08_part_selection",
              status=StageStatus.FAILED,
              issues=[Issue("SELECT_NO_ARCH", Severity.ERROR,
                            "Architecture not set.", "part_selection")],
              duration=time.monotonic() - t0,
          )

      candidates_data: Dict[str, List[Dict[str, Any]]] = (
          state.stage_data.get("p07_component_search", {}).get("candidates", {})
          if hasattr(state, "stage_data") and state.stage_data
          else {}
      )

      budget_usd: Optional[float] = getattr(state.requirements, "budget_usd", None) if state.requirements else None
      selected: Dict[str, str] = {}

      for sub in state.architecture.subsystems:
          # 1. Try PartSelectionEngine (offline DB scoring)
          pn = _select_via_engine(
              category=sub.category,
              voltage_min=sub.voltage_min,
              voltage_max=sub.voltage_max,
              current_ma=sub.current_ma,
              budget_usd=budget_usd,
          )

          # 2. Fall back to picking best from Stage 7 candidates
          if pn is None:
              cands = candidates_data.get(sub.name, [])
              pn = _pick_from_candidates(cands, state.components, budget_usd)

          if pn is None:
              issues.append(Issue(
                  code="SELECT_NO_PART",
                  severity=Severity.WARNING if sub.priority == 2 else Severity.ERROR,
                  message=f"Could not select a part for subsystem '{sub.name}' ({sub.category}).",
                  source="part_selection",
                  objects=[sub.name],
              ))
          else:
              selected[sub.name] = pn

      # Persist selection into state for downstream stages
      if not hasattr(state, "stage_data") or state.stage_data is None:
          state.stage_data = {}
      state.stage_data.setdefault("p08_part_selection", {})["selected"] = selected

      has_errors = any(i.is_error() for i in issues)
      return StageResult(
          stage="p08_part_selection",
          status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
          data={"selected": selected},
          issues=issues,
          duration=time.monotonic() - t0,
      )
  