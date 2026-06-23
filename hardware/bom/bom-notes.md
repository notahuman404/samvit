# BOM Notes — Sourcing, Substitutions, Tolerances

## AO3400A MOSFET

The AO3400A is logic-level compatible. The PCA9685 outputs 3.3 V PWM from a 3.3 V VCC pin. The AO3400A datasheet shows:

- Vgs(th) max = 1.45 V
- Id = 4 A continuous at Tc = 70 °C
- Rds(on) = 56 mΩ at Vgs = 2.5 V
- SOT-23 package

At Vgs = 3.3 V the device is fully enhanced. At 80 mA motor current the Vds drop is negligible (< 5 mV). No level shifter required.

**Acceptable substitutes:** IRLML2502 (same SOT-23, similar Vgs(th)), 2N7002 (lower current but fine for 80 mA). Do not substitute with logic-level parts that need ≥ 4 V gate drive.

---

## Flyback Diode

The 1N4148WS (SOD-323) has a reverse recovery time of 4 ns, which is fast enough to clamp the inductive kick when the MOSFET turns off. The motor inductance is low (typical ERM coil ~100 µH) but the clamping diode must be placed physically close to the motor terminals.

**Acceptable substitute:** BAT54 (Schottky, even faster, lower Vf). Do not use 1N4007 — its reverse recovery is too slow (30 µs) and it will not protect the MOSFET adequately at PWM frequencies above a few kHz.

---

## PCA9685

The PCA9685 has a configurable I2C address via six address pins (A0–A5), giving 64 possible addresses. We use nine boards at 0x40–0x48, which requires setting:

| Board | A0 | A1 | A2 | A3 | A4 | A5 |
|---|---|---|---|---|---|---|
| PCA1 (0x40) | 0 | 0 | 0 | 0 | 0 | 0 |
| PCA2 (0x41) | 1 | 0 | 0 | 0 | 0 | 0 |
| PCA3 (0x42) | 0 | 1 | 0 | 0 | 0 | 0 |
| PCA4 (0x43) | 1 | 1 | 0 | 0 | 0 | 0 |
| PCA5 (0x44) | 0 | 0 | 1 | 0 | 0 | 0 |
| PCA6 (0x45) | 1 | 0 | 1 | 0 | 0 | 0 |
| PCA7 (0x46) | 0 | 1 | 1 | 0 | 0 | 0 |
| PCA8 (0x47) | 1 | 1 | 1 | 0 | 0 | 0 |
| PCA9 (0x48) | 0 | 0 | 0 | 1 | 0 | 0 |

On Adafruit-style boards, these are solder jumpers (bridge with solder). On bare PCA9685 ICs, pull address pins to VCC (1) or leave floating/GND (0) per the datasheet.

The PCA9685 internal oscillator is 25 MHz with ±1% accuracy. For ERM motor PWM (target ~200 Hz), set the PRE_SCALE register to match. The exact PRE_SCALE value for 200 Hz:

```
PRE_SCALE = round(25_000_000 / (4096 × 200)) - 1 = round(30.52) - 1 = 30
```

Write 0x1E to register 0xFE of each board. Do this while the SLEEP bit in MODE1 is set.

---

## ERM Motor — Precision Microdrives 310-113

Key specs:

| Parameter | Value |
|---|---|
| Diameter | 10 mm |
| Thickness | 2.7 mm |
| Rated voltage | 3 V |
| Rated current | 80 mA |
| No-load current | 45 mA |
| Stall current | 140 mA |
| Start voltage | 1.5 V |
| Operating range | 1.5 – 3.5 V |
| Amplitude @ 3V | ~2.0 G |
| Frequency @ 3V | ~200 Hz |

The 310-113 has a 0.8 mm shaft with a flat. Ensure the adhesive pad (included or sourced separately) faces the vest fabric side, not the electronics side.

**Substitutes:** Any 10 mm coin ERM running at 3 V and drawing ≤ 120 mA. Larger motors (e.g., 12 mm) will not fit at 35 mm center-to-center spacing in a 12×12 grid.

---

## Power Bank Requirements

The power bank must support USB-C Power Delivery (PD) and sustain at least ~35 W on a single port (the system peaks at ~31 W, negotiated at 20 V). Many banks advertise 65 W but cannot sustain that continuously from a single port.

Verified models (as of 2025):
- Anker 737 Power Bank (PowerCore 26K) — dual 140 W ports, 25 600 mAh
- UGREEN 25000mAh 130W — sustained 65 W per port confirmed
- Baseus Blade 100W — thinner form factor

The PD trigger board (C2PD or similar, with a 20 V→5 V buck stage) negotiates 20 V from the bank and steps down to 5 V / 8 A cleanly (40 W output, covering the ~31 W / ~6.3 A system peak). A bare 5 V / 5 A (25 W) trigger is undersized. Do not try to power the system directly from a 5 V USB-A port — the current limit is too low.

---

## 3 V Motor Rail

The Pi's 5V rail must not power the motors directly. Use a dedicated buck converter (MP1584EN, MINI560-5V variant with output trimmed down, or a pre-built module). Set output to exactly 3.00 V using a multimeter before connecting motors.

Max continuous output required: 144 motors × 30% active × 80 mA = 3.5 A. Use a converter rated ≥ 5 A for thermal margin.

---

## I2C Pull-Up Resistors

The Pi's GPIO2/GPIO3 (SDA/SCL) have internal 1.8 kΩ pull-ups already enabled in the Pi's I2C peripheral. With nine PCA9685 boards on the bus, the total capacitive load is ~90 pF. At 400 kHz (fast-mode I2C) the RC time constant is:

```
τ = 1800 × 90×10⁻¹² = 162 ns
```

The I2C spec requires edges within 300 ns — this is marginal. Add external 4.7 kΩ pull-ups to 3.3 V on the SDA and SCL lines (in parallel with the Pi's internal ones), bringing effective pull-up to ~1.3 kΩ. This comfortably meets the 300 ns rise time spec.
