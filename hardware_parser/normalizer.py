"""
Normalizer for HWDL Compiler

Implements net merger algorithm and physical value normalization.
"""

from typing import Dict, List, Tuple, Set, Optional
from ast_nodes import *
from resolver import ResolvedAST
from units import normalize_physical_value, get_base_unit, get_unit_dimension


class NormalizedNet:
    def __init__(self, name: str, kind: str):
        self.name = name
        self.kind = kind # "signal", "power", "auto"
        self.power_domain: Optional[str] = None
        self.pins: List[Tuple[str, str]] = [] # (instance, pin)
        self.loc: Optional[SourceLoc] = None

class Normalizer:
    def __init__(self, resolved: ResolvedAST):
        self.resolved = resolved
        self.module_nets: Dict[str, Dict[str, NormalizedNet]] = {} 

    def normalize(self):
        for mod_name, mod in self.resolved.modules.items():
            self.module_nets[mod_name] = self.normalize_module(mod)

    def normalize_module(self, mod: ModuleDecl) -> Dict[str, NormalizedNet]:
        nets: Dict[str, NormalizedNet] = {}
        for item in mod.items:
            if isinstance(item, NetDecl):
                nets[item.name] = NormalizedNet(item.name, "signal")
                nets[item.name].loc = item.loc

        parent = {}
        def find(i):
            if parent[i] == i: return i
            parent[i] = find(parent[i])
            return parent[i]

        def union(i, j):
            root_i = find(i)
            root_j = find(j)
            if root_i != root_j:
                def score(name):
                    if name.startswith("$auto_"): return 0
                    if name.startswith("$power_"): return 1
                    return 2
                if score(root_i) >= score(root_j): parent[root_j] = root_i
                else: parent[root_i] = root_j

        auto_idx = 0
        for item in mod.items:
            if isinstance(item, ConnectStmt):
                src_pin = (item.src.instance, item.src.pin) if isinstance(item.src, PinRef) else str(item.src)
                if src_pin not in parent:
                    name = f"$auto_{auto_idx}"; auto_idx += 1
                    parent[src_pin] = name
                
                dst = item.dst
                if isinstance(dst, PinRef):
                    dst_pin = (dst.instance, dst.pin)
                    if dst_pin not in parent:
                        name = f"$auto_{auto_idx}"; auto_idx += 1
                        parent[dst_pin] = name
                    union(src_pin, dst_pin)
                elif isinstance(dst, PowerRef):
                    pnet = f"$power_{dst.domain}"
                    if pnet not in parent: parent[pnet] = pnet
                    union(src_pin, pnet)
                elif isinstance(dst, NetRef):
                    if dst.name not in parent: parent[dst.name] = dst.name
                    union(src_pin, dst.name)

        final_nets: Dict[str, NormalizedNet] = {}
        for p, _ in parent.items():
            root = find(p)
            if root not in final_nets:
                kind = "signal"
                if root.startswith("$auto_"): kind = "auto"
                elif root.startswith("$power_"): kind = "power"
                final_nets[root] = NormalizedNet(root, kind)
                if kind == "power": final_nets[root].power_domain = root[len("$power_"):]
            if isinstance(p, tuple): final_nets[root].pins.append(p)
        
        for name, net in nets.items():
            if name not in final_nets: final_nets[name] = net
        return final_nets

def normalize_val(val: AttrVal) -> dict:
    if isinstance(val, StringVal): return {"kind": "string", "value": val.value}
    if isinstance(val, BoolVal): return {"kind": "bool", "value": val.value}
    if isinstance(val, IdentVal): return {"kind": "ident", "value": val.name}
    if isinstance(val, PhysVal):
        norm_v, base_u = normalize_physical_value(val.number, val.unit)
        return {"kind": "phys", "value": val.number, "unit": val.unit, "normalized": norm_v, "base_unit": base_u}
    if isinstance(val, RangeVal):
        return {"kind": "range", "low": normalize_val(val.low), "high": normalize_val(val.high)}
    if isinstance(val, ListVal):
        return {"kind": "list", "items": [normalize_val(i) for i in val.items]}
    if isinstance(val, IntVal):
        return {"kind": "integer", "value": val.value}
    return {"kind": "unknown", "value": str(val)}
