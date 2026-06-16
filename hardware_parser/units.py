"""
Unit System for HWDL Compiler

Handles physical value units and normalization.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Tuple


@dataclass(frozen=True)
class UnitInfo:
    """Information about a physical unit."""
    symbol: str         # e.g., "V", "mA", "nF"
    dimension: str      # e.g., "voltage", "current", "capacitance"
    to_base: float      # multiplier to convert to base unit


# Unit registry: symbol -> (dimension, multiplier to base unit)
UNITS: Dict[str, Tuple[str, float]] = {
    # Voltage
    "V": ("voltage", 1.0),
    "mV": ("voltage", 0.001),
    "uV": ("voltage", 0.000001),
    
    # Current
    "A": ("current", 1.0),
    "mA": ("current", 0.001),
    "uA": ("current", 0.000001),
    "nA": ("current", 0.000000001),
    
    # Resistance
    "Ohm": ("resistance", 1.0),
    "kOhm": ("resistance", 1000.0),
    "MOhm": ("resistance", 1000000.0),
    
    # Capacitance
    "F": ("capacitance", 1.0),
    "mF": ("capacitance", 0.001),
    "uF": ("capacitance", 0.000001),
    "nF": ("capacitance", 0.000000001),
    "pF": ("capacitance", 0.000000000001),
    
    # Inductance
    "H": ("inductance", 1.0),
    "mH": ("inductance", 0.001),
    "uH": ("inductance", 0.000001),
    "nH": ("inductance", 0.000000001),
    
    # Frequency
    "Hz": ("frequency", 1.0),
    "kHz": ("frequency", 1000.0),
    "MHz": ("frequency", 1000000.0),
    "GHz": ("frequency", 1000000000.0),
    
    # Temperature
    "C": ("temperature", 1.0),
    "F": ("temperature", 1.0),  # approximated, not real conversion
    
    # Percentage
    "%": ("percentage", 1.0),
    
    # Time
    "s": ("time", 1.0),
    "ms": ("time", 0.001),
    "us": ("time", 0.000001),
    "ns": ("time", 0.000000001),
    "ps": ("time", 0.000000000001),
}


def get_unit_dimension(unit: str) -> Optional[str]:
    """Get the physical dimension for a unit symbol."""
    if unit in UNITS:
        return UNITS[unit][0]
    return None


def get_unit_to_base(unit: str) -> Optional[float]:
    """Get the multiplier to convert a unit to its base unit."""
    if unit in UNITS:
        return UNITS[unit][1]
    return None


def get_base_unit(dimension: str) -> Optional[str]:
    """Get the base unit symbol for a dimension."""
    base_units = {
        "voltage": "V",
        "current": "A",
        "resistance": "Ohm",
        "capacitance": "F",
        "inductance": "H",
        "frequency": "Hz",
        "temperature": "C",
        "percentage": "%",
        "time": "s",
    }
    return base_units.get(dimension)


def normalize_physical_value(value: float, unit: str) -> Tuple[float, str]:
    """
    Normalize a physical value to its base unit.
    
    Args:
        value: numeric value
        unit: unit symbol
        
    Returns:
        (normalized_value, base_unit) or (value, unit) if unit is unknown
    """
    if unit not in UNITS:
        return (value, unit)
    
    dimension, to_base = UNITS[unit]
    base_unit = get_base_unit(dimension)
    normalized = value * to_base
    
    return (normalized, base_unit or unit)


def are_units_compatible(unit1: str, unit2: str) -> bool:
    """Check if two units have the same physical dimension."""
    dim1 = get_unit_dimension(unit1)
    dim2 = get_unit_dimension(unit2)
    
    if dim1 is None or dim2 is None:
        return False
    
    return dim1 == dim2


def list_units_by_dimension(dimension: str) -> list:
    """List all unit symbols for a given dimension."""
    return [symbol for symbol, (dim, _) in UNITS.items() if dim == dimension]
