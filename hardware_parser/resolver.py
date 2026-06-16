"""
Resolver for HWDL Compiler

Populates cross-references in the AST after validation.
"""

from typing import Dict, Optional
from ast_nodes import *


class ResolvedAST:
    """AST with resolved references."""
    def __init__(self, file_ast: File):
        self.file = file_ast
        self.parts: Dict[str, PartDecl] = {}
        self.power_domains: Dict[str, PowerDecl] = {}
        self.modules: Dict[str, ModuleDecl] = {}
        
        # Populate global tables
        for decl in file_ast.top_decls:
            if isinstance(decl, PartDecl):
                self.parts[decl.name] = decl
            elif isinstance(decl, PowerDecl):
                self.power_domains[decl.name] = decl
            elif isinstance(decl, ModuleDecl):
                self.modules[decl.name] = decl

        # Instance to Part mapping
        self.instance_parts: Dict[tuple[str, str], PartDecl] = {} # (module, inst) -> Part
        for mod_name, mod in self.modules.items():
            for item in mod.items:
                if isinstance(item, InstanceDecl):
                    if item.part_name in self.parts:
                        self.instance_parts[(mod_name, item.ref_name)] = self.parts[item.part_name]


def resolve(ast: File) -> ResolvedAST:
    """Resolve references in the AST."""
    return ResolvedAST(ast)
