# Haptic Feedback Vest — Hardware Design

144-channel vibrotactile vest driven by a Raspberry Pi 4, two Intel RealSense D435i depth cameras, and nine PCA9685 PWM controllers switching AO3400A MOSFETs into Precision Microdrives 310-113 ERM coin motors.

## Directory Layout

```
hardware/
├── README.md                       ← this file
├── bom/
│   ├── bom-master.csv              ← full consolidated BOM
│   └── bom-notes.md                ← sourcing notes, substitutions, tolerances
├── schematics/
│   ├── top-level-block-diagram.md  ← system block diagram (ASCII)
│   ├── motor-driver-cell.md        ← single MOSFET driver cell (repeat ×144)
│   ├── pca9685-chain.md            ← I2C chain and addressing
│   ├── power-tree.md               ← full power distribution tree
│   └── raspberry-pi-pinout.md      ← Pi GPIO assignments
├── assembly/
│   ├── assembly-guide.md           ← step-by-step build sequence
│   ├── motor-grid-layout.md        ← 12×12 grid, numbering, spacing
│   └── connector-plan.md           ← JST, FFC, USB connector specs
├── firmware-notes/
│   ├── motor-addressing.md         ← PCA9685 → motor index mapping
│   └── latency-budget.md           ← pipeline timing to hit <50 ms
└── tests/
    └── validation-procedures.md    ← hardware smoke tests and validation
```

## Quick-Start Summary

| Item | Value |
|---|---|
| Haptic channels | 144 |
| Motor grid | 12 × 12 |
| PWM controllers | 9 × PCA9685 (I2C) |
| MOSFET switches | 144 × AO3400A |
| Depth sensors | 2 × Intel RealSense D435i (USB 3) |
| Compute | Raspberry Pi 4 4 GB |
| Audio amp | MAX98357A (I2S) |
| Motor supply | 3 V rail |
| Logic supply | 5 V rail |
| Estimated peak draw | ~31 W |
| Estimated average draw | ~16 W |
| Target power bank | 65 W USB-C PD, ≥ 20 000 mAh |
| Target end-to-end latency | < 50 ms |
