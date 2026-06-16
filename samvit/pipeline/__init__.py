"""
All 30 pipeline stages for the autonomous hardware design system.

Import order reflects data dependencies, not execution order
(the orchestrator controls execution).
"""
from samvit.pipeline import (
    p01_requirements,
    p03_architecture,
    p05_datasheet,
    p06_component_db,
    p07_component_search,
    p08_part_selection,
    p09_compatibility,
    p10_schematic_graph,
    p11_schematic_gen,
    p12_footprint,
    p13_placement,
    p14_routing,
    p15_rules,
    p16_erc,
    p17_drc,
    p18_power,
    p19_thermal,
    p20_short_circuit,
    p21_simulation,
    p22_test_gen,
    p23_metrics,
    p24_reviewer,
    p25_repair,
    p26_kicad,
    p27_exporter,
    p28_logging,
    p29_visualizer,
    p30_human_override,
)

__all__ = [
    "p01_requirements", "p03_architecture", "p05_datasheet",
    "p06_component_db", "p07_component_search", "p08_part_selection",
    "p09_compatibility", "p10_schematic_graph", "p11_schematic_gen",
    "p12_footprint", "p13_placement", "p14_routing", "p15_rules",
    "p16_erc", "p17_drc", "p18_power", "p19_thermal", "p20_short_circuit",
    "p21_simulation", "p22_test_gen", "p23_metrics",
    "p24_reviewer", "p25_repair",
    "p26_kicad", "p27_exporter", "p28_logging",
    "p29_visualizer", "p30_human_override",
]
