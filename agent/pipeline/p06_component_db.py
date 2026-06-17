"""
Stage 6 — Component Database
==============================
Wraps the SQLite parts database with a clean API.
Seeds / re-uses hardware_builder/samvit_parts.db and allows the
pipeline to register newly discovered components at runtime.
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from agent.core.models import (
    Component, DesignState, Issue, PinSpec, PinType,
    Severity, StageResult, StageStatus,
)

# Default DB path — look next to this file, then in hardware_builder/
_HERE = os.path.dirname(__file__)
_DEFAULT_DB = os.path.join(_HERE, "..", "..", "hardware_builder", "samvit_parts.db")


# ──────────────────────────────────────────────────────────────────────────────
# DB accessor
# ──────────────────────────────────────────────────────────────────────────────

class ComponentDB:
    def __init__(self, db_path: str = _DEFAULT_DB) -> None:
        self.db_path = os.path.abspath(db_path)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._connect()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS parts (
                id           INTEGER PRIMARY KEY,
                name         TEXT UNIQUE,
                category     TEXT,
                description  TEXT,
                voltage_v    TEXT,
                current_ma   TEXT,
                package      TEXT,
                footprint    TEXT,
                cost_usd     REAL,
                compatibility TEXT,
                notes        TEXT
            )
        """)
        conn.commit()
        conn.close()

    def all_parts(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute("SELECT * FROM parts").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def find_by_category(self, category: str, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT * FROM parts WHERE LOWER(category) LIKE ? LIMIT ?",
            (f"%{category.lower()}%", limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def find_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM parts WHERE LOWER(name) = ?", (name.lower(),)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def insert(self, comp: Component) -> bool:
        """Insert a new component; returns False if it already exists."""
        try:
            conn = self._connect()
            conn.execute("""
                INSERT OR IGNORE INTO parts
                (name, category, description, voltage_v, current_ma,
                 package, footprint, cost_usd, compatibility, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                comp.part_number, comp.category, comp.description,
                f"{comp.voltage_min}-{comp.voltage_max}V",
                str(comp.current_ma),
                comp.package, comp.footprint, comp.cost_usd,
                "general", comp.notes,
            ))
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def row_to_component(self, row: Dict[str, Any]) -> Component:
        """Convert a DB row dict to a Component model."""
        v_str = str(row.get("voltage_v", "0-5V"))
        try:
            parts = v_str.replace("V", "").split("-")
            v_min = float(parts[0]) if parts else 0.0
            v_max = float(parts[-1]) if len(parts) > 1 else v_min
        except ValueError:
            v_min, v_max = 0.0, 5.0

        try:
            i_ma = float(str(row.get("current_ma", "0")).replace("mA", "").strip())
        except ValueError:
            i_ma = 0.0

        category = str(row.get("category", "OTHER"))
        # Power-source components must expose a POWER_OUT pin, otherwise every
        # VDD rail they feed is seen as "undriven" by ERC (ERC_UNPOWERED_VDD).
        # The schematic graph builder wires power sources via their "VOUT" pin.
        _POWER_SOURCE_CATS = {
            "POWER", "Charger IC", "Buck-Boost", "Boost Converter", "LDO", "Battery",
        }
        if category in _POWER_SOURCE_CATS:
            pins: Dict[str, PinSpec] = {
                "VIN":  PinSpec("VIN",  PinType.POWER_IN,  v_min, v_max * 1.5, 0, i_ma / 1000.0),
                "VOUT": PinSpec("VOUT", PinType.POWER_OUT, v_min, v_max if v_max > 0 else 3.3, 2.0, 0),
                "GND":  PinSpec("GND",  PinType.POWER_IN,  0, 0, 0, 0),
            }
        else:
            pins = {
                "VDD": PinSpec("VDD", PinType.POWER_IN,  v_min, v_max, 0, i_ma / 1000.0),
                "GND": PinSpec("GND", PinType.POWER_IN,  0, 0, 0, 0),
            }

        return Component(
            part_number=str(row.get("name", "UNKNOWN")),
            manufacturer="Various",
            category=category,
            description=str(row.get("description", "")),
            voltage_min=v_min,
            voltage_max=v_max,
            current_ma=i_ma,
            package=str(row.get("package", "")),
            footprint=str(row.get("footprint", "")),
            cost_usd=float(row.get("cost_usd", 0.0)),
            pins=pins,
            notes=str(row.get("notes", "")),
            confidence=0.9,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Stage entry point
# ──────────────────────────────────────────────────────────────────────────────

def run(state: DesignState, db_path: str = _DEFAULT_DB) -> StageResult:
    t0 = time.monotonic()
    issues: List[Issue] = []

    try:
        db = ComponentDB(db_path)
        all_rows = db.all_parts()

        loaded: Dict[str, Component] = {}
        for row in all_rows:
            comp = db.row_to_component(row)
            loaded[comp.part_number] = comp

        # Merge without overwriting components already enriched by datasheet parser
        for pn, comp in loaded.items():
            if pn not in state.components or state.components[pn].confidence < comp.confidence:
                state.components[pn] = comp

        return StageResult(
            stage="p06_component_db",
            status=StageStatus.PASSED,
            data={"loaded_count": len(loaded)},
            metrics={"db_component_count": float(len(loaded))},
            duration=time.monotonic() - t0,
        )

    except Exception as exc:
        issues.append(Issue(
            code="DB_ERROR",
            severity=Severity.ERROR,
            message=f"Component DB failed: {exc}",
            source="component_db",
        ))
        return StageResult(
            stage="p06_component_db",
            status=StageStatus.FAILED,
            issues=issues,
            duration=time.monotonic() - t0,
        )
