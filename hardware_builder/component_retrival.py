"""
Samvit Component Retrieval Engine
Finds best-matching parts from samvit_parts.db using keyword, category,
and spec filters. No AI — pure scoring and SQL.

Usage:
    python component_retrieval.py "depth sensor for obstacle detection"
    python component_retrieval.py "3.3V regulator" --max-cost 1.0
    python component_retrieval.py --category IMU
    python component_retrieval.py --layer hardware
    python component_retrieval.py --list-categories
"""

import sqlite3
import argparse
import os
import re
import sys
from dataclasses import dataclass
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "samvit_parts.db")

# ---------------------------------------------------------------------------
# Keyword aliases — maps common query terms to DB values or column hints
# ---------------------------------------------------------------------------
CATEGORY_ALIASES = {
    "sensor":        ["Depth Sensor", "ToF Sensor", "LiDAR", "Barometer", "IMU"],
    "camera":        ["Camera", "Depth Sensor"],
    "depth":         ["Depth Sensor", "LiDAR", "ToF Sensor"],
    "lidar":         ["LiDAR"],
    "tof":           ["ToF Sensor"],
    "imu":           ["IMU"],
    "motion":        ["IMU"],
    "gyro":          ["IMU"],
    "accel":         ["IMU"],
    "mic":           ["Microphone", "Mic Amp"],
    "microphone":    ["Microphone", "Mic Amp"],
    "audio":         ["Audio Amp", "Microphone", "Mic Amp"],
    "speaker":       ["Audio Amp"],
    "haptic":        ["Haptic Driver", "Actuator"],
    "vibration":     ["Actuator", "Haptic Driver"],
    "motor":         ["Actuator", "Haptic Driver", "MOSFET"],
    "driver":        ["Haptic Driver", "PWM Driver"],
    "pwm":           ["PWM Driver"],
    "battery":       ["Battery", "Charger IC"],
    "charger":       ["Charger IC"],
    "power":         ["Charger IC", "Buck-Boost", "Boost Converter", "LDO", "Battery"],
    "regulator":     ["LDO", "Buck-Boost", "Boost Converter"],
    "ldo":           ["LDO"],
    "boost":         ["Boost Converter", "Buck-Boost"],
    "buck":          ["Buck-Boost"],
    "bluetooth":     ["BT Module", "BLE SoC"],
    "ble":           ["BLE SoC"],
    "wifi":          ["MCU"],
    "wireless":      ["BT Module", "BLE SoC", "LoRa", "LTE Module"],
    "lte":           ["LTE Module"],
    "lora":          ["LoRa"],
    "gps":           ["LTE Module"],
    "mcu":           ["MCU"],
    "microcontroller": ["MCU"],
    "sbc":           ["SBC"],
    "raspberry":     ["SBC"],
    "esp32":         ["MCU"],
    "compute":       ["SBC", "MCU"],
    "brain":         ["SBC"],
    "flash":         ["Flash", "Storage"],
    "storage":       ["Flash", "Storage"],
    "sd":            ["Storage"],
    "display":       ["Display"],
    "oled":          ["Display"],
    "led":           ["LED"],
    "level":         ["Level Shifter", "Buffer"],
    "shifter":       ["Level Shifter"],
    "gpio":          ["IO Expander"],
    "expander":      ["IO Expander"],
    "mosfet":        ["MOSFET"],
    "switch":        ["MOSFET"],
    "diode":         ["Diode"],
    "capacitor":     ["Capacitor"],
    "resistor":      ["Resistor"],
    "connector":     ["Connector"],
    "usb":           ["Connector"],
    "jst":           ["Connector"],
}

LAYER_ALIASES = {
    "hardware": "Layer 2 Hardware",
    "hw":       "Layer 2 Hardware",
    "software": "Layer 1 Software",
    "sw":       "Layer 1 Software",
    "both":     "Layer 1 + 2",
}

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Part:
    id: int
    name: str
    category: str
    description: str
    voltage_v: str
    current_ma: str
    package: str
    footprint: str
    cost_usd: float
    compatibility: str
    notes: str
    score: float = 0.0

    def display(self, rank: int = None):
        prefix = f"[{rank}] " if rank else ""
        print(f"\n{prefix}{self.name}  ({self.category})")
        print(f"  Description : {self.description}")
        print(f"  Voltage     : {self.voltage_v}")
        print(f"  Current     : {self.current_ma} mA")
        print(f"  Package     : {self.package}  |  Footprint: {self.footprint}")
        print(f"  Cost        : ${self.cost_usd:.2f}")
        print(f"  Layer       : {self.compatibility}")
        print(f"  Notes       : {self.notes}")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def load_db(db_path: str = DB_PATH) -> list[Part]:
    if not os.path.exists(db_path):
        sys.exit(f"[ERROR] Database not found at: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM parts").fetchall()
    conn.close()
    return [Part(**dict(r)) for r in rows]


def fetch_categories(db_path: str = DB_PATH) -> list[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT DISTINCT category FROM parts ORDER BY category").fetchall()
    conn.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------
def score_part(part: Part, tokens: list[str], target_categories: list[str]) -> float:
    score = 0.0
    text = f"{part.name} {part.category} {part.description} {part.notes}".lower()

    # Category match (highest weight)
    for cat in target_categories:
        if cat.lower() == part.category.lower():
            score += 10.0
        elif cat.lower() in part.category.lower():
            score += 5.0

    # Token match across searchable fields
    for token in tokens:
        if len(token) < 2:
            continue
        if token in part.name.lower():
            score += 4.0
        if token in part.category.lower():
            score += 3.0
        if token in part.description.lower():
            score += 2.0
        if token in part.notes.lower():
            score += 1.0

    return score


def parse_query(query: str) -> tuple[list[str], list[str]]:
    """Returns (tokens, resolved_categories)."""
    tokens = re.findall(r"[a-z0-9]+", query.lower())
    categories = []
    for token in tokens:
        if token in CATEGORY_ALIASES:
            categories.extend(CATEGORY_ALIASES[token])
    return tokens, list(set(categories))


def parse_voltage(v_str: str) -> Optional[float]:
    """Extract first numeric voltage value from a string."""
    m = re.search(r"[\d.]+", v_str)
    return float(m.group()) if m else None


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def retrieve(
    query: str = "",
    category: str = None,
    layer: str = None,
    max_cost: float = None,
    max_voltage: float = None,
    top_n: int = 5,
    db_path: str = DB_PATH,
) -> list[Part]:
    parts = load_db(db_path)

    # Hard filters
    if category:
        parts = [p for p in parts if category.lower() in p.category.lower()]

    if layer:
        resolved_layer = LAYER_ALIASES.get(layer.lower(), layer)
        parts = [p for p in parts if resolved_layer.lower() in p.compatibility.lower()]

    if max_cost is not None:
        parts = [p for p in parts if p.cost_usd <= max_cost]

    if max_voltage is not None:
        parts = [p for p in parts if (v := parse_voltage(p.voltage_v)) is not None and v <= max_voltage]

    if not parts:
        return []

    # Score and rank
    if query.strip():
        tokens, target_categories = parse_query(query)
        for p in parts:
            p.score = score_part(p, tokens, target_categories)
        parts = [p for p in parts if p.score > 0]
        parts.sort(key=lambda p: p.score, reverse=True)
    else:
        parts.sort(key=lambda p: p.cost_usd)

    return parts[:top_n]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Samvit Component Retrieval — find parts from the database."
    )
    parser.add_argument("query", nargs="?", default="", help="Natural language query, e.g. 'depth sensor'")
    parser.add_argument("--category", "-c", help="Filter by exact category name")
    parser.add_argument("--layer", "-l", choices=["hardware", "hw", "software", "sw", "both"],
                        help="Filter by project layer")
    parser.add_argument("--max-cost", type=float, help="Maximum cost in USD")
    parser.add_argument("--max-voltage", type=float, help="Maximum voltage (V)")
    parser.add_argument("--top", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite database")
    parser.add_argument("--list-categories", action="store_true", help="List all categories and exit")
    args = parser.parse_args()

    if args.list_categories:
        print("Available categories:")
        for cat in fetch_categories(args.db):
            print(f"  {cat}")
        return

    results = retrieve(
        query=args.query,
        category=args.category,
        layer=args.layer,
        max_cost=args.max_cost,
        max_voltage=args.max_voltage,
        top_n=args.top,
        db_path=args.db,
    )

    if not results:
        print("No matching parts found.")
        return

    q_display = args.query or "(no query — showing filtered results)"
    print(f"\n=== Results for: '{q_display}' ===")
    for i, part in enumerate(results, 1):
        part.display(rank=i)
    print()


# ---------------------------------------------------------------------------
# Importable API
# ---------------------------------------------------------------------------
def find(query: str, **kwargs) -> list[Part]:
    """
    Importable shorthand.
    Example:
        from component_retrieval import find
        results = find("haptic motor driver", max_cost=5.0, top_n=3)
    """
    return retrieve(query=query, **kwargs)


if __name__ == "__main__":
    main()