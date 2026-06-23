# Power Distribution Tree

```
USB-C Power Bank (65W PD, ≥20,000 mAh)
        │
        │ USB-C cable (5A rated, 20V PD negotiated)
        ▼
 PD Trigger Board (C2PD) + 20V→5V buck
 Input:  20V PD (up to 3.25A / 65W available)
 Output: 5V / 8A = 40W (covers ~31W system peak ≈ 6.3A)
        │
        │ 5V / 8A bus
        ├──────────────────────────────────────────────────────────────┐
        │                                                              │
        ▼                                                              ▼
 Raspberry Pi 4B (5V / 1.2A typ, 2A max)            Buck Converter (5V → 3.0V / 5A)
        │                                             MP1584EN module
        │ 3.3V onboard LDO (max 3A)                          │
        ├───────────────────────────────────┐                │ 3.0V motor rail
        │                                   │                │
        ▼                                   ▼                ▼
 GPIO/I2C outputs (PCA9685 VCC 5V)    PCA9685 V3V3     MOSFET drains → ERM motors ×144
 I2S outputs (MAX98357A VIN 5V)       (gate drive ref)
        │                                                    │
        ▼                                                    ▼
 USB3 ports ×2                                   Flyback diodes → 3.0V rail (return)
        │
        ├── D435i camera #1 (5V / 300mA = 1.5W)
        └── D435i camera #2 (5V / 300mA = 1.5W)
```

---

## Fusing and Protection

| Rail | Fuse Rating | Type | Location |
|---|---|---|---|
| 5V main bus | 8A | Polyfuse (PPTC) | At PD board output |
| 3V motor rail | 5A | Polyfuse (PPTC) | At buck converter output |
| Pi 5V input | Protected by Pi board | — | Pi has internal protection |

Use a blade-style automotive fuse holder or an 8A-hold PTC resettable fuse (e.g., Bourns MF-R800) in series with the 5V line before the Pi.

---

## Power Budget — Detailed

### Raspberry Pi 4B

| State | Current | Power |
|---|---|---|
| Idle (desktop off) | 540 mA | 2.7 W |
| Active (camera processing, I2C writes) | 1,200 mA | 6.0 W |
| Peak (brief CPU spike) | 1,800 mA | 9.0 W |

Sustained design value: **6 W @ 5V**

### D435i Cameras (×2)

| State | Current each | Power each |
|---|---|---|
| Idle | 190 mA | 0.95 W |
| Streaming depth + RGB | 300 mA | 1.50 W |

Two cameras: **3 W @ 5V**

### PCA9685 Boards (×9)

| State | Current per board | Power per board |
|---|---|---|
| Idle | 5 mA | 0.025 W |
| All channels active | 10 mA | 0.050 W |

Nine boards: **< 0.5 W @ 5V** (negligible)

### ERM Motors (×144)

| Metric | Value |
|---|---|
| Rated voltage | 3.0 V |
| Rated current per motor | 80 mA |
| Stall current per motor | 140 mA |
| Power per motor @ rated | 0.24 W |
| All 144 @ rated | 34.6 W |
| All 144 @ 100% duty cycle | 34.6 W peak |

**Realistic average**: Depth-proximity haptic patterns activate roughly 30% of motors at any time, and average duty cycle is ~50%.

```
Average motor power = 144 × 0.30 × 0.50 × 0.24 W = 5.2 W
Peak motor power (close obstacle, high intensity) ≈ 144 × 0.60 × 0.80 × 0.24 W = 16.6 W
```

Design for 20% headroom: **20 W motor rail budget @ 3V**, requiring **~21 W from 5V bus** (buck efficiency ~95%).

### MAX98357A + Speaker

| State | Power |
|---|---|
| Idle / quiet | 0.1 W |
| Speech output (typical) | 1.0 W |
| Maximum output (3.2W into 4Ω, but speaker is 8Ω) | 1.6 W |

Design value: **1 W @ 5V**

---

## Total Power Budget Summary

| Consumer | Average (W) | Peak (W) |
|---|---|---|
| Raspberry Pi 4 | 6.0 | 9.0 |
| D435i ×2 | 3.0 | 3.0 |
| ERM motors ×144 | 5.2 | 16.6 |
| Audio | 1.0 | 1.6 |
| PCA9685 ×9 | 0.5 | 0.5 |
| **Total** | **15.7 W** | **30.7 W** |

### Battery Life Estimate

```
Bank capacity: 26,800 mAh × 3.7V (nominal Li-ion) = 99 Wh
Usable (85% efficiency): ~84 Wh
At 15.7W average: 84 / 15.7 = 5.4 hours
At 30.7W peak (continuous): 84 / 30.7 = 2.7 hours
```

Practical expectation: **4–5 hours per charge** under normal active use.

---

## Ground Plane Notes

All grounds (5V logic GND, 3V motor GND, speaker GND) must connect at **one star point** — the ground terminal of the PD trigger board output. Do not create separate ground islands that connect only through cable runs; this creates ground loops and motor switching noise on I2C signals.

The buck converter's GND pin must connect to this same star point, not to the motor frame.
