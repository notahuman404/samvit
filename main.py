"""
Samvit Hardware Pipeline — Entry Point
========================================

Usage:
    # Free-text requirements
    python main.py "Build a wearable haptic feedback glove for the visually impaired"

    # JSON file of structured requirements
    python main.py --req requirements.json

    # With human override file
    python main.py "..." --overrides human_overrides.json

    # Quick demo (uses built-in example requirements)
    python main.py --demo

Environment variables:
    GEMINI_API_KEY_1  — first Gemini API key  (required)
    GEMINI_API_KEY_2  — second Gemini API key (optional, improves quota)
    SAMVIT_DB_PATH    — path to samvit_parts.db (default: hardware_builder/samvit_parts.db)
    SAMVIT_CHECKPOINT — checkpoint directory (default: checkpoint)
    SAMVIT_MAX_ITER   — maximum main iterations (default: 8)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import logging
from dotenv import load_dotenv
load_dotenv()

# ── Ensure samvit/ is importable regardless of cwd ───────────────────────────
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from agent.orchestrator import SamvitOrchestrator

log = logging.getLogger("samvit.main")

# ──────────────────────────────────────────────────────────────────────────────
# Built-in demo requirements
# ──────────────────────────────────────────────────────────────────────────────

DEMO_REQUIREMENTS = {
    "name":             "Haptic Feedback Wearable for Visually Impaired",
    "description": (
        "A wrist-worn device that detects obstacles via ToF sensors and LiDAR, "
        "then conveys distance and direction through haptic vibration patterns. "
        "Communicates with a companion phone app over BLE. "
        "Must run for 8 hours on a single charge from a 18650 Li-Ion cell."
    ),
    "goals": [
        "Detect obstacles at 0.5–5m range using depth sensors",
        "Convey direction and proximity via haptic patterns (DRV2605L + LRA motors)",
        "BLE connectivity to companion app for configuration",
        "8+ hours battery life on 18650 cell",
        "Lightweight and comfortable for all-day wear",
        "Audio feedback as secondary modality (I2S codec)",
    ],
    "constraints": {
        "fab_profile": "jlcpcb_2layer",
        "max_layers": 2,
    },
    "budget_usd":       80.0,
    "form_factor":      "wearable",
    "power_source":     "18650 li-ion",
    "operating_voltage": 3.3,
    "target_current_ma": 500.0,
    "environment":      "indoor",
    "success_criteria": [
        "ERC zero errors",
        "DRC zero errors",
        "Simulation pass rate >= 90%",
        "BOM cost <= $80",
        "Battery life estimate >= 8 hours",
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Samvit Autonomous Hardware Design Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "requirements",
        nargs="?",
        help="Free-text hardware requirements string",
    )
    p.add_argument(
        "--req", "--requirements-file",
        dest="req_file",
        help="Path to a JSON file with structured requirements",
    )
    p.add_argument(
        "--overrides",
        dest="overrides_file",
        help="Path to human_overrides.json",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Run with built-in wearable demo requirements",
    )
    p.add_argument(
        "--checkpoint-dir",
        default=os.environ.get("SAMVIT_CHECKPOINT", "checkpoint"),
        help="Directory for design checkpoints (default: checkpoint)",
    )
    p.add_argument(
        "--db-path",
        default=os.environ.get("SAMVIT_DB_PATH"),
        help="Path to samvit_parts.db",
    )
    p.add_argument(
        "--max-iter",
        type=int,
        default=int(os.environ.get("SAMVIT_MAX_ITER", "8")),
        help="Maximum main loop iterations (default: 8)",
    )
    p.add_argument(
        "--max-fix",
        type=int,
        default=5,
        help="Maximum fix-loop rounds per main iteration (default: 5)",
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity",
    )
    return p.parse_args()


def resolve_api_keys() -> list[str]:
    keys = []
    itr = 0
    base = "GEMINI_API_KEY"
    while True:
        if itr == 0 :
            key = os.getenv(base)
            if key:
                keys.append(key)
            itr+=1
            continue
        
        key = os.getenv(f"{base}_{itr}")
        if key:
            keys.append(key)
            itr+=1
        else: break
    return keys

        
async def _main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("samvit_run.log", encoding="utf-8"),
        ],
    )

    # ── Resolve requirements ─────────────────────────────────────────────────
    requirements_input: object = None

    if args.demo:
        log.info("Using built-in demo requirements (Haptic Wearable).")
        requirements_input = DEMO_REQUIREMENTS
    elif args.req_file:
        with open(args.req_file, encoding="utf-8") as f:
            requirements_input = json.load(f)
        log.info("Loaded requirements from %s", args.req_file)
    elif args.requirements:
        requirements_input = args.requirements
    else:
        print("ERROR: Provide requirements as a string, --req file, or --demo.")
        print("  python main.py 'Build a IoT soil moisture sensor'")
        print("  python main.py --demo")
        sys.exit(1)

    # ── Resolve human overrides ──────────────────────────────────────────────
    overrides: dict | None = None
    if args.overrides_file:
        with open(args.overrides_file, encoding="utf-8") as f:
            overrides = json.load(f)

    # ── API keys ─────────────────────────────────────────────────────────────
    api_keys = resolve_api_keys()
    log.info("Loaded %d Gemini API key(s).", len(api_keys))

    # ── Run pipeline ─────────────────────────────────────────────────────────
    orch = SamvitOrchestrator(
        api_keys=api_keys,
        checkpoint_dir=args.checkpoint_dir,
        db_path=args.db_path,
        max_main_iterations=args.max_iter,
        max_fix_rounds=args.max_fix,
    )

    final_state = await orch.run(requirements_input, human_overrides=overrides)

    # ── Exit code based on design quality ────────────────────────────────────
    m = final_state.metrics
    if m and m.erc_errors == 0 and m.drc_errors == 0:
        log.info("\n✅  Pipeline finished — design is CLEAN.")
        sys.exit(0)
    else:
        errs = m.erc_errors + m.drc_errors if m else -1
        log.warning("\n⚠️  Pipeline finished — design still has %d error(s).", errs)
        sys.exit(1)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
