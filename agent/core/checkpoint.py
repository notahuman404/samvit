"""
Checkpoint system — saves full pipeline state snapshots as the agent
progresses so work is never lost and any iteration can be inspected.

Layout on disk:
    checkpoint/
        checkpoint_001/
            state.json
            schematic.kicad_sch  (if available)
            layout.kicad_pcb     (if available)
            bom.csv              (if available)
            manifest.json
        checkpoint_002/
            ...
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.core.models import DesignState


class CheckpointManager:
    """
    Saves and loads pipeline state checkpoints.

    Usage:
        cp = CheckpointManager("checkpoint")
        cp.save(state, label="after_erc")
        state = cp.load_latest()
    """

    def __init__(self, base_dir: str = "checkpoint") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._counter = self._next_counter()

    # ── Internal ────────────────────────────────────────────────────────────

    def _next_counter(self) -> int:
        existing = sorted(self.base_dir.glob("checkpoint_*"))
        if not existing:
            return 1
        last = existing[-1].name  # e.g. "checkpoint_007"
        try:
            return int(last.split("_")[-1]) + 1
        except ValueError:
            return len(existing) + 1

    def _cp_path(self, n: int) -> Path:
        return self.base_dir / f"checkpoint_{n:03d}"

    # ── Public API ───────────────────────────────────────────────────────────

    def save(
        self,
        state: "DesignState",
        label: str = "",
        extra_files: Optional[Dict[str, str]] = None,
    ) -> Path:
        """
        Persist state to a new numbered checkpoint directory.

        Parameters
        ----------
        state:       The current DesignState.
        label:       Human-readable tag written to manifest.json.
        extra_files: Optional dict of {filename: content_string} for
                     KiCad files, BOMs, etc.

        Returns
        -------
        Path to the checkpoint directory.
        """
        cp_dir = self._cp_path(self._counter)
        cp_dir.mkdir(parents=True, exist_ok=True)

        # Core state JSON
        (cp_dir / "state.json").write_text(state.to_json(), encoding="utf-8")

        # Extra artefact files (KiCad, BOM, Gerbers, …). Some artefacts live in
        # sub-directories (e.g. "gerbers/samvit.GTL"), so ensure the parent dir
        # exists before writing.
        if extra_files:
            for filename, content in extra_files.items():
                out_path = cp_dir / filename
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content, encoding="utf-8")

        # Manifest
        manifest: Dict[str, Any] = {
            "checkpoint": self._counter,
            "label":      label,
            "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "iteration":  state.iteration,
            "stages_completed": list(state.stage_results.keys()),
            "files":      [p.name for p in cp_dir.iterdir()],
        }
        if state.metrics:
            manifest["metrics_snapshot"] = {
                "erc_errors":  state.metrics.erc_errors,
                "drc_errors":  state.metrics.drc_errors,
                "pass_rate":   state.metrics.pass_rate,
                "cost_usd":    state.metrics.bom_cost_usd,
            }
        (cp_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        self._counter += 1
        return cp_dir

    def load_latest(self) -> Optional[Dict[str, Any]]:
        """Return the state dict from the most recent checkpoint, or None."""
        checkpoints = sorted(self.base_dir.glob("checkpoint_*"))
        if not checkpoints:
            return None
        state_file = checkpoints[-1] / "state.json"
        if not state_file.exists():
            return None
        return json.loads(state_file.read_text(encoding="utf-8"))

    def load(self, n: int) -> Optional[Dict[str, Any]]:
        """Load a specific checkpoint by number."""
        state_file = self._cp_path(n) / "state.json"
        if not state_file.exists():
            return None
        return json.loads(state_file.read_text(encoding="utf-8"))

    @staticmethod
    def resolve(path: str) -> Dict[str, Any]:
        """
        Resolve a user-supplied resume path to a concrete checkpoint.

        Accepts any of:
          * a checkpoint directory          → checkpoint/checkpoint_016
          * a base checkpoint directory     → checkpoint   (uses the latest)
          * a direct state.json file        → checkpoint/checkpoint_016/state.json

        Returns a dict: {"state": <dict>, "manifest": <dict|None>,
                          "base_dir": <str>, "checkpoint_dir": <str>}.
        Raises FileNotFoundError if no usable state.json can be found.
        """
        p = Path(path)

        # Direct state.json file.
        if p.is_file() and p.name == "state.json":
            cp_dir = p.parent
        elif p.is_dir() and (p / "state.json").exists():
            cp_dir = p                                  # a checkpoint_XXX dir
        elif p.is_dir():
            cps = sorted(p.glob("checkpoint_*"))         # a base dir → latest
            cps = [c for c in cps if (c / "state.json").exists()]
            if not cps:
                raise FileNotFoundError(f"No checkpoint with state.json under '{path}'.")
            cp_dir = cps[-1]
        else:
            raise FileNotFoundError(f"Resume path not found: '{path}'.")

        state = json.loads((cp_dir / "state.json").read_text(encoding="utf-8"))
        manifest = None
        mf = cp_dir / "manifest.json"
        if mf.exists():
            manifest = json.loads(mf.read_text(encoding="utf-8"))

        # New checkpoints should continue numbering in the SAME base dir
        # (parent of checkpoint_XXX), so the resumed run appends rather than
        # starting a fresh tree.
        base_dir = cp_dir.parent if cp_dir.name.startswith("checkpoint_") else cp_dir
        return {
            "state":          state,
            "manifest":       manifest,
            "base_dir":       base_dir.as_posix(),
            "checkpoint_dir": cp_dir.as_posix(),
        }

    def list_checkpoints(self) -> list[Dict[str, Any]]:
        """Return all checkpoint manifests sorted by number."""
        manifests = []
        for cp_dir in sorted(self.base_dir.glob("checkpoint_*")):
            mf = cp_dir / "manifest.json"
            if mf.exists():
                manifests.append(json.loads(mf.read_text(encoding="utf-8")))
        return manifests

    def purge_old(self, keep: int = 10) -> None:
        """Remove oldest checkpoints keeping only the most recent `keep`."""
        all_cps = sorted(self.base_dir.glob("checkpoint_*"))
        to_remove = all_cps[: max(0, len(all_cps) - keep)]
        for cp in to_remove:
            shutil.rmtree(cp, ignore_errors=True)
