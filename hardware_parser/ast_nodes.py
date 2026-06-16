"""
AST Node Definitions for HWDL Compiler

Defines all abstract syntax tree node types used throughout the compiler pipeline.
"""

from dataclasses import dataclass
from typing import Optional, List, Union
from enum import Enum


@dataclass(frozen=True)
class SourceLoc:
    """Source location for error reporting."""
    file: str     # absolute path to source file
    line: int     # 1-based line number of first character
    col: int      # 1-based column number of first character


class PinDirection(Enum):
    """Pin direction enumeration."""
    POWER_IN = "power_in"
    POWER_OUT = "power_out"
    POWER_GND = "power_gnd"
    INPUT = "input"
    OUTPUT = "output"
    BIDIR = "bidir"
    PASSIVE = "passive"
    OPEN_DRAIN = "open_drain"
    NO_CONNECT = "no_connect"


# ─── Root ────────────────────────────────────────────────────────────────────

@dataclass
class VersionDecl:
    major: int
    minor: int
    loc: SourceLoc


@dataclass
class File:
    version: VersionDecl
    items: List['TopDecl']  # part_decl, power_decl, module_decl, target_decl
    loc: SourceLoc


# ─── Part ────────────────────────────────────────────────────────────────────

@dataclass
class PinStmt:
    name: str           # IDENT
    direction: PinDirection
    loc: SourceLoc


@dataclass
class PartDecl:
    name: str           # from STRING_LIT (unquoted)
    attrs: List['AttrStmt']
    pins: Optional[List[PinStmt]]  # None if no pins block
    loc: SourceLoc


# ─── Power ───────────────────────────────────────────────────────────────────

@dataclass
class PowerDecl:
    name: str           # IDENT
    attrs: List['AttrStmt']
    loc: SourceLoc


# ─── Net ─────────────────────────────────────────────────────────────────────

@dataclass
class NetDecl:
    name: str   # IDENT
    loc: SourceLoc


# ─── Module ──────────────────────────────────────────────────────────────────

@dataclass
class InstanceDecl:
    ref_name: str               # local name (U1, C1…)
    part_name: str              # STRING_LIT reference to a part
    attrs: Optional[List['AttrStmt']]  # instance overrides
    loc: SourceLoc


@dataclass
class PinRef:
    instance: str   # IDENT (left side of dot)
    pin: str        # IDENT (right side of dot)
    loc: SourceLoc


@dataclass
class PowerRef:
    domain: str   # IDENT after "power."
    loc: SourceLoc


@dataclass
class NetRef:
    name: str   # IDENT
    loc: SourceLoc


# Endpoint union
Endpoint = Union[PinRef, PowerRef, NetRef]


@dataclass
class ConnectStmt:
    src: PinRef         # always PinRef in v1.0
    dst: Endpoint       # can be PinRef, PowerRef, or NetRef
    loc: SourceLoc


@dataclass
class ConstraintBlock:
    attrs: List['AttrStmt']
    loc: SourceLoc


@dataclass
class PlacementBlock:
    attrs: List['AttrStmt']
    loc: SourceLoc


@dataclass
class RoutingBlock:
    attrs: List['AttrStmt']
    loc: SourceLoc


@dataclass
class ValidateBlock:
    attrs: List['AttrStmt']
    loc: SourceLoc


@dataclass
class SimulateBlock:
    attrs: List['AttrStmt']
    loc: SourceLoc


@dataclass
class ModuleDecl:
    name: str
    items: List['ModuleItem']  # instances, nets, connects, blocks
    constraint: Optional[ConstraintBlock]
    placement: Optional[PlacementBlock]
    routing: Optional[RoutingBlock]
    validate: Optional[ValidateBlock]
    simulate: Optional[SimulateBlock]
    loc: SourceLoc


ModuleItem = Union[InstanceDecl, NetDecl, ConnectStmt]


# ─── Target ──────────────────────────────────────────────────────────────────

@dataclass
class TargetDecl:
    name: str
    attrs: List['AttrStmt']
    loc: SourceLoc


# ─── Top-level union ─────────────────────────────────────────────────────────

TopDecl = Union[PartDecl, PowerDecl, ModuleDecl, TargetDecl]


# ─── Attributes ──────────────────────────────────────────────────────────────

@dataclass
class AttrKey:
    parts: List[str]   # 1 or 2 elements (dotted key like "board.size")
    loc: SourceLoc


@dataclass
class StringVal:
    value: str
    loc: SourceLoc


@dataclass
class PhysVal:
    number: float
    unit: str           # e.g., "V", "mA", "nF"
    loc: SourceLoc


@dataclass
class RangeVal:
    low: PhysVal
    high: PhysVal
    loc: SourceLoc


@dataclass
class BoolVal:
    value: bool
    loc: SourceLoc


@dataclass
class ListVal:
    items: List['AttrVal']
    loc: SourceLoc


@dataclass
class IdentVal:
    name: str     # bare IDENT used as value
    loc: SourceLoc


@dataclass
class IntVal:
    value: int
    loc: SourceLoc


# AttrVal union
AttrVal = Union[StringVal, PhysVal, RangeVal, BoolVal, ListVal, IdentVal, IntVal]


@dataclass
class AttrStmt:
    key: AttrKey
    val: AttrVal
    loc: SourceLoc
