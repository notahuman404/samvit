#!/usr/bin/env python3
"""
Module: compatibility_checker
Description: A deterministic, rule-based hardware-design compatibility checker 
             acting as a validator/linter for autonomous hardware pipelines.
Language: Python 3.11+ (Strictly typed, zero external dependencies)
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
import json
from typing import Any, Dict, List, Set, Tuple, Optional


# ==========================================
# 1. ENUMS & CORE DATA MODELS
# ==========================================

class PinType(str, Enum):
    POWER_IN = "POWER_IN"
    POWER_OUT = "POWER_OUT"
    DIGITAL_IN = "DIGITAL_IN"
    DIGITAL_OUT = "DIGITAL_OUT"
    DIGITAL_BIDI = "DIGITAL_BIDI"
    ANALOG_IN = "ANALOG_IN"
    ANALOG_OUT = "ANALOG_OUT"
    PASSIVE = "PASSIVE"


class InterfaceType(str, Enum):
    I2C = "I2C"
    SPI = "SPI"
    UART = "UART"
    GPIO = "GPIO"
    PWM = "PWM"
    POWER = "POWER"
    PASSIVE = "PASSIVE"


@dataclass(frozen=True)
class PinSpec:
    name: str
    type: PinType
    voltage_min: float = 0.0   # Minimum acceptable operating voltage (V)
    voltage_max: float = 0.0   # Maximum acceptable voltage / Nominal Output voltage (V)
    current_max: float = 0.0   # Max output capacity (A) for OUT pins, or absolute limit for IN pins
    current_draw: float = 0.0  # Constant or peak current consumption (A) under load


@dataclass(frozen=True)
class InterfaceSpec:
    name: str
    type: InterfaceType
    pins: List[str]  # List of pin names belonging to this interface group


@dataclass(frozen=True)
class ComponentSpec:
    part_number: str
    category: str        # e.g., "MCU", "REGULATOR", "MOTOR", "SENSOR", "CAPACITOR"
    description: str
    pins: Dict[str, PinSpec]
    interfaces: List[InterfaceSpec] = field(default_factory=list)
    footprint: Optional[str] = None
    package: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)  # Categories that must coexist in design


@dataclass(frozen=True)
class SelectedPart:
    designator: str   # Unique identifier in design (e.g., "U1", "M1", "C1")
    part_number: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Connection:
    from_part: str
    from_pin: str
    to_part: str
    to_pin: str


@dataclass(frozen=True)
class ArchitectureSpec:
    components: Dict[str, SelectedPart]
    connections: List[Connection]


# ==========================================
# 2. OUTPUT & DIAGNOSTIC REPORT MODELS
# ==========================================

@dataclass
class CompatibilityIssue:
    code: str
    severity: str  # "ERROR" or "WARNING"
    message: str
    source: str = "compatibility_checker"
    objects: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CompatibilityReport:
    is_valid: bool
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    component_diagnostics: Dict[str, Dict[str, List[str]]]
    connection_diagnostics: List[Dict[str, Any]]
    summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "component_diagnostics": self.component_diagnostics,
            "connection_diagnostics": self.connection_diagnostics,
            "summary": self.summary
        }


# ==========================================
# 3. GRAPH GRAPH & NETLIST ANALYSIS CONTEXT
# ==========================================

class ValidationContext:
    """Compiles the flat connections list into continuous electrical nets and lookups."""
    
    def __init__(self, spec: ArchitectureSpec, database: Dict[str, ComponentSpec]):
        self.spec = spec
        self.database = database
        self.nets: List[Set[Tuple[str, str]]] = []
        self.pin_to_net_idx: Dict[Tuple[str, str], int] = {}
        self._build_electrical_nets()

    def _build_electrical_nets(self) -> None:
        adj: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}
        all_pins: Set[Tuple[str, str]] = set()

        # Seed all physical pins declared by known selected components
        for des, part in self.spec.components.items():
            comp_spec = self.database.get(part.part_number)
            if comp_spec:
                for pin_name in comp_spec.pins:
                    all_pins.add((des, pin_name))

        # Build bidirectional adjacency map from explicit connection paths
        for conn in self.spec.connections:
            p1 = (conn.from_part, conn.from_pin)
            p2 = (conn.to_part, conn.to_pin)
            all_pins.add(p1)
            all_pins.add(p2)
            adj.setdefault(p1, []).append(p2)
            adj.setdefault(p2, []).append(p1)

        # Trace unified continuous net tracks using Breadth-First Search (BFS)
        visited: Set[Tuple[str, str]] = set()
        for pin in all_pins:
            if pin not in visited:
                current_net: Set[Tuple[str, str]] = set()
                queue = [pin]
                while queue:
                    curr = queue.pop(0)
                    if curr not in visited:
                        visited.add(curr)
                        current_net.add(curr)
                        for neighbor in adj.get(curr, []):
                            if neighbor not in visited:
                                queue.append(neighbor)
                if current_net:
                    net_idx = len(self.nets)
                    self.nets.append(current_net)
                    for np in current_net:
                        self.pin_to_net_idx[np] = net_idx

    def get_pin_spec(self, designator: str, pin_name: str) -> Optional[PinSpec]:
        part = self.spec.components.get(designator)
        if not part:
            return None
        comp_spec = self.database.get(part.part_number)
        return comp_spec.pins.get(pin_name) if comp_spec else None

    def get_component_spec(self, designator: str) -> Optional[ComponentSpec]:
        part = self.spec.components.get(designator)
        return self.database.get(part.part_number) if part else None


# ==========================================
# 4. MODULAR DETERMINISTIC VALIDATION RULES
# ==========================================

class BaseValidationRule:
    """Abstract Base Class for hardware pipeline evaluation validation checks."""
    def validate(self, ctx: ValidationContext) -> Tuple[List[CompatibilityIssue], List[CompatibilityIssue]]:
        raise NotImplementedError


class MetadataValidationRule(BaseValidationRule):
    """Verifies existence of physical packaging and CAD layout footprint definitions."""
    def validate(self, ctx: ValidationContext) -> Tuple[List[CompatibilityIssue], List[CompatibilityIssue]]:
        errors, warnings = [], []
        for des, part in ctx.spec.components.items():
            comp = ctx.database.get(part.part_number)
            if not comp:
                continue
            if not comp.footprint:
                errors.append(CompatibilityIssue(
                    code="MISSING_FOOTPRINT",
                    severity="ERROR",
                    message=f"Component '{des}' ({part.part_number}) lacks physical PCB footprint footprint data assignment.",
                    objects=[des]
                ))
            if not comp.package:
                warnings.append(CompatibilityIssue(
                    code="MISSING_PACKAGE",
                    severity="WARNING",
                    message=f"Component '{des}' ({part.part_number}) lacks structural package specification.",
                    objects=[des]
                ))
        return errors, warnings


class VoltageAndShortCircuitRule(BaseValidationRule):
    """Validates voltage compatibility domains and catches physical short-circuit rails."""
    def validate(self, ctx: ValidationContext) -> Tuple[List[CompatibilityIssue], List[CompatibilityIssue]]:
        errors, warnings = [], []
        
        for idx, net in enumerate(ctx.nets):
            drivers: List[Tuple[str, str, PinSpec]] = []
            receivers: List[Tuple[str, str, PinSpec]] = []
            
            for des, pin_name in net:
                pspec = ctx.get_pin_spec(des, pin_name)
                if not pspec:
                    continue
                if pspec.type in (PinType.POWER_OUT, PinType.DIGITAL_OUT, PinType.ANALOG_OUT):
                    drivers.append((des, pin_name, pspec))
                if pspec.type in (PinType.POWER_IN, PinType.DIGITAL_IN, PinType.ANALOG_IN):
                    receivers.append((des, pin_name, pspec))
            
            # Check 1: Conflicting electrical driving sources (Short Circuit / Rail Contention)
            if len(drivers) > 1:
                base_des, base_pin, base_spec = drivers[0]
                for d_des, d_pin, d_spec in drivers[1:]:
                    if base_spec.voltage_max != d_spec.voltage_max:
                        errors.append(CompatibilityIssue(
                            code="SHORT_CIRCUIT_HAZARD",
                            severity="ERROR",
                            message=f"Short circuit hazard on Net {idx}: Active driving outputs fighting on single rail. "
                                    f"Source {base_des}.{base_pin} ({base_spec.voltage_max}V) conflicts with "
                                    f"{d_des}.{d_pin} ({d_spec.voltage_max}V).",
                            objects=[base_des, d_des]
                        ))
            
            # Check 2: Single or multi driver voltage domain matches target inputs
            for d_des, d_pin, d_spec in drivers:
                v_out = d_spec.voltage_max  # Treat output max rating as its driven nominal voltage
                for r_des, r_pin, r_spec in receivers:
                    if v_out < r_spec.voltage_min or v_out > r_spec.voltage_max:
                        errors.append(CompatibilityIssue(
                            code="VOLTAGE_MISMATCH",
                            severity="ERROR",
                            message=f"Voltage domain breach on Net {idx}: Driver {d_des}.{d_pin} supplies {v_out}V, "
                                    f"violating input spec constraint [{r_spec.voltage_min}V - {r_spec.voltage_max}V] "
                                    f"for receiver pin {r_des}.{r_pin}.",
                            objects=[d_des, r_des]
                        ))
        return errors, warnings


class PowerRailOversubscriptionRule(BaseValidationRule):
    """Calculates cumulative downstream power consumption against sourcing regulator thresholds."""
    def validate(self, ctx: ValidationContext) -> Tuple[List[CompatibilityIssue], List[CompatibilityIssue]]:
        errors, warnings = [], []
        
        for idx, net in enumerate(ctx.nets):
            power_sources: List[Tuple[str, str, PinSpec]] = []
            power_sinks: List[Tuple[str, str, PinSpec]] = []
            
            for des, pin_name in net:
                pspec = ctx.get_pin_spec(des, pin_name)
                if not pspec:
                    continue
                if pspec.type == PinType.POWER_OUT:
                    power_sources.append((des, pin_name, pspec))
                elif pspec.type == PinType.POWER_IN:
                    power_sinks.append((des, pin_name, pspec))
            
            if power_sources:
                total_sourcing_capacity = sum(p[2].current_max for p in power_sources)
                total_sinking_drain = sum(p[2].current_draw for p in power_sinks)
                
                if total_sinking_drain > total_sourcing_capacity:
                    affected_nodes = list({p[0] for p in power_sources} | {p[0] for p in power_sinks})
                    errors.append(CompatibilityIssue(
                        code="OVERSUBSCRIBED_RAIL",
                        severity="ERROR",
                        message=f"Power capacity oversubscription on Net {idx}: Combined load draw demand ({total_sinking_drain}A) "
                                f"exceeds total rail sourcing regulator capabilities ({total_sourcing_capacity}A).",
                        objects=affected_nodes
                    ))
        return errors, warnings


class DriverStageAndLoadValidationRule(BaseValidationRule):
    """Enforces missing driver stage isolation logic (e.g., prevents low-power GPIO driving high-load inductive motors)."""
    def validate(self, ctx: ValidationContext) -> Tuple[List[CompatibilityIssue], List[CompatibilityIssue]]:
        errors, warnings = [], []
        
        for idx, net in enumerate(ctx.nets):
            control_outputs: List[Tuple[str, str, PinSpec]] = []
            heavy_loads: List[Tuple[str, str, PinSpec, ComponentSpec]] = []
            
            for des, pin_name in net:
                pspec = ctx.get_pin_spec(des, pin_name)
                comp_spec = ctx.get_component_spec(des)
                if not pspec or not comp_spec:
                    continue
                
                if pspec.type == PinType.DIGITAL_OUT:
                    control_outputs.append((des, pin_name, pspec))
                
                # Flag structural inductive/resistive high loads or power sinks exceeding low control logic ceilings
                if comp_spec.category in ("MOTOR", "ACTUATOR", "HEATER") or pspec.current_draw > 0.04:
                    if pspec.type in (PinType.DIGITAL_IN, PinType.ANALOG_IN, PinType.PASSIVE, PinType.POWER_IN):
                        heavy_loads.append((des, pin_name, pspec, comp_spec))
            
            if control_outputs and heavy_loads:
                for ctrl_des, ctrl_pin, ctrl_spec in control_outputs:
                    for load_des, load_pin, load_spec, load_comp in heavy_loads:
                        # Standard raw GPIO pins generally cannot source/sink high currents safely (threshold: 20mA)
                        if ctrl_spec.current_max <= 0.02 and (load_spec.current_draw > 0.02 or load_comp.category == "MOTOR"):
                            errors.append(CompatibilityIssue(
                                code="MISSING_DRIVER_STAGE",
                                severity="ERROR",
                                message=f"Invalid direct load connection on Net {idx}: Low-power control logic pin "
                                        f"{ctrl_des}.{ctrl_pin} (Source max: {ctrl_spec.current_max}A) connected directly "
                                        f"to high-load category '{load_comp.category}' component '{load_des}' drawing "
                                        f"{load_spec.current_draw}A without an isolation driver/FET stage.",
                                objects=[ctrl_des, load_des]
                            ))
        return errors, warnings


class InterfaceCompatibilityRule(BaseValidationRule):
    """Checks interface bus protocol safety bounds and flags general disconnected cross-domain structural pin mismatches."""
    def validate(self, ctx: ValidationContext) -> Tuple[List[CompatibilityIssue], List[CompatibilityIssue]]:
        errors, warnings = [], []
        
        for conn in ctx.spec.connections:
            from_comp = ctx.get_component_spec(conn.from_part)
            to_comp = ctx.get_component_spec(conn.to_part)
            if not from_comp or not to_comp:
                continue
            
            from_iface: Optional[InterfaceSpec] = None
            for iface in from_comp.interfaces:
                if conn.from_pin in iface.pins:
                    from_iface = iface
                    break
            
            to_iface: Optional[InterfaceSpec] = None
            for iface in to_comp.interfaces:
                if conn.to_pin in iface.pins:
                    to_iface = iface
                    break
            
            # Check 1: Bus structural mismatches (e.g., trying to route I2C directly to SPI lines)
            if from_iface and to_iface:
                if from_iface.type != to_iface.type:
                    errors.append(CompatibilityIssue(
                        code="INTERFACE_MISMATCH",
                        severity="ERROR",
                        message=f"Unsupported interface cross-connection: Interfacing cross-protocol bus frameworks. "
                                f"Mapped standard {conn.from_part}.{conn.from_pin} ({from_iface.type.value}) directly "
                                f"into target bus network {conn.to_part}.{conn.to_pin} ({to_iface.type.value}).",
                        objects=[conn.from_part, conn.to_part]
                    ))
            
            # Check 2: Broad structural pin function conflicts (e.g., tying active analog signals directly to strict digital inputs)
            p1_spec = ctx.get_pin_spec(conn.from_part, conn.from_pin)
            p2_spec = ctx.get_pin_spec(conn.to_part, conn.to_pin)
            if p1_spec and p2_spec:
                if (p1_spec.type == PinType.DIGITAL_OUT and p2_spec.type == PinType.ANALOG_IN) or \
                   (p1_spec.type == PinType.ANALOG_OUT and p2_spec.type == PinType.DIGITAL_IN):
                    warnings.append(CompatibilityIssue(
                        code="PIN_TYPE_MISMATCH",
                        severity="WARNING",
                        message=f"Suspicious schematic linkage: Signal source type {p1_spec.type.value} on "
                                f"{conn.from_part}.{conn.from_pin} routed directly into receiver type "
                                f"{p2_spec.type.value} on {conn.to_part}.{conn.to_pin}.",
                        objects=[conn.from_part, conn.to_part]
                    ))
        return errors, warnings


class ComponentDependencyRule(BaseValidationRule):
    """Enforces subsystem structural prerequisites (e.g., MCUs requiring decoupling capacitors or board-level regulators)."""
    def validate(self, ctx: ValidationContext) -> Tuple[List[CompatibilityIssue], List[CompatibilityIssue]]:
        errors, warnings = [], []
        
        # Aggregate all present functional blocks mapped within current architectural design
        active_categories = {c.category for part in ctx.spec.components.values() if (c := ctx.database.get(part.part_number))}
        
        for des, part in ctx.spec.components.items():
            comp_spec = ctx.database.get(part.part_number)
            if not comp_spec:
                continue
            for mandatory_dep in comp_spec.dependencies:
                if mandatory_dep not in active_categories:
                    errors.append(CompatibilityIssue(
                        code="MISSING_DEPENDENCY",
                        severity="ERROR",
                        message=f"Integration rule failure on '{des}' ({part.part_number}): Missing structural pipeline dependency. "
                                f"This component requires the instantiation of at least one '{mandatory_dep}' category block inside the model.",
                        objects=[des]
                    ))
        return errors, warnings


# ==========================================
# 5. CORE PIPELINE CONTROLLER ENTRIES
# ==========================================

def check_compatibility(spec: ArchitectureSpec, database: Dict[str, ComponentSpec]) -> CompatibilityReport:
    """
    Main entry point for evaluating top-level schematic and components topologies configurations.
    Executes a deterministic series of validation lint rules returning machine-readable results.
    """
    errors: List[CompatibilityIssue] = []
    warnings: List[CompatibilityIssue] = []
    
    # 1. Structural Pre-flight validation - Check database registration bounds
    for des, part in spec.components.items():
        if part.part_number not in database:
            errors.append(CompatibilityIssue(
                code="UNRESOLVED_PART_SPEC",
                severity="ERROR",
                message=f"Part catalog lookup fault on designator '{des}': Target identifier '{part.part_number}' "
                        f"is missing from global hardware definition library mappings.",
                objects=[des]
            ))
            
    # 2. Compile spatial connectivity mapping
    ctx = ValidationContext(spec, database)
    
    # 3. Instantiate rule runners pipeline
    rules_pipeline: List[BaseValidationRule] = [
        MetadataValidationRule(),
        VoltageAndShortCircuitRule(),
        PowerRailOversubscriptionRule(),
        DriverStageAndLoadValidationRule(),
        InterfaceCompatibilityRule(),
        ComponentDependencyRule()
    ]
    
    # 4. Sequential execution of rules
    for rule in rules_pipeline:
        rule_errors, rule_warnings = rule.validate(ctx)
        errors.extend(rule_errors)
        warnings.extend(rule_warnings)
        
    is_valid_design = len(errors) == 0
    
    # 5. Build localized diagnostics tracking summaries
    comp_diagnostics: Dict[str, Dict[str, List[str]]] = {des: {"errors": [], "warnings": []} for des in spec.components}
    for err in errors:
        for obj in err.objects:
            if obj in comp_diagnostics:
                comp_diagnostics[obj]["errors"].append(err.message)
    for wrn in warnings:
        for obj in wrn.objects:
            if obj in comp_diagnostics:
                comp_diagnostics[obj]["warnings"].append(wrn.message)
                
    conn_diagnostics: List[Dict[str, Any]] = []
    for conn in spec.connections:
        conn_str = f"{conn.from_part}.{conn.from_pin} -> {conn.to_part}.{conn.to_pin}"
        conn_faults = [e.message for e in errors if conn.from_part in e.objects and conn.to_part in e.objects]
        conn_warns = [w.message for w in warnings if conn.from_part in w.objects and conn.to_part in w.objects]
        
        status = "PASS"
        if conn_faults:
            status = "FAIL"
        elif conn_warns:
            status = "WARNING"
            
        conn_diagnostics.append({
            "connection": conn_str,
            "status": status,
            "issues": conn_faults + conn_warns
        })
        
    compiled_summary = {
        "checked_components": len(spec.components),
        "checked_connections": len(spec.connections),
        "error_count": len(errors),
        "warning_count": len(warnings)
    }
    
    return CompatibilityReport(
        is_valid=is_valid_design,
        errors=[e.to_dict() for e in errors],
        warnings=[w.to_dict() for w in warnings],
        component_diagnostics=comp_diagnostics,
        connection_diagnostics=conn_diagnostics,
        summary=compiled_summary
    )


# ==========================================
# 6. SYSTEM COMPONENT REFERENCE DICTIONARY (MOCK DATABASE)
# ==========================================

def get_mock_component_database() -> Dict[str, ComponentSpec]:
    """Generates standard library items for hardware testing validation targets."""
    return {
        "MCU-STM32-48": ComponentSpec(
            part_number="MCU-STM32-48",
            category="MCU",
            description="Ultra-low power 3.3V microcontroller module",
            footprint="LQFP-48",
            package="LQFP",
            dependencies=["CAPACITOR"],
            pins={
                "VDD": PinSpec(name="VDD", type=PinType.POWER_IN, voltage_min=3.0, voltage_max=3.6),
                "GND": PinSpec(name="GND", type=PinType.POWER_IN, voltage_min=0.0, voltage_max=0.0),
                "PA0_I2C_SCL": PinSpec(name="PA0_I2C_SCL", type=PinType.DIGITAL_BIDI, voltage_min=0.0, voltage_max=3.3),
                "PA1_I2C_SDA": PinSpec(name="PA1_I2C_SDA", type=PinType.DIGITAL_BIDI, voltage_min=0.0, voltage_max=3.3),
                "PC0_GPIO": PinSpec(name="PC0_GPIO", type=PinType.DIGITAL_OUT, voltage_min=0.0, voltage_max=3.3, current_max=0.015),
            },
            interfaces=[
                InterfaceSpec(name="I2C1", type=InterfaceType.I2C, pins=["PA0_I2C_SCL", "PA1_I2C_SDA"]),
                InterfaceSpec(name="GPIO0", type=InterfaceType.GPIO, pins=["PC0_GPIO"])
            ]
        ),
        "REG-AMS1117-33": ComponentSpec(
            part_number="REG-AMS1117-33",
            category="REGULATOR",
            description="Linear Dropout Regulator 5V to 3.3V output step down",
            footprint="SOT-223",
            package="SOT",
            pins={
                "VIN": PinSpec(name="VIN", type=PinType.POWER_IN, voltage_min=4.5, voltage_max=12.0),
                "VOUT": PinSpec(name="VOUT", type=PinType.POWER_OUT, voltage_min=3.25, voltage_max=3.35, current_max=0.100),  # Max current restricted to 100mA for test triggers
                "GND": PinSpec(name="GND", type=PinType.POWER_IN, voltage_min=0.0, voltage_max=0.0)
            }
        ),
        "SENSOR-I2C-5V": ComponentSpec(
            part_number="SENSOR-I2C-5V",
            category="SENSOR",
            description="High-precision digital barometer sensor tracking module running at strict 5V thresholds",
            footprint="DFN-8",
            package="DFN",
            pins={
                "VCC": PinSpec(name="VCC", type=PinType.POWER_IN, voltage_min=4.75, voltage_max=5.25, current_draw=0.010),
                "SCL": PinSpec(name="SCL", type=PinType.DIGITAL_IN, voltage_min=4.75, voltage_max=5.25),
                "SDA": PinSpec(name="SDA", type=PinType.DIGITAL_BIDI, voltage_min=4.75, voltage_max=5.25)
            },
            interfaces=[
                InterfaceSpec(name="SPI_COMM_FAIL", type=InterfaceType.SPI, pins=["SCL", "SDA"]) # Malformed specification intended to break bus checks
            ]
        ),
        "DC-MOTOR-12V": ComponentSpec(
            part_number="DC-MOTOR-12V",
            category="MOTOR",
            description="Brushed DC motor driver stage load",
            footprint="TERM-BLOCK-2",
            package=None, # Intentional Warning Trigger: Missing package field data
            pins={
                "PWR": PinSpec(name="PWR", type=PinType.POWER_IN, voltage_min=11.0, voltage_max=13.0, current_draw=0.800),
                "CTRL": PinSpec(name="CTRL", type=PinType.DIGITAL_IN, voltage_min=3.0, voltage_max=5.5, current_draw=0.080) # Sinks high control currents
            }
        ),
        "CAP-0603-10UF": ComponentSpec(
            part_number="CAP-0603-10UF",
            category="CAPACITOR",
            description="Ceramic Decoupling Capacitor",
            footprint="C0603",
            package="0603",
            pins={
                "1": PinSpec(name="1", type=PinType.PASSIVE),
                "2": PinSpec(name="2", type=PinType.PASSIVE)
            }
        )
    }


# ==========================================
# 7. AUTOMATED EVALUATION & COMPILER TESTS SUITE
# ==========================================

def run_pipeline_self_test() -> None:
    """Executes a diagnostic pass/fail loop over sample valid and invalid architecture topologies."""
    db = get_mock_component_database()
    
    print("-" * 80)
    print("RUNNING HARDWARE PIPELINE COMPATIBILITY CHECKER - SYSTEM VALIDATION")
    print("-" * 80)
    
    # -------------------------------------------------------------
    # CASE A: MALFORMED SPEC (Deliberately triggering all validations)
    # -------------------------------------------------------------
    invalid_components = {
        "U1": SelectedPart(designator="U1", part_number="MCU-STM32-48"),
        "U2": SelectedPart(designator="U2", part_number="REG-AMS1117-33"),
        "U3": SelectedPart(designator="U3", part_number="SENSOR-I2C-5V"),
        "M1": SelectedPart(designator="M1", part_number="DC-MOTOR-12V")
        # Missing Capacitor instantiation breaks U1's dependency rule
    }
    
    invalid_connections = [
        # 1. Voltage mismatch: Regulator 3.3V driving strict 5V Sensor VCC
        Connection(from_part="U2", from_pin="VOUT", to_part="U3", to_pin="VCC"),
        
        # 2. Power rail oversubscription: Motor drawing 0.8A from a 100mA regulator rail
        Connection(from_part="U2", from_pin="VOUT", to_part="M1", to_pin="PWR"),
        
        # 3. Missing isolation stage: Low power GPIO (max 15mA) driving motor input directly (drawing 80mA)
        Connection(from_part="U1", from_pin="PC0_GPIO", to_part="M1", to_pin="CTRL"),
        
        # 4. Interface mismatch rule: Microcontroller I2C interface routed straight into Sensor mismatched SPI block pins
        Connection(from_part="U1", from_pin="PA0_I2C_SCL", to_part="U3", to_pin="SCL"),
        Connection(from_part="U1", from_pin="PA1_I2C_SDA", to_part="U3", to_pin="SDA")
    ]
    
    invalid_architecture = ArchitectureSpec(components=invalid_components, connections=invalid_connections)
    
    print("\n[TEST 1] EVALUATING MALFORMED/INVALID HARDWARE PLATFORM SPEC...")
    bad_report = check_compatibility(invalid_architecture, db)
    
    print(f"Overall Compilation Status: {'PASS' if bad_report.is_valid else 'FAIL'}")
    print(f"Total Errors Intercepted: {bad_report.summary['error_count']}")
    print(f"Total Warnings Flagged:  {bad_report.summary['warning_count']}")
    print("\nCaptured Structured Error JSON Extract Payload:")
    print(json.dumps(bad_report.to_dict()["errors"][:3], indent=2))  # Displaying a sample cut of top items
    
    # Assert sanity constraints are caught explicitly
    error_codes = {err["code"] for err in bad_report.errors}
    warning_codes = {wrn["code"] for wrn in bad_report.warnings}
    
    assert "MISSING_DEPENDENCY" in error_codes, "Fail: Should catch missing bypass cap framework dependency."
    assert "VOLTAGE_MISMATCH" in error_codes, "Fail: Should verify 3.3V vs 5V supply boundary failures."
    assert "OVERSUBSCRIBED_RAIL" in error_codes, "Fail: Should detect power rail limits overdraw."
    assert "MISSING_DRIVER_STAGE" in error_codes, "Fail: Should identify high current raw control pin loops."
    assert "INTERFACE_MISMATCH" in error_codes, "Fail: Bus framework alignment rule failed."
    assert "MISSING_PACKAGE" in warning_codes, "Fail: Missing package structural metadata failed to notice."
    
    print("\n✔ Test 1 Successfully Caught All Targeted Hardware Violations.")
    
    # -------------------------------------------------------------
    # CASE B: NOMINAL INTEGRITY SPEC (100% Cleared Passing Platform)
    # -------------------------------------------------------------
    # Create healthy individual specific modules for nominal tracking
    db_clean = {
        "MCU-SAFE": ComponentSpec(
            part_number="MCU-SAFE", category="MCU", description="Clean Core", footprint="QFP", package="QFP",
            pins={
                "VDD": PinSpec(name="VDD", type=PinType.POWER_IN, voltage_min=3.0, voltage_max=3.6),
                "SIG_OUT": PinSpec(name="SIG_OUT", type=PinType.DIGITAL_OUT, voltage_min=0.0, voltage_max=3.3, current_max=0.015)
            }
        ),
        "REG-SAFE": ComponentSpec(
            part_number="REG-SAFE", category="REGULATOR", description="Clean Power Sourcing Supply Line", footprint="SOT", package="SOT",
            pins={
                "VOUT": PinSpec(name="VOUT", type=PinType.POWER_OUT, voltage_min=3.3, voltage_max=3.3, current_max=2.0)
            }
        ),
        "DRIVER-STAGE": ComponentSpec(
            part_number="DRIVER-STAGE", category="ACTUATOR", description="Isolation Stage Field Effect Transistor", footprint="SOIC", package="SOIC",
            pins={
                "GATE_IN": PinSpec(name="GATE_IN", type=PinType.DIGITAL_IN, voltage_min=2.5, voltage_max=5.0, current_draw=0.001), # Safe load draw profile
                "DRV_OUT": PinSpec(name="DRV_OUT", type=PinType.POWER_OUT, voltage_min=12.0, voltage_max=12.0, current_max=5.0)
            }
        )
    }
    
    valid_components = {
        "U1": SelectedPart(designator="U1", part_number="MCU-SAFE"),
        "U2": SelectedPart(designator="U2", part_number="REG-SAFE"),
        "Q1": SelectedPart(designator="Q1", part_number="DRIVER-STAGE")
    }
    
    valid_connections = [
        Connection(from_part="U2", from_pin="VOUT", to_part="U1", to_pin="VDD"),       # 3.3V Regulator driving 3.3V MCU VDD
        Connection(from_part="U1", from_pin="SIG_OUT", to_part="Q1", to_pin="GATE_IN") # Control signal hitting low draw isolation driver stage input
    ]
    
    valid_architecture = ArchitectureSpec(components=valid_components, connections=valid_connections)
    
    print("\n" + "-" * 40)
    print("[TEST 2] EVALUATING NOMINAL SANITIZED VALID ARCHITECTURE INTERFACES...")
    good_report = check_compatibility(valid_architecture, db_clean)
    
    print(f"Overall Compilation Status: {'PASS' if good_report.is_valid else 'FAIL'}")
    print(f"Total Errors Intercepted: {good_report.summary['error_count']}")
    print(f"Total Warnings Flagged:  {good_report.summary['warning_count']}")
    
    assert good_report.is_valid is True, "Fail: Clean architecture mapping should evaluate as a 100% valid setup."
    print("\n✔ Test 2 Successfully Cleared Verification Engineering Baseline Check Constraints.")
    print("-" * 80)
    print("COMPATIBILITY ENGINE SELF-TEST COMPLETELY PASSED WITH SCRIPT EXECUTIONS VERIFIED.")
    print("-" * 80)


if __name__ == "__main__":
    run_pipeline_self_test()