"""
Semantic Validator for HWDL Compiler

Implements scope, reference, connectivity, electrical, unit, and structural rules.
"""

from typing import Dict, List, Set, Optional, Tuple, Union
from ast_nodes import *
from diagnostics import DiagList, Severity
from units import are_units_compatible, get_unit_dimension, UNITS


class Validator:
    """Semantic validator for HWDL AST."""

    def __init__(self, ast: File, diags: DiagList):
        self.ast = ast
        self.diags = diags
        self.parts: Dict[str, PartDecl] = {}
        self.power_domains: Dict[str, PowerDecl] = {}
        self.modules: Dict[str, ModuleDecl] = {}
        self.targets: Dict[str, TargetDecl] = {}

    def validate(self):
        """Perform all validation passes."""
        self.pass1_symbol_collection()
        self.pass2_reference_and_rules()

    def pass1_symbol_collection(self):
        """Collect top-level symbols and check for duplicates (SR-01 to SR-04, ST-04)."""
        for decl in self.ast.top_decls:
            if isinstance(decl, PartDecl):
                if decl.name in self.parts:
                    self.diags.error("E201", decl.loc, f"Duplicate part name '{decl.name}'; first declared at {self.parts[decl.name].loc}")
                else:
                    self.parts[decl.name] = decl
            elif isinstance(decl, PowerDecl):
                if decl.name in self.power_domains:
                    self.diags.error("E202", decl.loc, f"Duplicate power domain '{decl.name}'")
                else:
                    self.power_domains[decl.name] = decl
            elif isinstance(decl, ModuleDecl):
                if decl.name in self.modules:
                    self.diags.error("E203", decl.loc, f"Duplicate module name '{decl.name}'")
                else:
                    self.modules[decl.name] = decl
            elif isinstance(decl, TargetDecl):
                if decl.name in self.targets:
                    self.diags.error("E204", decl.loc, f"Duplicate target name '{decl.name}'")
                else:
                    self.targets[decl.name] = decl
            elif isinstance(decl, NetDecl):
                 if decl.name in self.power_domains:
                     self.diags.error("E207", decl.loc, f"Net name '{decl.name}' shadows power domain of same name")

    def pass2_reference_and_rules(self):
        """Check reference rules, connectivity, ERC, etc. (RR, CR, ER, UC, ST)."""
        for decl in self.ast.top_decls:
            if isinstance(decl, PartDecl):
                self.validate_part(decl)
            elif isinstance(decl, PowerDecl):
                self.validate_power(decl)
            elif isinstance(decl, ModuleDecl):
                self.validate_module(decl)
            elif isinstance(decl, TargetDecl):
                self.validate_target(decl)

    def validate_part(self, part: PartDecl):
        """Validate a part declaration (ST-02, ST-03)."""
        if not part.pins:
            self.diags.warning("W040", part.loc, f"Part '{part.name}' has no pins block")
        
        pin_names = set()
        for pin in part.pins:
            if pin.name in pin_names:
                self.diags.error("E100", pin.loc, f"Duplicate pin name '{pin.name}' in part '{part.name}'")
            pin_names.add(pin.name)

    def validate_power(self, power: PowerDecl):
        """Validate a power domain declaration (UC-02, UC-03, UC-04)."""
        for attr in power.attrs:
            key_name = ".".join(attr.key.parts)
            if key_name == "voltage":
                if not isinstance(attr.value, PhysVal) or get_unit_dimension(attr.value.unit) != "voltage":
                    self.diags.error("E311", attr.loc, f"Attribute 'voltage' requires a voltage unit")
            elif key_name == "max_current":
                if not isinstance(attr.value, PhysVal) or get_unit_dimension(attr.value.unit) != "current":
                    self.diags.error("E312", attr.loc, f"Attribute 'max_current' requires a current unit")
            elif key_name == "tolerance":
                if not isinstance(attr.value, PhysVal) or attr.value.unit != "%":
                    self.diags.error("E313", attr.loc, f"Attribute 'tolerance' requires unit '%'")

    def validate_module(self, module: ModuleDecl):
        """Validate a module declaration."""
        instances: Dict[str, InstanceDecl] = {}
        nets: Dict[str, NetDecl] = {}
        connects: List[ConnectStmt] = []
        blocks: Set[type] = set()

        for item in module.items:
            if isinstance(item, InstanceDecl):
                if item.ref_name in instances:
                    self.diags.error("E205", item.loc, f"Duplicate instance name '{item.ref_name}' in module '{module.name}'")
                elif item.ref_name in nets:
                    self.diags.error("E206", item.loc, f"Duplicate name '{item.ref_name}'; already used as a net")
                else:
                    instances[item.ref_name] = item
                
                if item.part_name not in self.parts:
                    self.diags.error("E210", item.loc, f"Unknown part '{item.part_name}'; no 'part' declaration found")
                else:
                    part_decl = self.parts[item.part_name]
                    part_attr_keys = {".".join(a.key.parts) for a in part_decl.attrs}
                    allowed_generic = {"value", "voltage_rating", "tolerance", "part_number"}
                    for override in item.overrides:
                        okey = ".".join(override.key.parts)
                        if okey not in part_attr_keys and okey not in allowed_generic:
                            self.diags.error("E215", override.loc, f"Instance override key '{okey}' not recognized for part '{item.part_name}'")
                        
                        if okey == "value" and isinstance(override.value, PhysVal):
                            if item.ref_name.startswith("C") and get_unit_dimension(override.value.unit) != "capacitance":
                                self.diags.warning("W030", override.loc, f"Cannot verify unit compatibility for instance override 'value' on part '{item.part_name}'; expected capacitance unit")
                            elif item.ref_name.startswith("R") and get_unit_dimension(override.value.unit) != "resistance":
                                self.diags.warning("W030", override.loc, f"Cannot verify unit compatibility for instance override 'value' on part '{item.part_name}'; expected resistance unit")

            elif isinstance(item, NetDecl):
                if item.name in nets:
                    self.diags.error("E206", item.loc, f"Duplicate net name '{item.name}' in module '{module.name}'")
                elif item.name in instances:
                    self.diags.error("E206", item.loc, f"Duplicate name '{item.name}'; already used as an instance")
                elif item.name in self.power_domains:
                    self.diags.error("E207", item.loc, f"Net name '{item.name}' shadows power domain of same name")
                else:
                    nets[item.name] = item

            elif isinstance(item, ConnectStmt):
                connects.append(item)

            elif isinstance(item, (ConstraintBlock, PlacementBlock, RoutingBlock, ValidateBlock, SimulateBlock)):
                if type(item) in blocks:
                    self.diags.error("E400", item.loc, f"Block '{item.__class__.__name__}' appears more than once in module '{module.name}'")
                blocks.add(type(item))

        if not connects:
            self.diags.warning("W010", module.loc, f"Module '{module.name}' has no connect statements")

        pin_to_net: Dict[Tuple[str, str], str] = {} 
        net_to_pins: Dict[str, List[Tuple[str, str, SourceLoc]]] = {} 
        
        def merge_nets(net1: str, net2: str):
            if net1 == net2: return net1
            pins2 = net_to_pins.pop(net2)
            for inst, pin, loc in pins2:
                pin_to_net[(inst, pin)] = net1
            if net1 not in net_to_pins: net_to_pins[net1] = []
            net_to_pins[net1].extend(pins2)
            return net1

        net_counter = 0
        def get_new_auto_net():
            nonlocal net_counter
            name = f"$auto_{net_counter}"
            net_counter += 1
            net_to_pins[name] = []
            return name

        for conn in connects:
            def resolve_endpoint(ep: Endpoint) -> Optional[str]:
                if isinstance(ep, PinRef):
                    if ep.instance not in instances:
                        self.diags.error("E211", ep.loc, f"Unknown instance '{ep.instance}'")
                        return None
                    inst_decl = instances[ep.instance]
                    if inst_decl.part_name in self.parts:
                        part_decl = self.parts[inst_decl.part_name]
                        pin_stmt = next((p for p in part_decl.pins if p.name == ep.pin), None)
                        if not pin_stmt:
                            self.diags.error("E212", ep.loc, f"Pin '{ep.pin}' does not exist on part '{part_decl.name}'")
                            return None
                        if pin_stmt.direction == "no_connect":
                            self.diags.error("E304", ep.loc, f"Pin '{ep.instance}.{ep.pin}' is no_connect")
                        
                        if (ep.instance, ep.pin) in pin_to_net:
                            return pin_to_net[(ep.instance, ep.pin)]
                        else:
                            net_id = get_new_auto_net()
                            pin_to_net[(ep.instance, ep.pin)] = net_id
                            net_to_pins[net_id].append((ep.instance, ep.pin, ep.loc))
                            return net_id
                    return None
                elif isinstance(ep, NetRef):
                    if ep.name not in nets:
                        self.diags.error("E214", ep.loc, f"Unknown net '{ep.name}'")
                        return None
                    if ep.name not in net_to_pins: net_to_pins[ep.name] = []
                    return ep.name
                elif isinstance(ep, PowerRef):
                    if ep.domain not in self.power_domains:
                        self.diags.error("E213", ep.loc, f"Unknown power domain '{ep.domain}'")
                        return None
                    name = f"$power_{ep.domain}"
                    if name not in net_to_pins: net_to_pins[name] = []
                    return name
                return None

            src_net = resolve_endpoint(conn.src)
            dst_net = resolve_endpoint(conn.dst)
            if src_net and dst_net:
                merge_nets(src_net, dst_net)

        left_pins = {}
        for conn in connects:
            if isinstance(conn.src, PinRef):
                key = (conn.src.instance, conn.src.pin)
                if key in left_pins:
                    self.diags.error("E220", conn.loc, f"Pin '{conn.src.instance}.{conn.src.pin}' connected multiple times")
                left_pins[key] = conn

        for net_id, pins in net_to_pins.items():
            if not pins: continue
            pin_infos = []
            for inst, pin, loc in pins:
                inst_decl = instances[inst]
                part_decl = self.parts[inst_decl.part_name]
                pin_stmt = next(p for p in part_decl.pins if p.name == pin)
                pin_infos.append((inst, pin, loc, pin_stmt.direction))
            
            is_power_net = net_id.startswith("$power_")
            for inst, pin, loc, direction in pin_infos:
                if direction == "power_in" and not is_power_net:
                    self.diags.error("E300", loc, f"Pin '{inst}.{pin}' (power_in) on signal net")
                if direction == "power_gnd":
                    if not is_power_net:
                        self.diags.error("E300", loc, f"Pin '{inst}.{pin}' (power_gnd) on signal net")
                    else:
                        domain = self.power_domains[net_id[len("$power_"):]]
                        voltage_attr = next((a for a in domain.attrs if ".".join(a.key.parts) == "voltage"), None)
                        type_attr = next((a for a in domain.attrs if ".".join(a.key.parts) == "type"), None)
                        is_ok = (type_attr and isinstance(type_attr.value, StringVal) and type_attr.value.value == "reference") or \
                                (voltage_attr and isinstance(voltage_attr.value, PhysVal) and voltage_attr.value.number == 0.0)
                        if not is_ok:
                            self.diags.error("E301", loc, f"Pin '{inst}.{pin}' (power_gnd) on non-zero domain")

            if len([d for _,_,_,d in pin_infos if d == "power_out"]) > 1:
                self.diags.error("E302", pins[0][2], f"Net '{net_id}' has multiple power_out")
            if len([d for _,_,_,d in pin_infos if d == "output"]) > 1:
                self.diags.error("E303", pins[0][2], f"Net '{net_id}' has multiple output")

        for inst_name, inst_decl in instances.items():
            if inst_decl.part_name in self.parts:
                part_decl = self.parts[inst_decl.part_name]
                for pin in part_decl.pins:
                    if pin.direction == "power_in" and (inst_name, pin.name) not in pin_to_net:
                        self.diags.warning("W021", inst_decl.loc, f"Pin '{inst_name}.{pin.name}' (power_in) is not connected")

        self.validate_attr_ranges(module.items)

    def validate_attr_ranges(self, items: List[ModuleItem]):
        for item in items:
            attrs = getattr(item, 'attrs', getattr(item, 'overrides', []))
            if attrs is None: attrs = []
            for attr in attrs:
                if isinstance(attr.value, RangeVal):
                    if get_unit_dimension(attr.value.low.unit) != get_unit_dimension(attr.value.high.unit):
                        self.diags.error("E310", attr.value.loc, f"Range units mismatch")

    def validate_target(self, target: TargetDecl):
        pass
