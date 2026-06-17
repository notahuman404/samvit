"""
Part Selection Engine
======================
Selects the best electronic component for a subsystem requirement.

Search order
------------
  1. Offline DB (samvit_parts.db) — exact, deterministic, scored against
     hard constraints (voltage / current / cost).
  2. Real web search — if (and only if) the offline DB has no usable
     match, this calls Gemini with the built-in Google Search grounding
     tool ("google_search") and asks it to find one real, currently
     existing component, citing a real source URL it actually retrieved.

There is no mocked/hardcoded online provider. If a real, verifiable match
cannot be found — offline or online — `select_best_part` returns `None`.
It never fabricates a part number. A caller receiving `None` should treat
the subsystem as genuinely unfilled (e.g. surface a SELECT_NO_PART issue,
relax requirements, widen the offline DB, or add a manually-specified
ghost component) rather than silently proceeding with a phantom part.

New dependency
---------------
  pip install google-genai

Auth
----
  Reuses whatever Gemini API keys are already configured for the rest of
  the pipeline: the env var `GEMINI_API_KEY`, plus `GEMINI_API_KEY_1`,
  `GEMINI_API_KEY_2`, ... (same convention as main.py's resolve_api_keys).
  No new credentials are required. If no key is present, online search is
  skipped (with a logged warning) and only the offline DB is used.
"""

import sqlite3
import dataclasses
import json
import logging
import os
import re
import time
import asyncio
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# --- Core request/response models -------------------------------------------

@dataclasses.dataclass
class ComponentRequirements:
    category: str
    voltage_min: Optional[float] = None
    voltage_max: Optional[float] = None
    current_min_ma: Optional[float] = None
    max_cost_usd: Optional[float] = None
    preferred_package: Optional[str] = None

@dataclasses.dataclass
class ComponentCandidate:
    part_number: str
    manufacturer: str
    category: str
    source: str  # "offline_db" or "web_search"
    voltage_raw: str
    current_raw: str
    package: Optional[str] = None
    cost_usd: float = 0.0
    confidence_score: float = 0.0
    notes: str = ""
    source_url: Optional[str] = None
    datasheet_url: Optional[str] = None

# --- Web-search interchange models -------------------------------------------

@dataclasses.dataclass
class WebSearchConnectorInput:
    category: str
    requirements: Dict[str, Any] = dataclasses.field(default_factory=dict)
    keywords: List[str] = dataclasses.field(default_factory=list)
    constraints: Dict[str, Any] = dataclasses.field(default_factory=dict)

@dataclasses.dataclass
class CandidateComponent:
    part_number: str
    manufacturer: str
    source_url: str
    datasheet_url: Optional[str] = None
    package: Optional[str] = None
    category: Optional[str] = None
    confidence: float = 0.0
    retrieval_method: str = ""
    voltage_min: Optional[float] = None
    voltage_max: Optional[float] = None
    current_ma: Optional[float] = None
    cost_usd_estimate: Optional[float] = None

@dataclasses.dataclass
class WebSearchConnectorOutput:
    query: str
    candidates: List[CandidateComponent] = dataclasses.field(default_factory=list)
    search_metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)


# --- Parsing helpers for the offline DB --------------------------------------

def parse_voltage_range(v_str: str) -> tuple[float, float]:
    """Extracts (min_v, max_v) from strings like '3.3-5V', '5V/3.3V', or '3.7V nominal'."""
    if not v_str or v_str == "—":
        return 0.0, float('inf')

    clean = v_str.upper().replace("V", "").replace("NOMINAL", "").strip()

    if "-" in clean:
        try:
            parts = clean.split("-")
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass
    if "/" in clean:
        try:
            parts = [float(p) for p in clean.split("/")]
            return min(parts), max(parts)
        except ValueError:
            pass

    try:
        val = float(clean)
        return val, val
    except ValueError:
        return 0.0, float('inf')


def parse_current_ma(c_str: str) -> float:
    """Extracts numeric mA value from text like '3000mAh', '0.6', or '1000'."""
    if not c_str or c_str == "—":
        return 0.0
    clean = c_str.lower().replace("mah", "").replace("ma", "").strip()
    try:
        return float(clean)
    except ValueError:
        return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Real web search provider — Gemini + Google Search grounding
#
# No hardcoded/mocked results. Every CandidateComponent returned must have
# come from a grounded search result with a real http(s) source URL the
# model actually cited; otherwise this returns no candidates at all.
# ──────────────────────────────────────────────────────────────────────────────

class GeminiSearchProvider:
    # Tried in order; current (Gemini 2.0+) models use the "google_search"
    # tool name. (Older 1.x models used "google_search_retrieval" instead,
    # which is NOT compatible with these — mixing them causes a 400 error.)
    _MODELS = ["gemini-2.5-flash"]

    _SYSTEM_INSTRUCTION = (
        "You are a precise hardware component-sourcing assistant. You only "
        "report parts you can verify through your search tool. You never "
        "invent part numbers, manufacturers, or specs. If you cannot verify "
        "a real match, you say so instead of guessing."
    )

    def __init__(self, api_keys: Optional[List[str]] = None):
        self.api_keys: List[str] = api_keys if api_keys is not None else self._resolve_api_keys()
        self._key_cursor = 0
        self._cache: Dict[str, WebSearchConnectorOutput] = {}

    @staticmethod
    def _resolve_api_keys() -> List[str]:
        """Same convention as main.py:resolve_api_keys() — GEMINI_API_KEY,
        then GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... No new env vars needed."""
        keys: List[str] = []
        base = os.environ.get("GEMINI_API_KEY")
        if base:
            keys.append(base)
        i = 1
        while True:
            k = os.environ.get(f"GEMINI_API_KEY_{i}")
            if not k:
                break
            keys.append(k)
            i += 1
        return keys

    def _next_key(self) -> Optional[str]:
        if not self.api_keys:
            return None
        key = self.api_keys[self._key_cursor % len(self.api_keys)]
        self._key_cursor += 1
        return key

    async def search(self, query: WebSearchConnectorInput) -> WebSearchConnectorOutput:
        cache_key = json.dumps({"cat": query.category, "req": query.requirements}, sort_keys=True)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        if not self.api_keys:
            logger.warning(
                "[GeminiSearchProvider] No GEMINI_API_KEY(_n) env var found — "
                "skipping web search for '%s'.", query.category,
            )
            return WebSearchConnectorOutput(query=query.category, candidates=[])

        try:
            import google.genai  # noqa: F401  (import check only)
        except ImportError:
            logger.error(
                "[GeminiSearchProvider] google-genai is not installed. "
                "Run: pip install google-genai"
            )
            return WebSearchConnectorOutput(query=query.category, candidates=[])

        prompt = self._build_prompt(query)
        raw_text: Optional[str] = None
        last_exc: Optional[Exception] = None
        max_attempts = max(3, len(self.api_keys) * len(self._MODELS))

        for attempt in range(max_attempts):
            api_key = self._next_key()
            if api_key is None:
                break
            model = self._MODELS[attempt % len(self._MODELS)]
            try:
                raw_text = await asyncio.to_thread(self._call_once, api_key, model, prompt)
                break
            except Exception as exc:  # noqa: BLE001 — we deliberately want to retry on anything transient
                last_exc = exc
                msg = str(exc).lower()
                if "429" in msg or "quota" in msg or "resource_exhausted" in msg:
                    logger.warning(
                        "[GeminiSearchProvider] Rate limited on attempt %d/%d "
                        "(model=%s) — rotating key/model.",
                        attempt + 1, max_attempts, model,
                    )
                    await asyncio.sleep(min(2.0 * (attempt + 1), 10.0))
                    continue
                logger.warning(
                    "[GeminiSearchProvider] Call failed on attempt %d/%d "
                    "(model=%s): %s", attempt + 1, max_attempts, model, exc,
                )
                await asyncio.sleep(0.5)
                continue

        if raw_text is None:
            logger.warning(
                "[GeminiSearchProvider] Web search failed for '%s' after %d "
                "attempt(s). Last error: %s", query.category, max_attempts, last_exc,
            )
            return WebSearchConnectorOutput(query=query.category, candidates=[])

        candidate = self._parse_response(raw_text, query)
        result = WebSearchConnectorOutput(
            query=query.category,
            candidates=[candidate] if candidate else [],
            search_metadata={"raw_response_chars": len(raw_text)},
        )
        self._cache[cache_key] = result
        return result

    def _build_prompt(self, query: WebSearchConnectorInput) -> str:
        reqs = query.requirements or {}
        constraints = []
        v_min, v_max = reqs.get("voltage_min"), reqs.get("voltage_max")
        if v_min is not None or v_max is not None:
            constraints.append(
                f"must operate within roughly {v_min if v_min is not None else 'any'}V "
                f"to {v_max if v_max is not None else 'any'}V"
            )
        if reqs.get("current_min") is not None:
            constraints.append(f"must supply/handle at least {reqs.get('current_min')}mA")
        if reqs.get("max_cost_usd") is not None:
            constraints.append(f"unit cost should be at or under ${reqs.get('max_cost_usd')} USD")
        constraints_txt = "; ".join(constraints) if constraints else "no further hard numeric constraints"

        return (
            f"Search the web right now to find ONE real, currently available electronic "
            f"component in this category: \"{query.category}\".\n"
            f"Requirement: {constraints_txt}.\n\n"
            "Rules:\n"
            "- Only report a part you can confirm exists via an actual search result this turn "
            "(a manufacturer page, a distributor listing such as Digi-Key/Mouser/LCSC, or a "
            "datasheet you found).\n"
            "- Do not guess, infer from memory, or invent a plausible-sounding part number.\n"
            "- If you cannot find a real, verifiable match, return found=false rather than your "
            "best guess.\n\n"
            "Respond with ONLY one JSON object — no markdown code fences, no prose before or "
            "after it — in exactly this shape:\n"
            "{\n"
            '  "found": true,\n'
            '  "part_number": "...",\n'
            '  "manufacturer": "...",\n'
            '  "package": "...",\n'
            '  "voltage_min": 0.0,\n'
            '  "voltage_max": 0.0,\n'
            '  "current_ma": 0.0,\n'
            '  "cost_usd_estimate": 0.0,\n'
            '  "source_url": "https://... (the real URL of the search result you used)",\n'
            '  "datasheet_url": "https://... or null",\n'
            '  "confidence": 0.0\n'
            "}\n"
            'If nothing real is found, respond with exactly: {"found": false}'
        )

    def _call_once(self, api_key: str, model: str, prompt: str) -> str:
        """Single synchronous Gemini call with Google Search grounding enabled.
        Runs inside asyncio.to_thread() since the google-genai client is sync."""
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=self._SYSTEM_INSTRUCTION,
                temperature=0.1,
                max_output_tokens=1024,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise RuntimeError("Empty response from Gemini.")
        return text

    @staticmethod
    def _extract_json(text: str) -> Optional[Dict[str, Any]]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(json)?", "", cleaned, flags=re.IGNORECASE).strip()
            cleaned = re.sub(r"```$", "", cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        return None

    def _parse_response(self, raw_text: str, query: WebSearchConnectorInput) -> Optional[CandidateComponent]:
        data = self._extract_json(raw_text)
        if not data:
            logger.warning(
                "[GeminiSearchProvider] Could not parse a JSON object out of the "
                "response for '%s'. Treating as no match.", query.category,
            )
            return None

        if not data.get("found"):
            return None

        part_number = str(data.get("part_number") or "").strip()
        source_url = str(data.get("source_url") or "").strip()

        # Hard guardrail against hallucination: no real part number or no
        # http(s) source URL the model claims to have actually retrieved
        # means this is rejected outright, not accepted with a caveat.
        if not part_number or not source_url.lower().startswith(("http://", "https://")):
            logger.warning(
                "[GeminiSearchProvider] Rejecting result for '%s': missing part "
                "number or a real source URL (got part_number=%r, source_url=%r).",
                query.category, part_number, source_url,
            )
            return None

        def _num(key: str) -> Optional[float]:
            try:
                v = data.get(key)
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        confidence = _num("confidence")
        confidence = max(0.0, min(confidence, 1.0)) if confidence is not None else 0.5

        return CandidateComponent(
            part_number=part_number,
            manufacturer=str(data.get("manufacturer") or "Unknown"),
            source_url=source_url,
            datasheet_url=(str(data["datasheet_url"]) if data.get("datasheet_url") else None),
            package=(str(data["package"]) if data.get("package") else None),
            category=query.category,
            confidence=confidence,
            retrieval_method="gemini_google_search_grounding",
            voltage_min=_num("voltage_min"),
            voltage_max=_num("voltage_max"),
            current_ma=_num("current_ma"),
            cost_usd_estimate=_num("cost_usd_estimate"),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Core selection engine
# ──────────────────────────────────────────────────────────────────────────────

class PartSelectionEngine:
    def __init__(self, db_path: str, api_keys: Optional[List[str]] = None):
        self.db_path = db_path
        self.online_provider = GeminiSearchProvider(api_keys=api_keys)

    def _query_offline_db(self, category: str) -> List[ComponentCandidate]:
        """Queries the SQLite database for matches based on category strings."""
        candidates = []
        try:
            conn = sqlite3.connect(self.db_path)
            c = conn.cursor()
            c.execute(
                "SELECT name, category, description, voltage_v, current_ma, "
                "package, cost_usd, notes FROM parts WHERE category LIKE ?",
                (f"%{category}%",),
            )
            rows = c.fetchall()

            for row in rows:
                candidates.append(ComponentCandidate(
                    part_number=row[0],
                    manufacturer="Unknown/Generic",
                    category=row[1],
                    source="offline_db",
                    voltage_raw=row[3],
                    current_raw=row[4],
                    package=row[5],
                    cost_usd=float(row[6]),
                    notes=row[7],
                ))
            conn.close()
        except sqlite3.OperationalError as e:
            logger.warning("Offline DB warning: %s. Ensure the database is built and located at %s", e, self.db_path)
        return candidates

    def _score_candidate(self, candidate: ComponentCandidate, reqs: ComponentRequirements) -> float:
        """Calculates compatibility score. Returns -1.0 if any hard constraint is violated."""
        score = 100.0

        cand_min_v, cand_max_v = parse_voltage_range(candidate.voltage_raw)
        if reqs.voltage_min is not None and cand_max_v < reqs.voltage_min:
            return -1.0
        if reqs.voltage_max is not None and cand_min_v > reqs.voltage_max:
            return -1.0

        cand_ma = parse_current_ma(candidate.current_raw)
        if reqs.current_min_ma is not None and cand_ma < reqs.current_min_ma and cand_ma > 0:
            return -1.0

        if reqs.max_cost_usd is not None and candidate.cost_usd > reqs.max_cost_usd:
            return -1.0
        score -= (candidate.cost_usd * 2.0)

        if reqs.preferred_package and candidate.package:
            if reqs.preferred_package.lower() in candidate.package.lower():
                score += 15.0

        return max(score, 0.0)

    def _score_web_candidate(self, candidate: CandidateComponent, reqs: ComponentRequirements) -> float:
        """Same hard-constraint gating as _score_candidate, but for a web result
        whose numeric fields are already floats rather than raw strings. A web
        candidate that's real but doesn't actually satisfy the requirement
        should be rejected exactly like an offline one would be — being
        '"real"' doesn't exempt it from the spec."""
        if candidate.voltage_max is not None and reqs.voltage_min is not None and candidate.voltage_max < reqs.voltage_min:
            return -1.0
        if candidate.voltage_min is not None and reqs.voltage_max is not None and candidate.voltage_min > reqs.voltage_max:
            return -1.0
        if (candidate.current_ma is not None and reqs.current_min_ma is not None
                and candidate.current_ma > 0 and candidate.current_ma < reqs.current_min_ma):
            return -1.0
        if (candidate.cost_usd_estimate is not None and reqs.max_cost_usd is not None
                and candidate.cost_usd_estimate > reqs.max_cost_usd):
            return -1.0
        return candidate.confidence * 100.0

    async def select_best_part(self, reqs: ComponentRequirements) -> Optional[ComponentCandidate]:
        logger.info("[Engine] Starting evaluation for subsystem tier: '%s'", reqs.category)

        # Step 1: offline DB first.
        offline_candidates = self._query_offline_db(reqs.category)
        scored_offline = []
        for cand in offline_candidates:
            score = self._score_candidate(cand, reqs)
            if score >= 0:
                cand.confidence_score = score
                scored_offline.append(cand)
        scored_offline.sort(key=lambda x: x.confidence_score, reverse=True)

        if scored_offline:
            best_local = scored_offline[0]
            logger.info(
                "[Engine] Found matching offline component: %s (score=%.2f)",
                best_local.part_number, best_local.confidence_score,
            )
            return best_local

        # Step 2: real web search — no match locally, search live, no mock fallback.
        logger.info("[Engine] No offline match for '%s'. Searching the web...", reqs.category)
        web_input = WebSearchConnectorInput(
            category=reqs.category,
            requirements={
                "voltage_min": reqs.voltage_min,
                "voltage_max": reqs.voltage_max,
                "current_min": reqs.current_min_ma,
                "max_cost_usd": reqs.max_cost_usd,
            },
        )

        try:
            online_response = await self.online_provider.search(web_input)
        except Exception as exc:
            logger.warning("[Engine] Web search raised for '%s': %s", reqs.category, exc)
            return None

        if not online_response.candidates:
            logger.warning("[Engine] No real, verifiable component found for '%s' (offline or online).", reqs.category)
            return None

        best_online = online_response.candidates[0]
        score = self._score_web_candidate(best_online, reqs)
        if score < 0:
            logger.warning(
                "[Engine] Web result '%s' for '%s' failed hard constraints "
                "(voltage/current/cost) — rejecting rather than using a "
                "real-but-unsuitable part.", best_online.part_number, reqs.category,
            )
            return None

        logger.info(
            "[Engine] Found via web search: %s (%s, confidence=%.2f) — %s",
            best_online.part_number, best_online.manufacturer,
            best_online.confidence, best_online.source_url,
        )
        return ComponentCandidate(
            part_number=best_online.part_number,
            manufacturer=best_online.manufacturer,
            category=best_online.category or reqs.category,
            source="web_search",
            voltage_raw=(
                f"{best_online.voltage_min if best_online.voltage_min is not None else ''}-"
                f"{best_online.voltage_max if best_online.voltage_max is not None else ''}V"
            ),
            current_raw=f"{best_online.current_ma if best_online.current_ma is not None else ''}mA",
            package=best_online.package,
            cost_usd=best_online.cost_usd_estimate or 0.0,
            confidence_score=score,
            source_url=best_online.source_url,
            datasheet_url=best_online.datasheet_url,
            notes=(
                f"Found via live web search (Gemini + Google Search grounding); "
                f"source: {best_online.source_url}"
            ),
        )


# ──────────────────────────────────────────────────────────────────────────────
# Manual smoke test (not run on import / not used by the pipeline)
# ──────────────────────────────────────────────────────────────────────────────

async def _main():
    logging.basicConfig(level=logging.INFO)
    engine = PartSelectionEngine("./samvit_parts.db")

    # Scenario A: exists offline.
    reqs_a = ComponentRequirements(
        category="Buck-Boost", voltage_min=3.3, voltage_max=5.0,
        current_min_ma=1500, preferred_package="VSON-10",
    )
    part_a = await engine.select_best_part(reqs_a)
    print(f"Result A: {part_a.part_number if part_a else 'None'} "
          f"from {part_a.source if part_a else 'N/A'}")

    # Scenario B: not in the 50-part offline DB -> real web search.
    reqs_b = ComponentRequirements(
        category="6-axis IMU breakout module", voltage_min=1.7, voltage_max=3.6,
        current_min_ma=1,
    )
    part_b = await engine.select_best_part(reqs_b)
    if part_b:
        print(f"Result B: {part_b.part_number} from {part_b.source} — {part_b.source_url}")
    else:
        print("Result B: None (no real, verifiable match found)")


if __name__ == "__main__":
    asyncio.run(_main())