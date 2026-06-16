"""
Diagnostic System for HWDL Compiler

Manages error and warning reporting with precise source locations.
"""

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum
from ast_nodes import SourceLoc


class Severity(Enum):
    """Diagnostic severity levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Diagnostic:
    """A single diagnostic message (error, warning, or info)."""
    code: str           # e.g., "E201", "W010"
    severity: Severity
    loc: SourceLoc
    message: str        # user-facing message
    context: Optional[str] = None  # optional context/hint
    hint: Optional[str] = None     # optional fix suggestion

    def format(self) -> str:
        """Format diagnostic for console output."""
        lines = [
            f"{self.severity.value.upper()} {self.code} {self.loc.file}:{self.loc.line}:{self.loc.col}",
            f"  {self.message}",
        ]
        if self.context:
            lines.append(f"  {self.context}")
        if self.hint:
            lines.append(f"  hint: {self.hint}")
        return "\n".join(lines)


class DiagList:
    """Accumulator for diagnostic messages."""

    def __init__(self):
        self.items: List[Diagnostic] = []

    def error(self, code: str, loc: SourceLoc, message: str, context: Optional[str] = None, hint: Optional[str] = None) -> None:
        """Add an error diagnostic."""
        self.items.append(Diagnostic(code, Severity.ERROR, loc, message, context, hint))

    def warning(self, code: str, loc: SourceLoc, message: str, context: Optional[str] = None, hint: Optional[str] = None) -> None:
        """Add a warning diagnostic."""
        self.items.append(Diagnostic(code, Severity.WARNING, loc, message, context, hint))

    def info(self, code: str, loc: SourceLoc, message: str, context: Optional[str] = None, hint: Optional[str] = None) -> None:
        """Add an info diagnostic."""
        self.items.append(Diagnostic(code, Severity.INFO, loc, message, context, hint))

    def has_errors(self) -> bool:
        """Check if any errors have been recorded."""
        return any(d.severity == Severity.ERROR for d in self.items)

    def has_warnings(self) -> bool:
        """Check if any warnings have been recorded."""
        return any(d.severity == Severity.WARNING for d in self.items)

    def format_all(self) -> str:
        """Format all diagnostics for console output."""
        return "\n".join(d.format() for d in self.items)

    def count_by_severity(self) -> dict:
        """Return counts of diagnostics by severity."""
        counts = {
            "error": 0,
            "warning": 0,
            "info": 0,
        }
        for d in self.items:
            counts[d.severity.value] += 1
        return counts
