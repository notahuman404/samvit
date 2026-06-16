"""
Stage 28 — Logging and Versioning
=====================================
Appends a structured log entry to the design run journal.
Each entry captures: timestamp, iteration, all stage statuses,
key metrics, and issues. Provides a queryable audit trail.

Output
------
  Appends to run_journal.jsonl (one JSON record per line).
  StageResult.data["journal_entry"] = the entry just written.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

from samvit.core.models import (
    DesignState, StageResult, StageStatus,
)

DEFAULT_JOURNAL = "samvit_run_journal.jsonl"


def build_entry(state: DesignState) -> Dict[str, Any]:
    """Build a single structured journal entry."""
    entry: Dict[str, Any] = {
        "timestamp":  time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "iteration":  state.iteration,
        "project":    state.requirements.name if state.requirements else "unknown",
        "stage_statuses": {
            name: result.status.value
            for name, result in state.stage_results.items()
        },
    }

    if state.metrics:
        from dataclasses import asdict
        entry["metrics"] = asdict(state.metrics)

    if state.review:
        entry["review"] = {
            "passed":        state.review.passed,
            "summary":       state.review.summary[:200],
            "repair_count":  len(state.review.repairs),
        }

    # Count issues by severity across all stages
    error_count   = 0
    warning_count = 0
    for result in state.stage_results.values():
        for issue in result.issues:
            if issue.is_error():
                error_count += 1
            else:
                warning_count += 1

    entry["total_errors"]   = error_count
    entry["total_warnings"] = warning_count
    entry["is_complete"]    = all(
        r.status in (StageStatus.PASSED, StageStatus.REPAIRED, StageStatus.SKIPPED)
        for r in state.stage_results.values()
    )
    return entry


def run(state: DesignState, journal_path: str = DEFAULT_JOURNAL) -> StageResult:
    t0 = time.monotonic()

    entry = build_entry(state)

    # Append to journal
    try:
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        pass   # Non-fatal if journal can't be written (e.g. read-only FS)

    return StageResult(
        stage="p28_logging",
        status=StageStatus.PASSED,
        data={"journal_entry": entry, "journal_path": journal_path},
        duration=time.monotonic() - t0,
    )
