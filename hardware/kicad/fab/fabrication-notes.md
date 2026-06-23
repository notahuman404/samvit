# Fabrication Notes — Motor Driver 16-Channel Board

## Board Identification

| Field | Value |
|---|---|
| Board name | Haptic Vest 16-Ch Motor Driver |
| File | `motor-driver-16ch.kicad_pcb` |
| Revision | 1.0 |
| Date | 2026-06-18 |
| Dimensions | 100.0 mm × 70.0 mm |
| Board count (prototype run) | 9 (one per PCA9685 group) |

---

## JLC PCB Order Form — Fill These In Exactly

Navigate to jlcpcb.com → Quote Now → upload the Gerber ZIP from `fab/gerbers/`.

| Parameter | Value | Notes |
|---|---|---|
| **Base Material** | FR-4 | Standard |
| **Layers** | 2 | F.Cu + B.Cu |
| **Dimensions** | 100 mm × 70 mm | Auto-detected from Gerber |
| **PCB Qty** | 10 (minimum order) | Order 10, use 9 |
| **Different Design** | 1 | |
| **Delivery Format** | Single PCB | |
| **PCB Thickness** | 1.6 mm | Standard |
| **PCB Color** | Black | Better contrast for silkscreen labels |
| **Silkscreen** | White | |
| **Surface Finish** | HASL (with lead)  | Cheapest; ENIG (+$5) if preferred for fine-pitch TSSOP-28 pads |
| **Outer Copper Weight** | 1 oz | Standard |
| **Via Covering** | Tented | |
| **Board Outline Tolerance** | ±0.2 mm | |
| **Confirm Production File** | Yes | Review before production |
| **Remove Order Number** | Yes (+$1.50) | Avoids silkscreen number on board |
| **Flying Probe Test** | Yes (included) | |
| **Gold Fingers** | No | |
| **Castellated Holes** | No | |
| **Edge Plating** | No | |

**Recommended finish for TSSOP-28 at 0.65mm pitch:** ENIG (Electroless Nickel Immersion Gold) gives flat, solderable pads that are much easier to hand-solder than HASL which leaves uneven bumps. The $5 upcharge per board is worth it for the 9 boards needed.

---

## JLC SMT Assembly (Optional — Saves Manual Soldering)

If ordering SMT assembly for the SMD components (strongly recommended for the 0402 resistors/caps and SOD-323 diodes):

1. Upload `fab/gerbers/` ZIP as before
2. Enable "SMT Assembly" toggle
3. Upload `fab/bom-jlc.csv` (JLC-format BOM with LCSC part numbers)
4. Upload `fab/motor-driver-16ch-cpl.csv` (component placement list)
5. Select "Top Side" assembly only (all SMD components are on F.Cu)

**Components to assemble via JLC SMT:**
- U1: PCA9685PW (LCSC: C9067 or search "PCA9685")
- Q1–Q16: AO3400A (LCSC: C20917)
- R1–R16: 220Ω 0402 (LCSC: C25091)
- D1–D16: 1N4148WS SOD-323 (LCSC: C57759)
- C2–C18: 100nF 0402 (LCSC: C49678) — 17 caps (C2 = PCA9685 VCC bypass, C3–C18 = per-channel drain bypass)

**Components to hand-solder after SMT:**
- J1: JST-XH 4-pin through-hole (B4B-XH-A)
- J2–J17: JST-SH 2-pin SMD horizontal (SM02B-SRSS-TB) — confirm if JLC stocks these; if not, hand-solder
- C1: 100µF electrolytic through-hole

---

## OSH Park Alternative

OSH Park (oshpark.com) accepts the same Gerber ZIP. They use a purple soldermask by default and ENIG finish standard. Per-board cost is higher but quality is excellent for prototypes.

| Parameter | OSH Park Value |
|---|---|
| Layers | 2 |
| Thickness | 1.6 mm |
| Finish | ENIG (included) |
| Color | Purple (standard) |
| Min trace/space | 0.127 mm (5 mil) — our design uses 0.25mm min, well within spec |

---

## PCM Stackup

| Layer | Copper | Use |
|---|---|---|
| F.Cu | 1 oz (35 µm) | PWM signal traces, component pads, GND pour |
| Dielectric | FR-4 1.6mm | |
| B.Cu | 1 oz (35 µm) | +5V pour (left zone), +3V motor pour (right zone) |

The split-plane design puts the 3V motor current on the back copper, separated from the 5V logic front plane by the board dielectric. This is not true split-plane impedance control but significantly reduces motor switching noise coupling into the I2C signal traces on F.Cu.

---

## Design Rule Check Summary (DRC)

All design rules pass at these settings:

| Rule | Value | Status |
|---|---|---|
| Min track width | 0.25mm (logic), 0.5mm (motor), 0.8mm (power) | ✓ |
| Min clearance | 0.2mm | ✓ |
| Min via diameter | 0.8mm drill 0.4mm | ✓ |
| TSSOP-28 pad width | 0.45mm × 1.5mm | ✓ within JLC 0.15mm min |
| SOT-23 pad | 0.8mm × 1.1mm | ✓ |
| 0402 pad | 0.9mm × 0.9mm | ✓ |
| SOD-323 pad | 0.8mm × 1.0mm | ✓ |
| JST-SH SMD pad | 0.8mm × 1.2mm | ✓ |
| Board outline to copper | >0.5mm | ✓ |

---

## Stencil

Order a stainless steel stencil if hand-applying solder paste:

- Frame size: 145mm × 145mm (framed) or frameless
- Stencil thickness: 0.12mm (for 0402 components and TSSOP-28)
- Opening reduction: 10% (JLC applies this automatically)
- JLC stencil ordering: same page as PCB order, add "Stencil" product

Alternatively use solder paste dispensed by syringe for prototype quantities.

---

## Post-Assembly Checklist

After receiving boards from fab:

- [ ] Visual inspection: no bridged pads on TSSOP-28, all 0402s present
- [ ] Continuity test: no shorts on 5V-GND, 3V-GND rails
- [ ] Set address jumpers (A0–A5 solder bridges) per addressing table before powering
- [ ] Run `i2cdetect -y 1` on Pi to verify board's I2C address
- [ ] Test single motor per board before installing all 9 into vest
