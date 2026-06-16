"""
GeminiModelManager
==================
Multi-key, multi-model Gemini router with real-time quota awareness,
automatic key rotation on 429s, and an async call interface designed
to minimise total API round-trips through batched, context-rich prompts.

Model tiers
-----------
  HEAVY   → gemini-2.5-pro-preview-06-05 (rank 1)
             gemini-2.5-flash             (rank 2)
  MEDIUM  → gemini-2.5-flash-lite        (rank 1)
             gemini-2.0-flash-lite        (rank 2)
  LIGHT   → gemma-3-27b-it  | gemma-3-12b-it | gemma-3-4b-it

Key rotation rules
------------------
  * All registered keys are tried in round-robin order per tier.
  * A key is skipped for DEFAULT_HARD_BLOCK_SECS after a live 429.
  * Hard→medium downgrade is allowed; medium→light is NEVER allowed.

Request batching guidance
-------------------------
  Callers should embed the full pipeline context — requirements,
  current design state, all issues, metrics — into a SINGLE prompt so
  that plan + critique + repair decisions happen in one network call.
  The `call_gemini` method enforces a minimum token budget and will
  warn if the prompt is suspiciously short (likely under-batched).
"""

from __future__ import annotations

import asyncio
import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Quota snapshot per (api_key, model)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class QuotaSnapshot:
    """Tracks rate-limit state for one (api_key × model) pair."""
    hard_blocked_until: float = 0.0   # monotonic; 0 = not blocked
    consecutive_429s:   int   = 0

    @property
    def is_available(self) -> bool:
        return time.monotonic() >= self.hard_blocked_until

    @property
    def seconds_blocked(self) -> float:
        return max(0.0, self.hard_blocked_until - time.monotonic())

    def mark_429(self, retry_after: int = 60) -> None:
        self.hard_blocked_until = time.monotonic() + retry_after
        self.consecutive_429s  += 1

    def mark_success(self) -> None:
        self.consecutive_429s = 0


# ──────────────────────────────────────────────────────────────────────────────
# Manager
# ──────────────────────────────────────────────────────────────────────────────

class GeminiModelManager:
    """
    Central Gemini router.

    Startup
    -------
        manager = GeminiModelManager(api_keys=["KEY_A", "KEY_B"])

    Usage
    -----
        response_text = await manager.call_gemini(prompt, task="heavy")
        response_text = await manager.call_gemini(prompt, task="medium")
    """

    # ── Model rosters ────────────────────────────────────────────────────────
    HEAVY_MODELS: List[str] = [
        "gemini-2.5-pro-preview-06-05",
        "gemini-2.5-flash",
    ]
    MEDIUM_MODELS: List[str] = [
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash-lite",
    ]
    LIGHT_MODELS: List[str] = [
        "gemma-3-27b-it",
        "gemma-3-12b-it",
        "gemma-3-4b-it",
    ]

    TIER_MAP: Dict[str, List[str]] = {
        "heavy":  HEAVY_MODELS,
        "medium": MEDIUM_MODELS,
        "light":  LIGHT_MODELS,
    }

    DEFAULT_HARD_BLOCK_SECS: int  = 65
    MAX_RETRIES:              int  = 6
    MIN_PROMPT_CHARS:         int  = 200   # warn if prompt is too short (under-batched)

    def __init__(
        self,
        api_keys: List[str],
        default_tier: str = "heavy",
        max_output_tokens: int = 8192,
    ) -> None:
        if not api_keys:
            raise ValueError("At least one Gemini API key is required.")

        self.api_keys          = list(api_keys)
        self.default_tier      = default_tier
        self.max_output_tokens = max_output_tokens

        # (api_key, model) → QuotaSnapshot
        self._quotas: Dict[Tuple[str, str], QuotaSnapshot] = {}
        self._lock   = threading.Lock()

        all_models = self.HEAVY_MODELS + self.MEDIUM_MODELS + self.LIGHT_MODELS
        for key in self.api_keys:
            for model in all_models:
                self._quotas[(key, model)] = QuotaSnapshot()

        # Round-robin pointer per tier
        self._rr: Dict[str, int] = {"heavy": 0, "medium": 0, "light": 0}

        logger.info(
            "GeminiModelManager ready — %d key(s), default_tier=%s",
            len(self.api_keys), self.default_tier,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _quota(self, key: str, model: str) -> QuotaSnapshot:
        with self._lock:
            return self._quotas[(key, model)]

    def _mark_429(self, key: str, model: str, retry_after: int) -> None:
        with self._lock:
            self._quotas[(key, model)].mark_429(retry_after)
        logger.warning(
            "429 on key=...%s model=%s — blocked for %ds",
            key[-4:], model, retry_after,
        )

    def _mark_success(self, key: str, model: str) -> None:
        with self._lock:
            self._quotas[(key, model)].mark_success()

    def _pick(self, tier: str) -> Optional[Tuple[str, str]]:
        """
        Pick the next available (api_key, model) pair for the given tier.
        Rotates through keys in round-robin; tries each model in priority order.
        Returns None if everything is blocked.
        """
        models = self.TIER_MAP.get(tier, self.HEAVY_MODELS)
        n_keys = len(self.api_keys)

        for model in models:
            start = self._rr.get(tier, 0)
            for offset in range(n_keys):
                idx = (start + offset) % n_keys
                key = self.api_keys[idx]
                snap = self._quota(key, model)
                if snap.is_available:
                    self._rr[tier] = (idx + 1) % n_keys
                    return key, model

        return None  # all blocked

    def _make_client(self, api_key: str) -> Any:
        """Lazily import google.generativeai and return a configured client."""
        try:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=api_key)
            return genai
        except ImportError:
            raise RuntimeError(
                "google-generativeai is not installed. "
                "Run: pip install google-generativeai"
            )

    # ── Public API ───────────────────────────────────────────────────────────

    async def call_gemini(
        self,
        prompt: str,
        task: str = "heavy",
        system_instruction: str = "",
        temperature: float = 0.2,
        model_override: Optional[str] = None,
    ) -> str:
        """
        Send a prompt to Gemini and return the response text.

        Parameters
        ----------
        prompt:             The full user prompt. Include ALL context needed
                            so the model can complete multiple sub-tasks in
                            one call (plan + critique + repair = 1 request).
        task:               Tier to use: "heavy" | "medium" | "light".
        system_instruction: Optional system prompt prepended to the call.
        temperature:        Sampling temperature (0.0–1.0).
        model_override:     Force a specific model name regardless of tier.

        Returns
        -------
        Response text string.
        """
        if len(prompt) < self.MIN_PROMPT_CHARS:
            logger.warning(
                "Prompt is very short (%d chars). Consider batching more "
                "context into a single call to reduce total API requests.",
                len(prompt),
            )

        last_error: Optional[Exception] = None

        for attempt in range(self.MAX_RETRIES):
            if model_override:
                # Try each key in order for the overridden model
                pair = None
                for key in self.api_keys:
                    snap = self._quota(key, model_override)
                    if snap.is_available:
                        pair = (key, model_override)
                        break
            else:
                pair = self._pick(task)

            if pair is None:
                # All keys blocked — wait for the shortest block to expire
                min_wait = min(
                    self._quota(k, m).seconds_blocked
                    for k in self.api_keys
                    for m in self.TIER_MAP.get(task, self.HEAVY_MODELS)
                )
                wait = max(min_wait, 2.0)
                logger.info("All keys blocked. Waiting %.1fs …", wait)
                await asyncio.sleep(wait)
                continue

            api_key, model = pair

            try:
                response_text = await self._call_once(
                    api_key, model, prompt, system_instruction, temperature
                )
                self._mark_success(api_key, model)
                logger.info(
                    "Gemini call OK — model=%s key=...%s attempt=%d",
                    model, api_key[-4:], attempt + 1,
                )
                return response_text

            except Exception as exc:
                last_error = exc
                exc_str    = str(exc).lower()

                if "429" in exc_str or "quota" in exc_str or "resource_exhausted" in exc_str:
                    retry_after = self._parse_retry_after(exc) or self.DEFAULT_HARD_BLOCK_SECS
                    self._mark_429(api_key, model, retry_after)
                    # Immediately retry — _pick will select a different key/model
                    continue

                if "400" in exc_str or "invalid" in exc_str:
                    logger.error("Bad request to Gemini: %s", exc)
                    raise

                # Transient network / server error — exponential backoff
                wait = 2 ** attempt
                logger.warning(
                    "Gemini error attempt %d/%d: %s — retrying in %ds",
                    attempt + 1, self.MAX_RETRIES, exc, wait,
                )
                await asyncio.sleep(wait)

        raise RuntimeError(
            f"Gemini call failed after {self.MAX_RETRIES} attempts. "
            f"Last error: {last_error}"
        )

    async def _call_once(
        self,
        api_key: str,
        model: str,
        prompt: str,
        system_instruction: str,
        temperature: float,
    ) -> str:
        """Single blocking Gemini call wrapped in asyncio.to_thread."""
        def _sync_call() -> str:
            import google.generativeai as genai  # type: ignore
            genai.configure(api_key=api_key)

            config = {"temperature": temperature, "max_output_tokens": self.max_output_tokens}

            if system_instruction:
                gen_model = genai.GenerativeModel(
                    model_name=model,
                    system_instruction=system_instruction,
                    generation_config=config,
                )
            else:
                gen_model = genai.GenerativeModel(
                    model_name=model,
                    generation_config=config,
                )

            response = gen_model.generate_content(prompt)
            return response.text

        return await asyncio.to_thread(_sync_call)

    @staticmethod
    def _parse_retry_after(exc: Exception) -> Optional[int]:
        """Extract retry-after seconds from a 429 error if present."""
        try:
            msg = str(exc)
            import re
            m = re.search(r"retry.?after[^\d]*(\d+)", msg, re.IGNORECASE)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return None

    def status_report(self) -> Dict[str, Any]:
        """Return a dict summarising current quota state for all key×model pairs."""
        report: Dict[str, Any] = {}
        with self._lock:
            for (key, model), snap in self._quotas.items():
                label = f"...{key[-4:]}/{model}"
                report[label] = {
                    "available":         snap.is_available,
                    "blocked_for_secs":  snap.seconds_blocked,
                    "consecutive_429s":  snap.consecutive_429s,
                }
        return report
