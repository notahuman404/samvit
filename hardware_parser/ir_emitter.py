"""
IR Emitter for HWDL Compiler

Serializes the normalized, resolved AST to JSON IR.
"""

import json
from typing import Dict, List, Any
from ast_nodes import *
from resolver import ResolvedAST
from normalizer import Normalizer, normalize_val
from diagnostics import Diagnostic, DiagList


def loc_to_dict(loc: SourceLoc) -> Dict[str, Any]:
    return {
        "file": loc.file,
        "line": loc.line,
        "col": loc.col
    }


def emit_ir(resolved: ResolvedAST, normalizer: Normalizer, diags: DiagList) -> Dict[str, Any]:
    ir = {
        "ir_version": "1.0",
        "hwdl_version": f"{resolved.file.version.major}.{resolved.file.version.minor}",
        "source_file": resolved.file.source,
        "parts": {},
        "power_domains": {},
        "modules": {},
        "targets": {},
        "diagnostics": []
    }

    # Parts
    for name, part in resolved.parts.items():
        ir["parts"][name] = {
            "attrs": { ".".join(a.key.parts): normalize_val(a.value) for a in part.attrs },
            "pins": { p.name: { "direction": p.direction } for p in part.pins },
            "source_loc": loc_to_dict(part.loc)
        }

    # Power Domains
    for name, domain in resolved.power_domains.items():
        domain_ir = {
            "attrs": { ".".join(a.key.parts): normalize_val(a.value) for a in domain.attrs },
            "source_loc": loc_to_dict(domain.loc)
        }
        for attr in domain.attrs:
            key = ".".join(attr.key.parts)
            norm = normalize_val(attr.value)
            if key == "voltage":
                domain_ir["voltage"] = {
                    "value": norm["value"],
                    "unit": norm["unit"],
                    "normalized_V": norm.get("normalized", 0.0)
                }
            elif key == "tolerance":
                domain_ir["tolerance"] = {
                    "value": norm["value"],
                    "unit": norm["unit"],
                    "normalized": norm.get("normalized", 0.0)
                }
            elif key == "max_current":
                domain_ir["max_current"] = {
                    "value": norm["value"],
                    "unit": norm["unit"],
                    "normalized_A": norm.get("normalized", 0.0)
                }
        ir["power_domains"][name] = domain_ir

    # Modules
    for name, mod in resolved.modules.items():
        mod_ir = {
            "instances": {},
            "nets": {},
            "source_loc": loc_to_dict(mod.loc)
        }
        
        nets_in_mod = normalizer.module_nets.get(name, {})
        for net_name, net in nets_in_mod.items():
            mod_ir["nets"][net_name] = {
                "kind": net.kind,
                "power_domain": net.power_domain,
                "pins": [ {"instance": p[0], "pin": p[1]} for p in net.pins ],
                "source_loc": loc_to_dict(net.loc) if net.loc else mod_ir["source_loc"]
            }

        for item in mod.items:
            if isinstance(item, InstanceDecl):
                mod_ir["instances"][item.ref_name] = {
                    "part": item.part_name,
                    "overrides": { ".".join(a.key.parts): normalize_val(a.value) for a in item.overrides },
                    "source_loc": loc_to_dict(item.loc)
                }
            elif isinstance(item, ConstraintBlock):
                mod_ir["constraint"] = { ".".join(a.key.parts): normalize_val(a.value) for a in item.attrs }
            elif isinstance(item, PlacementBlock):
                mod_ir["placement"] = { ".".join(a.key.parts): normalize_val(a.value) for a in item.attrs }
            elif isinstance(item, RoutingBlock):
                mod_ir["routing"] = { ".".join(a.key.parts): normalize_val(a.value) for a in item.attrs }
            elif isinstance(item, ValidateBlock):
                mod_ir["validate"] = { ".".join(a.key.parts): normalize_val(a.value) for a in item.attrs }
            elif isinstance(item, SimulateBlock):
                mod_ir["simulate"] = { ".".join(a.key.parts): normalize_val(a.value) for a in item.attrs }

        ir["modules"][name] = mod_ir

    # Targets
    for name, target in resolved.targets.items():
        ir["targets"][name] = {
            "attrs": { ".".join(a.key.parts): normalize_val(a.value) for a in target.attrs },
            "source_loc": loc_to_dict(target.loc)
        }

    # Diagnostics
    for diag in diags.items:
        ir["diagnostics"].append({
            "code": diag.code,
            "severity": diag.severity.value,
            "message": diag.message,
            "loc": loc_to_dict(diag.loc)
        })

    return ir
