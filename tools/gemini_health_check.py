#!/usr/bin/env python3
"""
Gemini health / quota check
===========================
Standalone diagnostic that answers, per model tier (heavy / medium / light):

  1. Are any GEMINI_API_KEY(_n) keys present in the environment?
  2. Is the SDK the pipeline actually uses (`google.generativeai`) importable?
     (The architecture/reviewer stages call Gemini through that SDK; the
     part-search engine uses the newer `google.genai` — both are checked.)
  3. For every (key x model) the pipeline would use, can we actually reach it?
     Each pair is probed with a 1-token request and classified:

        OK          - call succeeded, you have access + quota
        NOT_FOUND   - model name is not available to this key (404)
        AUTH        - key rejected / no permission (401 / 403 / invalid key)
        RATE_LIMIT  - 429 / quota / resource_exhausted (out of credit or RPM/RPD)
        BLOCKED     - request blocked by safety / policy
        ERROR       - anything else (network, 5xx, timeout)

Note on "credit": the Gemini API has no balance endpoint. A successful call
means you have access + remaining quota; a RATE_LIMIT means you are out of
quota or over the RPM/RPD limit; AUTH means the key has no access to that model.

Usage
-----
    python tools/gemini_health_check.py                # probe every tier
    python tools/gemini_health_check.py --tier heavy   # one tier only
    python tools/gemini_health_check.py --no-probe     # list-only, no API calls
    python tools/gemini_health_check.py --json          # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

# Keep the tier rosters in sync with the live manager instead of duplicating
# the model names here.
try:
    from agent.core.gemini_manager import GeminiModelManager
    TIERS: Dict[str, List[str]] = {
        "heavy":  list(GeminiModelManager.HEAVY_MODELS),
        "medium": list(GeminiModelManager.MEDIUM_MODELS),
        "light":  list(GeminiModelManager.LIGHT_MODELS),
    }
except Exception:  # pragma: no cover - fallback if run outside repo root
    TIERS = {
        "heavy":  ["gemini-3-flash-preview", "gemini-2.5-flash"],
        "medium": ["gemini-3.1-flash-lite-preview", "gemini-2.5-flash-lite"],
        "light":  ["gemma-3-27b-it", "gemma-3-12b-it", "gemma-3-4b-it"],
    }


def resolve_api_keys() -> List[str]:
    """Collect GEMINI_API_KEY, GEMINI_API_KEY_1, GEMINI_API_KEY_2, ... .

    Mirrors main.resolve_api_keys so this tool sees exactly the keys the
    pipeline would load.
    """
    keys: List[str] = []
    itr = 0
    base = "GEMINI_API_KEY"
    while True:
        if itr == 0:
            key = os.getenv(base)
            if key:
                keys.append(key)
            itr += 1
            continue
        key = os.getenv(f"{base}_{itr}")
        if key:
            keys.append(key)
            itr += 1
        else:
            break
    return keys


def _mask(key: str) -> str:
    return f"...{key[-4:]}" if len(key) >= 4 else "????"


def _check_sdks() -> Dict[str, str]:
    """Report importability + version of both Gemini SDKs used in the repo."""
    out: Dict[str, str] = {}
    try:
        import google.generativeai as old  # type: ignore
        out["google-generativeai"] = getattr(old, "__version__", "installed")
    except Exception as exc:
        out["google-generativeai"] = f"MISSING ({exc.__class__.__name__})"
    try:
        import google.genai as new  # type: ignore
        out["google-genai"] = getattr(new, "__version__", "installed")
    except Exception as exc:
        out["google-genai"] = f"MISSING ({exc.__class__.__name__})"
    return out


def _classify(exc: Exception) -> str:
    s = str(exc).lower()
    if "429" in s or "quota" in s or "resource_exhausted" in s or "rate limit" in s:
        return "RATE_LIMIT"
    if "404" in s or "not found" in s or "not supported" in s or "is not found" in s:
        return "NOT_FOUND"
    if ("401" in s or "403" in s or "permission" in s or "api key" in s
            or "api_key_invalid" in s or "unauthenticated" in s):
        return "AUTH"
    if "block" in s or "safety" in s:
        return "BLOCKED"
    return "ERROR"


def _list_models(api_key: str) -> Optional[set]:
    """Return the set of generateContent-capable model ids for a key, or None."""
    try:
        import google.generativeai as genai  # type: ignore
        genai.configure(api_key=api_key)
        names = set()
        for m in genai.list_models():
            methods = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in methods:
                names.add(m.name.split("/")[-1])
        return names
    except Exception:
        return None


def _probe(api_key: str, model: str) -> Tuple[str, float, str]:
    """Send a minimal request. Returns (status, latency_s, detail)."""
    import google.generativeai as genai  # type: ignore
    t0 = time.monotonic()
    try:
        genai.configure(api_key=api_key)
        # Use a realistic output budget: "thinking" models (gemini-2.5/3.x) can
        # spend a tiny max_output_tokens entirely on reasoning and return no text
        # Part, which would make response.text raise and look like a failure even
        # though the model is reachable. 64 tokens is plenty for a reachability
        # probe without that false positive.
        gm = genai.GenerativeModel(
            model_name=model,
            generation_config={"temperature": 0.0, "max_output_tokens": 64},
        )
        resp = gm.generate_content("Reply with the single word: ok")
        # Don't rely on the .text quick accessor (it raises when there is no
        # plain-text Part). Treat "reachable, returned a candidate" as OK.
        text = ""
        try:
            text = resp.text or ""
        except Exception:
            cands = getattr(resp, "candidates", None) or []
            if cands:
                parts = getattr(getattr(cands[0], "content", None), "parts", []) or []
                text = "".join(getattr(p, "text", "") for p in parts)
                if not text:
                    fr = getattr(cands[0], "finish_reason", "?")
                    return "OK", time.monotonic() - t0, f"reachable (no text Part, finish_reason={fr})"
        return "OK", time.monotonic() - t0, ""
    except Exception as exc:
        return _classify(exc), time.monotonic() - t0, str(exc).splitlines()[0][:160]


def main() -> int:
    ap = argparse.ArgumentParser(description="Gemini health / quota check")
    ap.add_argument("--tier", choices=["heavy", "medium", "light"],
                    help="Only check this tier (default: all).")
    ap.add_argument("--no-probe", action="store_true",
                    help="Do not make API calls; only list keys/models/SDKs.")
    ap.add_argument("--json", action="store_true", help="Machine-readable output.")
    args = ap.parse_args()

    report: Dict[str, object] = {}

    sdks = _check_sdks()
    report["sdks"] = sdks

    keys = resolve_api_keys()
    report["key_count"] = len(keys)
    report["keys"] = [_mask(k) for k in keys]

    tiers = {args.tier: TIERS[args.tier]} if args.tier else TIERS
    report["tiers"] = {t: list(ms) for t, ms in tiers.items()}

    if not args.json:
        print("=" * 64)
        print("GEMINI HEALTH CHECK")
        print("=" * 64)
        print("SDKs:")
        for name, ver in sdks.items():
            print(f"  - {name:22s}: {ver}")
        print(f"\nKeys found: {len(keys)}  {[_mask(k) for k in keys]}")
        print("Model tiers (pipeline rosters):")
        for t, ms in tiers.items():
            print(f"  - {t:6s}: {', '.join(ms)}")

    # Hard stops -------------------------------------------------------------
    if not keys:
        report["verdict"] = "NO_KEYS"
        if not args.json:
            print("\n[VERDICT] No GEMINI_API_KEY(_n) found in the environment. "
                  "Every Gemini call will fall back to the heuristic path.")
        else:
            print(json.dumps(report, indent=2))
        return 1

    if sdks["google-generativeai"].startswith("MISSING"):
        report["verdict"] = "SDK_MISSING"
        if not args.json:
            print("\n[VERDICT] The pipeline's Gemini SDK 'google-generativeai' is "
                  "not installed, so the architecture/reviewer stages cannot call "
                  "Gemini even though keys exist. Run: pip install google-generativeai")
        if args.no_probe or sdks["google-generativeai"].startswith("MISSING"):
            if args.json:
                print(json.dumps(report, indent=2))
            return 2

    if args.no_probe:
        report["verdict"] = "LISTED_ONLY"
        if args.json:
            print(json.dumps(report, indent=2))
        return 0

    # Live probes ------------------------------------------------------------
    access: Dict[str, object] = {}
    if not args.json:
        print("\nAccessible models per key (list_models, generateContent only):")
    for k in keys:
        avail = _list_models(k)
        access[_mask(k)] = sorted(avail) if avail is not None else None
        if not args.json:
            shown = (", ".join(sorted(avail)[:8]) + (" ..." if avail and len(avail) > 8 else "")
                     if avail is not None else "(list_models failed)")
            print(f"  {_mask(k)}: {shown}")
    report["accessible_models"] = access

    results: List[Dict[str, object]] = []
    tier_usable: Dict[str, bool] = {t: False for t in tiers}
    if not args.json:
        print("\nProbe results (1-token request per key x model):")
        print(f"  {'tier':6s} {'model':32s} {'key':8s} {'status':11s} {'lat':>6s}  detail")
        print("  " + "-" * 90)
    for tier, models in tiers.items():
        for model in models:
            for k in keys:
                status, lat, detail = _probe(k, model)
                if status == "OK":
                    tier_usable[tier] = True
                row = {"tier": tier, "model": model, "key": _mask(k),
                       "status": status, "latency_s": round(lat, 2), "detail": detail}
                results.append(row)
                if not args.json:
                    print(f"  {tier:6s} {model:32s} {_mask(k):8s} "
                          f"{status:11s} {lat:5.1f}s  {detail}")
    report["probes"] = results
    report["tier_usable"] = tier_usable

    usable = [t for t, ok in tier_usable.items() if ok]
    report["verdict"] = "OK" if usable else "ALL_TIERS_FAILED"
    if not args.json:
        print("\n" + "=" * 64)
        if usable:
            print(f"[VERDICT] Usable tiers: {', '.join(usable)}. "
                  f"Tiers with no working model: "
                  f"{', '.join(t for t in tiers if t not in usable) or 'none'}.")
        else:
            print("[VERDICT] No tier has a single working (key x model) pair — "
                  "Gemini is effectively down; the pipeline will run fully on the "
                  "heuristic fallback. See the status column above for why "
                  "(NOT_FOUND = bad model name, AUTH = bad/again-scoped key, "
                  "RATE_LIMIT = out of quota/credit).")
    else:
        print(json.dumps(report, indent=2))
    return 0 if usable else 3


if __name__ == "__main__":
    sys.exit(main())
