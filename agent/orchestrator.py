"""
Samvit Orchestrator
====================

Implements the full autonomous hardware design loop:

MAIN LOOP
─────────
  Global Plan (Gemini #1)
      ↓
  [Segment A]  Build → Local Validate
  [Segment B]  Build → Local Validate
  [Segment C]  Build → Local Validate
      ↓
  System Integration
      ↓
  ERC → DRC → Simulation → Power Analysis → Thermal Analysis
      ↓
  Critique + Root Cause + Impact + Repair Plan  (Gemini #3, one call)
      ↓
  Apply Repair (deterministic, smallest scope)
      ↓
  Local Validate → Full Validate
      ↓
  repeat until clean or max iterations reached

FIX LOOP (triggered on any stage failure)
──────────────────────────────────────────
  Failure
      ↓ Failure Classification
      ↓ Root Cause Analysis
      ↓ Impact Analysis
      ↓ Repair Plan
      ↓ Apply Repair
      ↓ Local Validation
      ↓ Full Validation (sim + ERC/DRC/power/thermal)
      ↓ repeat or advance if fixed

Gemini call budget: 4 total
  #1 — Architecture planning (Stage 3)
  #2 — Datasheet batch parse  (Stage 5)
  #3 — Critique+RCA+Impact+Repair plan (Stage 24, one combined call)
  #4 — (reserved for future deep repair reasoning)
"""

from __future__ import annotations

import asyncio
import copy
import logging
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from agent.core.checkpoint import CheckpointManager
from agent.core.gemini_manager import GeminiModelManager
from agent.core.models import (
    DesignRules, DesignState, HardwareRequirements, StageStatus,
)

# ── Pipeline imports ─────────────────────────────────────────────────────────
from agent.pipeline import (
    p01_requirements,
    p03_architecture,
    p05_datasheet,
    p06_component_db,
    p07_component_search,
    p08_part_selection,
    p09_compatibility,
    p10_schematic_graph,
    p10b_hwdl_validate,
    p11_schematic_gen,
    p12_footprint,
    p13_placement,
    p14_routing,
    p15_rules,
    p16_erc,
    p17_drc,
    p18_power,
    p19_thermal,
    p20_short_circuit,
    p21_simulation,
    p22_test_gen,
    p23_metrics,
    p24_reviewer,
    p25_repair,
    p26_kicad,
    p27_exporter,
    p28_logging,
    p29_visualizer,
    p30_human_override,
)

log = logging.getLogger("agent.orchestrator")


# ──────────────────────────────────────────────────────────────────────────────
# Segment definition
# A "segment" is a logical grouping of subsystems that can be built
# and locally validated independently before full system integration.
# ──────────────────────────────────────────────────────────────────────────────

SEGMENT_CATEGORIES = {
    "POWER_SEGMENT":   ["POWER", "PROTECTION", "Battery"],
    "COMPUTE_SEGMENT": ["MCU", "SBC", "MEMORY"],
    "IO_SEGMENT":      ["SENSOR", "ACTUATOR", "COMMS", "AUDIO", "DISPLAY", "INTERFACE"],
    "PASSIVE_SEGMENT": ["PASSIVE"],
}


def _categorise_into_segments(
    architecture: Any,
) -> Dict[str, List[Any]]:
    """
    Group subsystems into segments for parallel build+validate.
    Returns {segment_name: [subsystem, ...]}
    """
    segments: Dict[str, List[Any]] = {k: [] for k in SEGMENT_CATEGORIES}
    for sub in architecture.subsystems:
        placed = False
        for seg_name, cats in SEGMENT_CATEGORIES.items():
            if sub.category in cats or any(c.lower() in sub.category.lower() for c in cats):
                segments[seg_name].append(sub)
                placed = True
                break
        if not placed:
            segments["IO_SEGMENT"].append(sub)
    # Drop empty segments
    return {k: v for k, v in segments.items() if v}


# ──────────────────────────────────────────────────────────────────────────────
# Stage runner helpers
# ──────────────────────────────────────────────────────────────────────────────

def _run(label: str, fn, *args, **kwargs) -> Any:
    """Run a synchronous stage, log result, return StageResult."""
    log.info("  ▶ Running %s …", label)
    t0 = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        log.info(
            "  %s %s — %.2fs  (E:%d W:%d)",
            "✅" if result.ok() else "❌",
            label, time.monotonic() - t0,
            len(result.errors()), len(result.issues) - len(result.errors()),
        )
        return result
    except Exception as exc:
        log.exception("  💥 %s crashed: %s", label, exc)
        from agent.core.models import Issue, Severity, StageResult
        return StageResult(
            stage=label,
            status=StageStatus.FAILED,
            issues=[Issue(f"{label.upper()}_CRASH", Severity.ERROR, str(exc), label)],
            duration=time.monotonic() - t0,
        )


async def _run_async(label: str, coro) -> Any:
    """Run an async stage and return its StageResult."""
    log.info("  ▶ Running %s …", label)
    t0 = time.monotonic()
    try:
        result = await coro
        log.info(
            "  %s %s — %.2fs  (E:%d W:%d)",
            "✅" if result.ok() else "❌",
            label, time.monotonic() - t0,
            len(result.errors()), len(result.issues) - len(result.errors()),
        )
        return result
    except Exception as exc:
        log.exception("  💥 %s crashed: %s", label, exc)
        from agent.core.models import Issue, Severity, StageResult
        return StageResult(
            stage=label,
            status=StageStatus.FAILED,
            issues=[Issue(f"{label.upper()}_CRASH", Severity.ERROR, str(exc), label)],
            duration=time.monotonic() - t0,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Segment build + local validate
# ──────────────────────────────────────────────────────────────────────────────

def _local_validate_segment(
    state: DesignState,
    segment_name: str,
    subsystems: List[Any],
) -> bool:
    """
    Local validation for a segment:
      - check voltage compatibility within segment
      - check that all subsystems have a candidate part
      Returns True if the segment passes local checks.
    """
    sel = state.stage_results.get("p08_part_selection")
    if sel is None:
        return False

    selected = sel.data.get("selected", {})
    sub_names = [s.name for s in subsystems]
    missing = [name for name in sub_names if name not in selected]

    if missing:
        log.warning("    [%s] local validate FAIL — missing parts for: %s", segment_name, missing)
        return False

    # Voltage range check within segment
    seg_comps = [
        state.components[selected[name]]
        for name in sub_names
        if name in selected and selected[name] in state.components
    ]
    if seg_comps:
        v_max = max(c.voltage_max for c in seg_comps)
        v_min = min(c.voltage_min for c in seg_comps)
        if v_max - v_min > 3.5:
            log.warning(
                "    [%s] local validate WARN — voltage spread %.1f–%.1fV > 3.5V",
                segment_name, v_min, v_max,
            )

    log.info("    [%s] local validate PASS ✅", segment_name)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Fix loop  (Failure → Classify → RCA → Impact → Plan → Apply → Validate)
# ──────────────────────────────────────────────────────────────────────────────

def _design_score(m: Optional[Any]) -> float:
    """
    Scalar quality score for a design — LOWER is better. Used to detect whether
    an iteration actually improved the hardware and to keep the best design.
    """
    if m is None:
        return float("inf")
    score = m.erc_errors * 1000.0 + m.drc_errors * 100.0
    score += (1.0 - m.sim_pass_rate) * 200.0
    score += max(0.0, m.max_temp_c - 85.0) * 2.0
    if math.isfinite(m.estimated_battery_h):
        score += max(0.0, 8.0 - m.estimated_battery_h)
    # Power validation (p18) is a real convergence signal, not a free pass.
    # Fixed penalty when over budget, plus a small per-mW gradient so the
    # improvement guard can see the repair loop trimming power toward budget.
    if not getattr(m, "power_ok", True):
        score += 150.0
        score += getattr(m, "power_over_budget_mw", 0.0) * 0.01
    return score


async def _fix_loop(
    state: DesignState,
    gemini: GeminiModelManager,
    checkpoint: CheckpointManager,
    max_fix_rounds: int = 5,
    orchestrator: Any = None,
) -> bool:
    """
    Run the repair cycle until the design is clean or max_fix_rounds exhausted.

    Returns True if the design passes all checks after fixing.
    """
    prev_score = _design_score(state.metrics)
    stagnant_rounds = 0
    for fix_round in range(1, max_fix_rounds + 1):
        log.info("━" * 60)
        log.info("  FIX ROUND %d / %d", fix_round, max_fix_rounds)
        log.info("━" * 60)

        # ── Step 1: Critique + RCA + Impact + Repair Plan (1 Gemini call) ──────
        log.info("  📋  STEP 1 — Critique / Root Cause / Impact / Repair Plan")
        r24 = await _run_async("p24_reviewer",
                               p24_reviewer.run_async(state, gemini))
        state.record(r24)

        if r24.data.get("review", {}).get("passed", False):
            log.info("  ✅  Reviewer says design PASSED — exiting fix loop.")
            return True

        repair_count = r24.data.get("repair_count", 0)
        if repair_count == 0:
            log.warning("  ⚠️  Reviewer found failures but produced no repairs. Stopping fix loop.")
            return False

        # ── Step 2: Apply Repair (deterministic, smallest scope) ─────────────
        log.info("  🔧  STEP 2 — Apply Repair (%d instruction(s))", repair_count)
        r25 = _run("p25_repair", p25_repair.run, state)
        state.record(r25)

        stages_to_rerun: List[str] = r25.data.get("stages_to_rerun", [])
        applied_count              = len(r25.data.get("applied_repairs", []))

        if applied_count == 0:
            log.error("  ❌  No repairs applied. Manual intervention required.")
            return False

        log.info("  Applied %d repair(s). Re-running: %s", applied_count, stages_to_rerun)

        # ── Step 3: Local Validation (fast, stage-specific) ───────────────────
        log.info("  🔍  STEP 3 — Local Validation")
        if orchestrator is not None:
            await orchestrator._run_locally_affected(state, stages_to_rerun)

        # ── Step 4: Full Validation (ERC → DRC → Sim → Power → Thermal) ──────
        log.info("  🧪  STEP 4 — Full Validation")
        _full_validate(state)

        # ── Save checkpoint after each fix round ──────────────────────────────
        _save_checkpoint(state, checkpoint, label=f"fix_round_{fix_round}")

        # Check if design is now clean (incl. thermal within safe limit and
        # power within budget — a design over its power budget is NOT clean).
        m = state.metrics
        if (m and m.erc_errors == 0 and m.drc_errors == 0
                and m.sim_pass_rate >= 0.75 and m.max_temp_c < 105.0
                and getattr(m, "power_ok", True)):
            log.info("  ✅  Design passed all checks after fix round %d!", fix_round)
            return True

        # ── Improvement tracking: detect when repairs stop moving the metrics ──
        cur_score = _design_score(m)
        log.info("  📊  Design score: %.1f → %.1f (lower is better)", prev_score, cur_score)
        if cur_score < prev_score - 1e-6:
            stagnant_rounds = 0
        else:
            stagnant_rounds += 1
            if stagnant_rounds >= 2:
                log.warning(
                    "  ⚠️  No measurable improvement over %d rounds — "
                    "repairs cannot move the remaining metrics. Stopping fix loop.",
                    stagnant_rounds,
                )
                return False
        prev_score = min(prev_score, cur_score)

    log.warning("  ⚠️  Max fix rounds (%d) reached without full resolution.", max_fix_rounds)
    return False





def _full_validate(state: DesignState) -> None:
    """Run all five full-system validators."""
    for label, fn in [
        ("p16_erc",          lambda: p16_erc.run(state)),
        ("p17_drc",          lambda: p17_drc.run(state)),
        ("p18_power",        lambda: p18_power.run(state)),
        ("p19_thermal",      lambda: p19_thermal.run(state)),
        ("p20_short_circuit",lambda: p20_short_circuit.run(state)),
        ("p21_simulation",   lambda: p21_simulation.run(state)),
        ("p23_metrics",      lambda: p23_metrics.run(state)),
    ]:
        result = _run(label, fn)
        state.record(result)


def _save_checkpoint(
    state: DesignState,
    checkpoint: CheckpointManager,
    label: str = "",
) -> None:
    kic = state.stage_results.get("p26_kicad")
    exp = state.stage_results.get("p27_exporter")
    extra: Dict[str, str] = {}
    if kic:
        extra.update(kic.data.get("files", {}))
    if exp:
        extra.update(exp.data.get("artefacts", {}))
    cp_dir = checkpoint.save(state, label=label, extra_files=extra)
    log.info("  💾  Checkpoint saved → %s", cp_dir)


# ──────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ──────────────────────────────────────────────────────────────────────────────

class SamvitOrchestrator:
    """
    Full autonomous hardware design pipeline orchestrator.

    Usage:
        orch = SamvitOrchestrator(
            api_keys=["KEY_A", "KEY_B"],
            checkpoint_dir="checkpoint",
        )
        asyncio.run(orch.run("Build a wearable haptic device for visually impaired people."))
    """

    def __init__(
        self,
        api_keys: List[str],
        checkpoint_dir: str = "checkpoint",
        db_path: Optional[str] = None,
        max_main_iterations: int = 8,
        max_fix_rounds: int = 5,
    ) -> None:
        self.gemini    = GeminiModelManager(api_keys=api_keys, default_tier="heavy")
        self.checkpoint = CheckpointManager(checkpoint_dir)
        self.db_path   = db_path
        self.max_main_iterations = max_main_iterations
        self.max_fix_rounds      = max_fix_rounds

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s  %(message)s",
            datefmt="%H:%M:%S",
        )

    # ──────────────────────────────────────────────────────────────────────

    async def _run_locally_affected(self, state: DesignState, stages_to_rerun: List[str]) -> None:
        """Re-run only the stages that were dirtied by the repair."""
        async_stages = {"p05_datasheet"}
        stage_fns = {
            "p05_datasheet":        lambda: _run_async("p05_datasheet", p05_datasheet.run_async(state, self.gemini)),
            "p08_part_selection":   lambda: _run("p08_part_selection", p08_part_selection.run, state),
            "p09_compatibility":    lambda: _run("p09_compatibility", p09_compatibility.run, state),
            "p10_schematic_graph":  lambda: _run("p10_schematic_graph", p10_schematic_graph.run, state),
            "p11_schematic_gen":    lambda: _run("p11_schematic_gen", p11_schematic_gen.run, state),
            "p12_footprint":        lambda: _run("p12_footprint", p12_footprint.run, state),
            "p13_placement":        lambda: _run("p13_placement", p13_placement.run, state),
            "p14_routing":          lambda: _run("p14_routing", p14_routing.run, state),
            "p17_drc":              lambda: _run("p17_drc", p17_drc.run, state),
            "p18_power":            lambda: _run("p18_power", p18_power.run, state),
            "p20_short_circuit":    lambda: _run("p20_short_circuit", p20_short_circuit.run, state),
        }
        ordered = [
            "p05_datasheet", "p08_part_selection", "p09_compatibility",
            "p10_schematic_graph", "p11_schematic_gen",
            "p12_footprint", "p13_placement", "p14_routing",
            "p17_drc", "p18_power", "p20_short_circuit",
        ]
        for stage in ordered:
            if stage in stages_to_rerun and stage in stage_fns:
                fn_result = stage_fns[stage]()
                result = await fn_result if stage in async_stages else fn_result
                state.record(result)

    # ──────────────────────────────────────────────────────────────────────

    async def run(
        self,
        requirements_input: Any,
        human_overrides: Optional[Dict[str, Any]] = None,
        resume_from: Optional[str] = None,
    ) -> DesignState:
        """
        Entry point. `requirements_input` can be a string (free text) or dict.

        If `resume_from` is given (a checkpoint dir, a base checkpoint dir, or a
        state.json file) the expensive setup phases (requirements, architecture,
        component DB, datasheet parsing, per-segment build) are SKIPPED: the
        design state is rebuilt from the checkpoint and the pipeline continues
        from system integration → validation → the critique/repair loop.

        Returns the final DesignState after all iterations.
        """
        t_start = time.monotonic()

        log.info("╔══════════════════════════════════════════════════════════╗")
        log.info("║          SAMVIT AUTONOMOUS HARDWARE PIPELINE             ║")
        log.info("╚══════════════════════════════════════════════════════════╝")

        if resume_from is not None:
            # ── Resume: rebuild state from a checkpoint and continue ──────────
            info = CheckpointManager.resolve(resume_from)
            state = DesignState.from_dict(info["state"])
            state.checkpoint_dir = self.checkpoint.base_dir.as_posix()
            log.info("\n♻️  RESUMING FROM CHECKPOINT — %s", info["checkpoint_dir"])
            log.info("    iteration=%d  components=%d  stages_done=%d",
                     state.iteration, len(state.components), len(state.stage_results))
            m = state.metrics
            if m:
                log.info("    metrics: ERC=%d DRC=%d Sim=%.0f%% Temp=%.1f°C Battery=%.1fh",
                         m.erc_errors, m.drc_errors, m.sim_pass_rate * 100,
                         m.max_temp_c, m.estimated_battery_h)
            if state.requirements is None or not state.components:
                log.error(
                    "Checkpoint is missing requirements/components — cannot resume. "
                    "Run a fresh build instead. Aborting.")
                return state
            log.info("  ⏩  Skipping setup phases (0–3); continuing from integration.")
        else:
            state = DesignState(checkpoint_dir=self.checkpoint.base_dir.as_posix())

            # ── Phase 0: Requirements ─────────────────────────────────────────
            log.info("\n📌  PHASE 0 — REQUIREMENTS")
            r01 = _run("p01_requirements", p01_requirements.run, state, requirements_input)
            state.record(r01)
            if not r01.ok():
                log.error("Requirements failed — aborting. Errors: %s", r01.errors())
                return state

            # ── Phase 1: Global Plan (Architecture) — Gemini call #1 ─────────
            log.info("\n🧠  PHASE 1 — GLOBAL ARCHITECTURE PLAN  (Gemini call #1)")
            r03 = await _run_async("p03_architecture",
                                   p03_architecture.run_async(state, self.gemini))
            state.record(r03)
            if not r03.ok():
                log.error("Architecture planning failed. Errors: %s", r03.errors())
                return state

            arch = state.architecture
            log.info("  Planned %d subsystems:", len(arch.subsystems))
            for sub in arch.subsystems:
                log.info("    [%s] %s — %s  %.1fV  %.0fmA",
                         sub.category, sub.name, sub.role, sub.voltage_max, sub.current_ma)

            # ── Phase 2: Component database + datasheet parsing (Gemini #2) ──
            log.info("\n🗄️  PHASE 2 — COMPONENT DATABASE + DATASHEET PARSING")
            r06 = _run("p06_component_db", p06_component_db.run, state,
                       *([self.db_path] if self.db_path else []))
            state.record(r06)

            # Datasheet batch parse — Gemini call #2
            log.info("  Datasheet parser (Gemini call #2) …")
            r05 = await _run_async("p05_datasheet",
                                   p05_datasheet.run_async(state, self.gemini))
            state.record(r05)

            log.info("  Component DB: %d parts loaded, %d parsed from datasheets",
                     r06.data.get("loaded_count", 0), r05.data.get("parsed_count", 0))

            # ── Phase 3: Per-segment Build + Local Validate ───────────────────
            log.info("\n🔧  PHASE 3 — PER-SEGMENT BUILD + LOCAL VALIDATE")

            # Component search + selection (needed before segmentation)
            r07 = _run("p07_component_search", p07_component_search.run, state)
            state.record(r07)
            r08 = _run("p08_part_selection", p08_part_selection.run, state)
            state.record(r08)

            segments = _categorise_into_segments(arch)
            log.info("  Segments: %s", list(segments.keys()))

            for seg_name, subsystems in segments.items():
                log.info("\n  ── Segment: %s (%d subsystems) ──", seg_name, len(subsystems))
                for sub in subsystems:
                    log.info("       %s (%s)", sub.name, sub.category)

                # Build: footprint + compatibility for this segment's parts
                r09 = _run("p09_compatibility", p09_compatibility.run, state)
                state.record(r09)
                r12 = _run("p12_footprint", p12_footprint.run, state)
                state.record(r12)

                # Local validate
                passed = _local_validate_segment(state, seg_name, subsystems)
                if not passed:
                    log.warning("  [%s] local validation failed — will fix in repair loop", seg_name)

            # Checkpoint after segment phase
            _save_checkpoint(state, self.checkpoint, label="after_segments")

        # ── Phase 4: System Integration ───────────────────────────────────────
        log.info("\n🔗  PHASE 4 — SYSTEM INTEGRATION")
        r15 = _run("p15_rules", p15_rules.run, state)
        state.record(r15)
        r10 = _run("p10_schematic_graph", p10_schematic_graph.run, state)
        state.record(r10)
        r11 = _run("p11_schematic_gen", p11_schematic_gen.run, state)
        state.record(r11)
        r13 = _run("p13_placement", p13_placement.run, state)
        state.record(r13)
        r14 = _run("p14_routing", p14_routing.run, state)
        state.record(r14)

        # Human overrides (applied before validation)
        r30 = _run("p30_human_override", p30_human_override.run, state, human_overrides)
        state.record(r30)

        _save_checkpoint(state, self.checkpoint, label="after_integration")

        # ── Phase 5: Full Validation ──────────────────────────────────────────
        log.info("\n🧪  PHASE 5 — FULL VALIDATION")
        log.info("  Running: ERC → DRC → Simulation → Power → Thermal")
        r22 = _run("p22_test_gen", p22_test_gen.run, state)
        state.record(r22)
        _full_validate(state)

        # ── Phase 6: Main iteration loop (Critique → Repair → Validate) ──────
        log.info("\n🔁  PHASE 6 — CRITIQUE → REPAIR → VALIDATE LOOP")
        design_clean = False
        best_score = _design_score(state.metrics)
        best_state: Optional[DesignState] = copy.deepcopy(state)
        stagnant_iters = 0

        for main_iter in range(1, self.max_main_iterations + 1):
            state.iteration = main_iter
            log.info("\n━" * 30)
            log.info("  MAIN ITERATION %d / %d", main_iter, self.max_main_iterations)
            log.info("━" * 30)

            m = state.metrics
            if m:
                log.info("  Status: ERC=%d DRC=%d Sim=%.0f%% Temp=%.1f°C Battery=%.1fh",
                         m.erc_errors, m.drc_errors, m.sim_pass_rate * 100,
                         m.max_temp_c, m.estimated_battery_h)

            # Enter fix loop
            design_clean = await _fix_loop(
                state, self.gemini, self.checkpoint, self.max_fix_rounds, self
            )

            if design_clean:
                log.info("  ✅  Design is CLEAN after iteration %d!", main_iter)
                best_state = copy.deepcopy(state)
                best_score = _design_score(state.metrics)
                break

            log.info("  ↩️  Design still has issues — re-running full validation …")
            r22 = _run("p22_test_gen", p22_test_gen.run, state)
            state.record(r22)
            _full_validate(state)

            # ── Track the best design and stop early if it plateaus ──────────
            cur_score = _design_score(state.metrics)
            if cur_score < best_score - 1e-6:
                best_score = cur_score
                best_state = copy.deepcopy(state)
                stagnant_iters = 0
            else:
                stagnant_iters += 1
                if stagnant_iters >= 2:
                    log.warning(
                        "  ⚠️  No improvement over %d iterations (best score %.1f) — "
                        "stopping early instead of exhausting iterations.",
                        stagnant_iters, best_score,
                    )
                    break

        # Restore the best design seen, so exported artefacts reflect it.
        if (not design_clean and best_state is not None
                and _design_score(state.metrics) > best_score + 1e-6):
            log.info("  ↺  Restoring best-known design (score %.1f).", best_score)
            state.components    = best_state.components
            state.schematic     = best_state.schematic
            state.layout        = best_state.layout
            state.rules         = best_state.rules
            state.metrics       = best_state.metrics
            state.stage_results = best_state.stage_results

        # ── Phase 7: Export artefacts ─────────────────────────────────────────
        log.info("\n📦  PHASE 7 — EXPORT ARTEFACTS")
        r26 = _run("p26_kicad", p26_kicad.run, state)
        state.record(r26)
        r27 = _run("p27_exporter", p27_exporter.run, state)
        state.record(r27)

        # ── Phase 8: Final checkpoint + log ──────────────────────────────────
        log.info("\n💾  PHASE 8 — FINAL CHECKPOINT + LOG")
        r28 = _run("p28_logging", p28_logging.run, state)
        state.record(r28)
        r29 = _run("p29_visualizer", p29_visualizer.run, state)
        state.record(r29)
        _save_checkpoint(state, self.checkpoint, label="final")

        # ── Summary ───────────────────────────────────────────────────────────
        elapsed = time.monotonic() - t_start
        log.info("\n" + "=" * 60)
        log.info("  PIPELINE COMPLETE  —  %.1fs  —  %d iteration(s)", elapsed, state.iteration)
        log.info("=" * 60)
        if r29.data.get("report"):
            for line in r29.data["report"].splitlines():
                log.info("%s", line)

        return state
