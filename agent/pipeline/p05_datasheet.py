"""
Stage 5 — Datasheet Parser
===========================
Takes raw text scraped from datasheets or product pages and extracts
structured component specs using Gemini in a single batched call.

This is Gemini call point #2.  The prompt includes ALL candidate URLs
and their scraped text in ONE request so that a 10-component BOM costs
one API call, not ten.

Output
------
  Populates state.components with enriched Component records.
  StageResult.data["parsed_count"] = number of successfully parsed parts.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict
from typing import Any, Dict, List, Optional

from agent.core.models import (
    Component, DesignState, InterfaceSpec, InterfaceType,
    Issue, PinSpec, PinType, Severity, StageResult, StageStatus,
)

SYSTEM_PROMPT = """You are a precision hardware data-extraction engine.
You parse raw datasheet text and return ONLY clean structured JSON.
No explanations. No extra text. JSON only."""

PARSE_PROMPT_TEMPLATE = """
=== DATASHEET BATCH PARSE REQUEST ===

You will receive {n} component entries. Each entry has:
  - part_number
  - raw_text  (scraped from datasheet or product page)

For EACH entry, extract the following fields. If a value cannot be
determined from the text, use null.

Fields to extract per component:
  part_number   : string (preserve as given)
  manufacturer  : string
  category      : one of [MCU, SBC, POWER, SENSOR, ACTUATOR, COMMS, AUDIO,
                          DISPLAY, MEMORY, INTERFACE, PASSIVE, PROTECTION, OTHER]
  description   : one sentence max
  voltage_min   : float (V, must be a finite number, no Infinity)
  voltage_max   : float (V, must be a finite number, no Infinity)
  current_ma    : float (mA, typical operating, must be a finite number, no Infinity)
  package       : string (e.g. "QFN-32", "SOT-23")
  footprint     : string (KiCad footprint name if known, else package)
  cost_usd      : float (if mentioned)
  notes         : string (any important design notes or caveats, including battery capacity in mAh if applicable)

=== COMPONENT ENTRIES ===

{entries}

=== OUTPUT FORMAT ===

Return ONLY this JSON (no markdown, no extra text):
{{
  "components": [
    {{
      "part_number": "...",
      "manufacturer": "...",
      "category": "...",
      "description": "...",
      "voltage_min": 0.0,
      "voltage_max": 5.0,
      "current_ma": 100.0,
      "package": "...",
      "footprint": "...",
      "cost_usd": null,
      "notes": "..."
    }}
  ]
}}
"""


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start == -1:
        raise ValueError("No JSON found in datasheet parser response.")
    return json.loads(text[start:end])


def _build_component(d: Dict[str, Any], source_url: str = "", confidence: float = 0.8) -> Component:
    """Convert a parsed dict into a Component model."""

    def _f(key: str, default: float = 0.0) -> float:
        v = d.get(key)
        try:
            return float(v) if v is not None else default
        except (TypeError, ValueError):
            return default

    # Build minimal pin set based on category
    pins: Dict[str, PinSpec] = {}
    category = d.get("category", "OTHER")
    v_min = _f("voltage_min", 0.0)
    v_max = _f("voltage_max", 5.0)
    i_ma  = _f("current_ma", 10.0)

    if category in ("MCU", "SBC"):
        pins = {
            "VDD": PinSpec("VDD", PinType.POWER_IN,  v_min, v_max, 0, i_ma),
            "GND": PinSpec("GND", PinType.POWER_IN,  0.0,   0.0,  0, 0),
            "IO0": PinSpec("IO0", PinType.DIGITAL_BIDI, 0, v_max, 0.02, 0),
        }
    elif category == "POWER":
        pins = {
            "VIN":  PinSpec("VIN",  PinType.POWER_IN,  v_min, v_max * 1.5, 0, i_ma),
            "VOUT": PinSpec("VOUT", PinType.POWER_OUT, v_min, v_max,       2.0, 0),
            "GND":  PinSpec("GND",  PinType.POWER_IN,  0, 0, 0, 0),
        }
    elif category in ("SENSOR", "ACTUATOR", "AUDIO", "DISPLAY", "COMMS"):
        pins = {
            "VDD": PinSpec("VDD", PinType.POWER_IN,  v_min, v_max, 0, i_ma),
            "GND": PinSpec("GND", PinType.POWER_IN,  0, 0, 0, 0),
            "SDA": PinSpec("SDA", PinType.DIGITAL_BIDI, 0, v_max, 0.02, 0),
            "SCL": PinSpec("SCL", PinType.DIGITAL_IN,   0, v_max, 0,    0),
        }
    else:
        pins = {
            "P1": PinSpec("P1", PinType.PASSIVE, v_min, v_max, 0, i_ma),
            "P2": PinSpec("P2", PinType.PASSIVE, v_min, v_max, 0, 0),
        }

    return Component(
        part_number=d.get("part_number", "UNKNOWN"),
        manufacturer=d.get("manufacturer", "Unknown"),
        category=category,
        description=d.get("description", ""),
        voltage_min=v_min,
        voltage_max=v_max,
        current_ma=_f("current_ma"),
        package=d.get("package") or "",
        footprint=d.get("footprint") or d.get("package") or "",
        cost_usd=_f("cost_usd"),
        source_url=source_url,
        pins=pins,
        notes=d.get("notes") or "",
        confidence=confidence,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

async def run_async(
    state: DesignState,
    gemini_manager: Any,
    raw_entries: Optional[List[Dict[str, str]]] = None,
) -> StageResult:
    """
    Parameters
    ----------
    state:          Current DesignState.
    gemini_manager: GeminiModelManager instance.
    raw_entries:    List of {"part_number": str, "raw_text": str, "source_url": str}.
                    If None, tries to use candidates already in state.components.
    """
    t0 = time.monotonic()
    issues: List[Issue] = []

    # Build entries from state if not provided
    if not raw_entries:
        raw_entries = []
        for pn, comp in state.components.items():
            if comp.description:
                raw_entries.append({
                    "part_number": pn,
                    "raw_text": f"{comp.manufacturer} {comp.category} {comp.description} {comp.notes}",
                    "source_url": comp.source_url or "",
                })

    if not raw_entries:
        return StageResult(
            stage="p05_datasheet",
            status=StageStatus.SKIPPED,
            data={"parsed_count": 0},
            issues=[Issue("DS_NO_INPUT", Severity.INFO,
                          "No datasheet entries to parse.", "datasheet")],
            duration=time.monotonic() - t0,
        )

    # Build batched prompt
    entry_text = ""
    for i, e in enumerate(raw_entries, 1):
        entry_text += (
            f"\n--- Entry {i} ---\n"
            f"part_number: {e['part_number']}\n"
            f"raw_text:\n{e.get('raw_text', '')[:1500]}\n"
        )

    prompt = PARSE_PROMPT_TEMPLATE.format(
        n=len(raw_entries),
        entries=entry_text,
    )

    parsed_components: Dict[str, Component] = {}

    try:
        raw_response = await gemini_manager.call_gemini(
            prompt=prompt,
            task="medium",
            system_instruction=SYSTEM_PROMPT,
            temperature=0.1,
        )
        result = _extract_json(raw_response)

        for item in result.get("components", []):
            pn = item.get("part_number", "UNKNOWN")
            source = next(
                (e.get("source_url", "") for e in raw_entries if e["part_number"] == pn), ""
            )
            comp = _build_component(item, source_url=source, confidence=0.85)
            parsed_components[pn] = comp

    except Exception as exc:
        issues.append(Issue(
            code="DS_PARSE_ERROR",
            severity=Severity.WARNING,
            message=f"Datasheet parse failed: {exc}. Keeping existing component data.",
            source="datasheet",
        ))
        # Fall back: mark components as confidence=0.5 if not already parsed
        for e in raw_entries:
            pn = e["part_number"]
            if pn not in state.components:
                parsed_components[pn] = Component(
                    part_number=pn,
                    manufacturer="Unknown",
                    category="OTHER",
                    description=e.get("raw_text", "")[:100],
                    confidence=0.3,
                )

    # Merge into state — only update if we got higher-confidence data
    for pn, new_comp in parsed_components.items():
        existing = state.components.get(pn)
        if existing is None or new_comp.confidence > existing.confidence:
            state.components[pn] = new_comp

    has_errors = any(i.is_error() for i in issues)
    return StageResult(
        stage="p05_datasheet",
        status=StageStatus.FAILED if has_errors else StageStatus.PASSED,
        data={"parsed_count": len(parsed_components)},
        issues=issues,
        metrics={"parsed_count": float(len(parsed_components))},
        duration=time.monotonic() - t0,
    )


def run(state: DesignState, gemini_manager: Any, raw_entries: Optional[List[Dict[str, str]]] = None) -> StageResult:
    return asyncio.run(run_async(state, gemini_manager, raw_entries))
