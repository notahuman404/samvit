"""
Top-level Compiler for HWDL

Coordinates the compiler pipeline.
"""

from typing import Dict, List, Tuple, Optional
from parser import Parser
from validator import Validator
from resolver import resolve
from normalizer import Normalizer
from ir_emitter import emit_ir
from diagnostics import DiagList, Diagnostic


def compile_hwdl(
    source: str,
    source_path: str = "<stdin>",
) -> Tuple[Optional[Dict], DiagList]:
    """
    Compiles HWDL source to IR.
    Returns (ir_dict, diagnostics).
    """
    parser, diags = Parser.from_source(source, source_path)
    ast = parser.parse_file()
    
    if diags.has_errors():
        return None, diags
    
    validator = Validator(ast, diags)
    validator.validate()
    
    if any(d.severity.value == "error" for d in diags.items):
        return None, diags
    
    resolved = resolve(ast)
    normalizer = Normalizer(resolved)
    normalizer.normalize()
    
    ir = emit_ir(resolved, normalizer, diags)
    return ir, diags
