# Single Motor Driver Cell

This circuit is repeated 144 times — once per ERM motor.

```
PCA9685 PWM Output Pin (3.3V logic, open-drain with pull-up)
                │
               [R] 220Ω  (RC0402FR-07220RL)
                │
                └──────────────── Gate (AO3400A)
                                       │
                         ┌─────────────┤
                         │         AO3400A (SOT-23)
                         │             │
                    Source ────────── GND (0V)
                                       │
                                   Drain ──────────── Motor negative terminal (–)
                                                              │
                                                         [ERM Motor]
                                                    Precision Microdrives 310-113
                                                              │
                                              Motor positive terminal (+) ──── 3V rail
                                                              │
                                         [Flyback diode: 1N4148WS, SOD-323]
                                          Cathode → 3V rail
                                          Anode   → Motor negative (= MOSFET Drain)
```

---

## Schematic in Table Form

| Node | Component | Connection |
|---|---|---|
| PWM_n | PCA9685 channel n output | → 220Ω gate resistor |
| Gate | AO3400A G | ← 220Ω from PWM_n |
| Source | AO3400A S | → GND |
| Drain | AO3400A D | → Motor − terminal; Diode anode |
| Motor + | ERM + | → 3V rail |
| Motor − | ERM − | → AO3400A Drain |
| D_anode | 1N4148WS A | → AO3400A Drain (= Motor −) |
| D_cathode | 1N4148WS K | → 3V rail |

---

## Design Rationale

### 220Ω Gate Resistor

Without a gate resistor, the parasitic capacitance at the gate (Ciss ≈ 270 pF for AO3400A) combined with the very low output impedance of the PCA9685 creates a high dV/dt at turn-on. This causes:
- Excessive current spike in the driver
- High-frequency ringing on the gate, potentially causing spurious oscillations

220Ω limits peak gate current to ≈ 3.3 V / 220 Ω = 15 mA, which is well within the PCA9685 source/sink rating of 25 mA. Switching time is still fast (τ = 220 × 270 pF = 59 ns → 10–90% transition in ~130 ns), acceptable for a 200 Hz PWM signal.

### Flyback Diode Placement

The diode must be placed physically as close to the motor terminals as possible — on the motor PCB pad or at the JST-SH connector. If placed at the PCA9685 board instead, the wiring inductance between the diode and the motor adds extra voltage spike. Aim for < 10 mm lead length from diode to motor terminals.

### N-Channel Low-Side Switch

The motor is switched on the low side (between motor − and GND). This means:
- Gate drive is simple: Vgs = logic voltage (3.3 V), no bootstrap required
- Motor + terminal is always tied to the 3V rail (no shoot-through risk)
- Ground is shared between logic and motor rails (important: keep 3V motor GND and 5V logic GND tied at one star point to prevent ground offset)

---

## PWM Duty Cycle to Haptic Intensity

The PCA9685 generates 12-bit PWM (0–4095 steps). The motor responds roughly linearly in amplitude to RMS voltage up to ~3 V.

| Duty cycle | Effective Vrms | Relative intensity |
|---|---|---|
| 0% | 0 V | Off |
| 25% | 1.5 V | ~25% — barely perceptible |
| 50% | 2.1 V | ~55% — clearly felt |
| 75% | 2.6 V | ~80% — strong |
| 100% | 3.0 V | 100% — maximum |

Software should map depth sensor distance to a duty cycle using a nonlinear (e.g., inverse-square or log-inverse) curve so that the haptic sensation changes gradually at long distances and sharply at close range.

---

## PCB Layout Notes for Production

When moving from perfboard to a custom PCB:

1. Place the MOSFET and its flyback diode together in a cell. Repeat the cell 16 times per driver board (one per PCA9685 board).
2. Motor current traces must carry 80 mA sustained, 140 mA peak (stall). A 0.15 mm trace width on 1 oz copper is sufficient (ampacity ~400 mA), but use 0.3 mm for margin.
3. 3V motor power plane on the bottom layer, logic signals on the top layer. Separate pour fills with a 0.5 mm gap.
4. One 100 µF electrolytic + one 100 nF ceramic cap per PCA9685 board on the 5V supply.
5. One 100 nF ceramic cap per MOSFET drain (motor supply side) to absorb fast transients.
