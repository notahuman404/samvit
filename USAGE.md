# How to Use the Agent

  Samvit's AI hardware pipeline lives in the `agent/` package. Here's everything you need to get started.

  ---

  ## Prerequisites

  - Python 3.10+
  - A Gemini API key (free tier works for testing)

  Install dependencies:

  ```bash
  pip install -r requirements.txt
  ```

  Set your environment variables:

  ```bash
  export GEMINI_API_KEY_1="your-key-here"
  # Optional — helps with quota limits
  export GEMINI_API_KEY_2="your-second-key-here"
  ```

  ---

  ## Running the Pipeline

  ### Quick demo (built-in example)

  ```bash
  python main.py --demo
  ```

  This runs the full pipeline on a built-in haptic feedback wearable example — no input file needed.

  ---

  ### From a plain-text description

  Describe what you want to build in natural language:

  ```bash
  python main.py "Build a wearable haptic feedback glove for the visually impaired"
  ```

  ---

  ### From a structured JSON requirements file

  Create a `requirements.json` file:

  ```json
  {
    "name": "My Device",
    "description": "A wrist-worn device that...",
    "goals": [
      "Detect obstacles at 0.5–5m range",
      "Vibration feedback via haptic motors",
      "BLE connectivity to companion app",
      "8+ hours battery life"
    ]
  }
  ```

  Then run:

  ```bash
  python main.py --req requirements.json
  ```

  ---

  ### With a human override file

  Override specific pipeline decisions manually:

  ```bash
  python main.py "..." --overrides human_overrides.json
  ```

  ---

  ## Environment Variables

  | Variable | Required | Default | Description |
  |---|---|---|---|
  | `GEMINI_API_KEY_1` | ✅ Yes | — | Primary Gemini API key |
  | `GEMINI_API_KEY_2` | No | — | Secondary key for quota relief |
  | `SAMVIT_DB_PATH` | No | `hardware_builder/samvit_parts.db` | Path to the component database |
  | `SAMVIT_CHECKPOINT` | No | `checkpoint/` | Directory for saving pipeline checkpoints |
  | `SAMVIT_MAX_ITER` | No | `8` | Maximum main loop iterations |

  ---

  ## What the Pipeline Does

  When you run the pipeline, it:

  1. **Parses requirements** — understands your hardware goals
  2. **Plans architecture** — decides MCU, sensors, power strategy
  3. **Fetches datasheets** — pulls real component datasheets
  4. **Searches component DB** — finds matching parts in the database
  5. **Selects parts** — picks the best components for your use case
  6. **Checks compatibility** — validates voltage, pinout, and BOM conflicts
  7. **Generates schematic** — produces a circuit graph
  8. **Runs layout stages** — footprint mapping, placement, routing
  9. **Runs design checks** — ERC, DRC, power, thermal, short-circuit analysis
  10. **Simulates** — runs SPICE-style simulation
  11. **Exports** — outputs KiCad files, Gerbers, JSONL logs, ASCII visualizer

  ---

  ## Output Files

  After a successful run you'll find:

  ```
  checkpoint/          ← Intermediate pipeline state (auto-saved)
  output/              ← Final exports (KiCad, Gerber, reports)
  ```

  ---

  ## Package Structure

  ```
  agent/
  ├── __init__.py
  ├── orchestrator.py         ← Top-level pipeline runner
  ├── core/
  │   ├── models.py           ← Shared data models (DesignState, etc.)
  │   ├── checkpoint.py       ← Save/load pipeline state
  │   └── gemini_manager.py   ← Gemini API key rotation & calls
  └── pipeline/
      ├── p01_requirements.py ← Stage 1: parse requirements
      ├── p03_architecture.py ← Stage 3: plan architecture
      ├── p05_datasheet.py    ← Stage 5: fetch datasheets
      ├── ...                 ← (30 pipeline stages total)
      └── p30_human_override.py
  ```

  ---

  ## Troubleshooting

  **`ModuleNotFoundError: No module named 'agent'`**
  Make sure you're running from the repo root:
  ```bash
  cd /path/to/samvit
  python main.py --demo
  ```

  **Gemini quota errors**
  Set a second API key via `GEMINI_API_KEY_2`. The pipeline rotates between keys automatically.

  **Pipeline stalls on a stage**
  Increase the iteration limit:
  ```bash
  SAMVIT_MAX_ITER=16 python main.py --demo
  ```

  ---

  ## Contributing

  1. Fork the repo
  2. Create a feature branch: `git checkout -b my-feature`
  3. Add your stage(s) in `agent/pipeline/` following the existing naming pattern
  4. Open a PR — describe what your stage does and which pipeline step it fits into
  