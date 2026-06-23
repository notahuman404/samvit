# Motor Addressing — PCA9685 Channel to Motor Index Mapping

## Addressing Scheme

Motor numbers are 0-based (0–143) in software. The physical grid is row-major, left-to-right, top-to-bottom:

```
Motor index = row * 12 + col    (row 0–11, col 0–11)
```

Each PCA9685 board controls 16 consecutive motors:

```
Board n (0-indexed) controls motors: n*16  to  n*16 + 15
```

To resolve a motor index to an I2C address and channel:

```python
I2C_ADDRESSES = [0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48]

def motor_to_pca(motor_idx: int) -> tuple[int, int]:
    """
    Returns (i2c_address, channel_0_to_15) for a given motor index (0-based).
    Raises ValueError if motor_idx is out of range.
    """
    if not 0 <= motor_idx <= 143:
        raise ValueError(f"motor_idx {motor_idx} out of range 0–143")
    board = motor_idx // 16
    channel = motor_idx % 16
    return I2C_ADDRESSES[board], channel


def grid_to_motor(row: int, col: int) -> int:
    """
    Converts (row, col) 0-based grid coordinates to a motor index 0–143.
    """
    if not (0 <= row <= 11 and 0 <= col <= 11):
        raise ValueError(f"grid position ({row},{col}) out of range")
    return row * 12 + col
```

---

## PCA9685 Register Write for One Motor

The PCA9685 controls motor intensity via PWM duty cycle. Each channel has four registers:
`LED_n_ON_L`, `LED_n_ON_H`, `LED_n_OFF_L`, `LED_n_OFF_H`.

For a motor that turns ON at counter=0 and OFF at `duty` (0–4095):

```
LED_n_ON_L  = 0x00
LED_n_ON_H  = 0x00
LED_n_OFF_L = duty & 0xFF
LED_n_OFF_H = (duty >> 8) & 0x0F
```

The register base address for channel n is `0x06 + 4*n`.

Full single-motor write (Python, using smbus2):

```python
import smbus2

bus = smbus2.SMBus(1)

def set_motor(bus, motor_idx: int, intensity: int) -> None:
    """
    intensity: 0 (off) to 4095 (full on)
    """
    addr, ch = motor_to_pca(motor_idx)
    reg_base = 0x06 + 4 * ch
    duty = max(0, min(4095, intensity))
    data = [0x00, 0x00, duty & 0xFF, (duty >> 8) & 0x0F]
    bus.write_i2c_block_data(addr, reg_base, data)
```

---

## Bulk Update — All 144 Motors in One Pass

For a full heatmap update, group writes by board to minimise I2C transactions.

Each PCA9685 supports auto-increment (AI bit in MODE1 = 1). Writing 64 bytes starting at register 0x06 updates all 16 channels in one transaction:

```python
def update_board(bus, board_idx: int, intensities: list[int]) -> None:
    """
    board_idx: 0–8
    intensities: list of 16 values, each 0–4095
    """
    assert len(intensities) == 16
    addr = I2C_ADDRESSES[board_idx]
    data = []
    for duty in intensities:
        duty = max(0, min(4095, duty))
        data += [0x00, 0x00, duty & 0xFF, (duty >> 8) & 0x0F]
    # Write 64 bytes starting at LED0_ON_L (0x06), auto-increment handles the rest
    bus.write_i2c_block_data(addr, 0x06, data)


def update_all_motors(bus, heatmap: list[int]) -> None:
    """
    heatmap: flat list of 144 intensity values (0–4095), row-major
    """
    assert len(heatmap) == 144
    for board_idx in range(9):
        start = board_idx * 16
        update_board(bus, board_idx, heatmap[start:start + 16])
```

Typical time for one full update: ~9 ms at 400 kHz I2C. See `latency-budget.md`.

---

## Depth-to-Intensity Mapping

Raw depth from RealSense D435i is in millimetres (uint16). Map to motor intensity:

```python
import numpy as np

MIN_DIST_MM = 300     # closer than this → max intensity
MAX_DIST_MM = 3000    # farther than this → off

def depth_frame_to_heatmap(depth_frame_mm: np.ndarray) -> list[int]:
    """
    depth_frame_mm: H×W uint16 array of depth values in mm
    Returns: flat list of 144 intensity values (0–4095)
    """
    # Resize to 12×12
    import cv2
    resized = cv2.resize(
        depth_frame_mm.astype(np.float32),
        (12, 12),
        interpolation=cv2.INTER_AREA
    )

    # Clamp distances
    resized = np.clip(resized, MIN_DIST_MM, MAX_DIST_MM)

    # Inverse mapping: closer → higher intensity
    # Use a nonlinear curve (inverse square) for better perceptual resolution at close range
    normalized = (MAX_DIST_MM - resized) / (MAX_DIST_MM - MIN_DIST_MM)
    intensity = (normalized ** 2) * 4095

    return intensity.flatten().astype(int).tolist()
```

When using two cameras (front chest, different tilt angles), fuse their heatmaps by taking the element-wise minimum depth (nearest obstacle in each cell wins) before mapping to intensity.
