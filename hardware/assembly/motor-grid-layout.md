# Motor Grid Layout — 12 × 12

## Physical Grid on Vest

The 144 motors are arranged in a 12-column × 12-row grid across the back of the vest.

```
Column:  C01  C02  C03  C04  C05  C06  C07  C08  C09  C10  C11  C12
        ┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
Row 01  │ 01 │ 02 │ 03 │ 04 │ 05 │ 06 │ 07 │ 08 │ 09 │ 10 │ 11 │ 12 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 02  │ 13 │ 14 │ 15 │ 16 │ 17 │ 18 │ 19 │ 20 │ 21 │ 22 │ 23 │ 24 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 03  │ 25 │ 26 │ 27 │ 28 │ 29 │ 30 │ 31 │ 32 │ 33 │ 34 │ 35 │ 36 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 04  │ 37 │ 38 │ 39 │ 40 │ 41 │ 42 │ 43 │ 44 │ 45 │ 46 │ 47 │ 48 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 05  │ 49 │ 50 │ 51 │ 52 │ 53 │ 54 │ 55 │ 56 │ 57 │ 58 │ 59 │ 60 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 06  │ 61 │ 62 │ 63 │ 64 │ 65 │ 66 │ 67 │ 68 │ 69 │ 70 │ 71 │ 72 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 07  │ 73 │ 74 │ 75 │ 76 │ 77 │ 78 │ 79 │ 80 │ 81 │ 82 │ 83 │ 84 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 08  │ 85 │ 86 │ 87 │ 88 │ 89 │ 90 │ 91 │ 92 │ 93 │ 94 │ 95 │ 96 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 09  │ 97 │ 98 │ 99 │100 │101 │102 │103 │104 │105 │106 │107 │108 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 10  │109 │110 │111 │112 │113 │114 │115 │116 │117 │118 │119 │120 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 11  │121 │122 │123 │124 │125 │126 │127 │128 │129 │130 │131 │132 │
        ├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
Row 12  │133 │134 │135 │136 │137 │138 │139 │140 │141 │142 │143 │144 │
        └────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
```

Motor index formula:

```python
motor_index = (row - 1) * 12 + (col - 1)   # 0-based
# or
motor_number = row * 12 - (12 - col)         # 1-based (M001–M144)
```

---

## Physical Dimensions

| Parameter | Value |
|---|---|
| Center-to-center spacing | 35 mm |
| Grid width (11 gaps × 35 mm) | 385 mm |
| Grid height (11 gaps × 35 mm) | 385 mm |
| Motor diameter | 10 mm |
| Gap between motor edges | 25 mm |
| Total panel area | ~420 mm × 420 mm including edge margins |

The 420 mm × 420 mm panel fits within the back panel of most tactical/plate-carrier vests (typical back panel: 250–300 mm wide × 350 mm tall). **Reduce to a 10×10 grid (100 motors) or reduce spacing to 28 mm if the vest back is smaller than 400 mm in either dimension.** Measure the vest before committing to spacing.

---

## PCA9685 Board-to-Motor Assignment

Each PCA9685 board controls 16 consecutive motors in row-major order.

| PCA Board | I2C Addr | Motors (1-based) | Grid Rows |
|---|---|---|---|
| PCA1 | 0x40 | M001 – M016 | Row 1, Row 2 cols 1–4 |
| PCA2 | 0x41 | M017 – M032 | Row 2 cols 5–12, Row 3 cols 1–8 |
| PCA3 | 0x42 | M033 – M048 | Row 3 cols 9–12, Row 4 |
| PCA4 | 0x43 | M049 – M064 | Row 5, Row 6 cols 1–4 |
| PCA5 | 0x44 | M065 – M080 | Row 6 cols 5–12, Row 7 cols 1–8 |
| PCA6 | 0x45 | M081 – M096 | Row 7 cols 9–12, Row 8 |
| PCA7 | 0x46 | M097 – M112 | Row 9, Row 10 cols 1–4 |
| PCA8 | 0x47 | M113 – M128 | Row 10 cols 5–12, Row 11 cols 1–8 |
| PCA9 | 0x48 | M129 – M144 | Row 11 cols 9–12, Row 12 |

Software mapping (Python):

```python
PCA_ADDR = [0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48]

def motor_to_pca(motor_idx: int) -> tuple[int, int]:
    """
    motor_idx: 0-based (0–143)
    Returns (i2c_address, channel) where channel is 0–15.
    """
    board = motor_idx // 16
    channel = motor_idx % 16
    return PCA_ADDR[board], channel
```

---

## Vest Orientation Convention

- Row 1 = **top** of back panel (near shoulders)
- Row 12 = **bottom** of back panel (near lumbar)
- Column 1 = **left** side (wearer's left)
- Column 12 = **right** side (wearer's right)

The depth camera heatmap is projected onto this grid with the same orientation: upper-left of the camera depth image maps to M001 (top-left of vest), lower-right maps to M144 (bottom-right of vest).

---

## Motor Attachment Method

Recommended: double-sided foam tape (3M VHB 1.0 mm, 5 mm × 5 mm squares cut to size) on the back face of the motor. The vibrating mass is on the underside facing the vest fabric, ensuring vibration is transmitted into the vest and to the skin.

Do not glue directly — motors fail and need replacement. Use hook-and-loop (Velcro) loops stitched to the vest fabric for final retention of harness cable runs, with the foam tape holding the motor head itself.

Mark the 12×12 grid on the vest panel with a fabric marker and a 35 mm spacing template (a 3D-printed jig simplifies this) before attaching motors.
