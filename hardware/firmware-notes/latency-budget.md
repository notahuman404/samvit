# Pipeline Latency Budget

Target: **< 50 ms** end-to-end from obstacle presence to haptic activation.

---

## Pipeline Stages

```
[Physical obstacle enters camera FOV]
         │
         │ optical propagation (speed of light) → negligible
         ▼
[D435i D435i sensor — depth frame capture]
         │ ~8.3 ms  (at 120 fps, 1/120 s per frame)
         ▼
[USB 3.0 transfer to Pi]
         │ ~1–2 ms  (USB3 latency at 480p depth frame ~60KB)
         ▼
[Depth frame in Pi RAM]
         │
         ▼
[Software: receive frame from librealsense SDK]
         │ ~1–2 ms  (SDK callback, frame already in host memory via DMA)
         ▼
[Depth processing: resize + clip + intensity map]
         │ ~1–2 ms  (NumPy ops on 480×270 → 12×12; CPU-bound)
         ▼
[I2C writes to 9 PCA9685 boards]
         │ ~9 ms    (64 bytes × 9 boards at 400 kHz, sequential)
         ▼
[PCA9685 hardware PWM begins outputting]
         │ < 1 ms  (hardware; no CPU)
         ▼
[MOSFET switches motor current]
         │ < 1 µs  (AO3400A switching time)
         ▼
[ERM motor spins up to tactile threshold]
         │ ~10–20 ms  (ERM rise time; ~15 ms typical for 310-113)
         ▼
[Wearer perceives vibration]
```

---

## Latency Table

| Stage | Time (ms) | Notes |
|---|---|---|
| D435i frame capture | 8.3 | At 120 fps mode; 33 ms at 30 fps |
| USB3 transfer | 1.5 | Measured; D435i SDK uses zero-copy DMA |
| SDK frame delivery | 1.5 | Callback latency |
| Depth resize + map | 2.0 | NumPy on Pi 4 (64-bit, ~1.5 GHz) |
| I2C write all 9 boards | 9.0 | 400 kHz, sequential board writes |
| PCA9685 → MOSFET gate | 0.1 | Hardware PWM |
| MOSFET switching | 0.001 | AO3400A 130 ns transition |
| ERM motor rise time | 15.0 | Mechanical; 10–20 ms typical |
| **Total** | **~37 ms** | Well within 50 ms target |

---

## Operating at 120 fps

The D435i supports the following depth streaming modes:

| Resolution | FPS | Depth latency |
|---|---|---|
| 1280×720 | 30 | 33.3 ms |
| 848×480 | 90 | 11.1 ms |
| 848×480 | 120 | 8.3 ms |
| 640×360 | 90 | 11.1 ms |

For latency optimisation, use **848×480 @ 90 fps**. 120 fps is supported but requires USB bandwidth verification with two simultaneous cameras. At 90 fps, two cameras in depth-only mode (no RGB) stay within the USB3 5 Gbps bandwidth of the Pi's single USB3 hub.

Configure in firmware:

```python
import pyrealsense2 as rs

pipeline = rs.pipeline()
config = rs.config()
config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 90)
pipeline.start(config)
```

Disable the RGB stream on both cameras to halve USB bandwidth consumption:

```python
# Do NOT add:
# config.enable_stream(rs.stream.color, ...)
```

---

## I2C Timing Optimisation

Sequential 9-board update (~9 ms) is acceptable. Further optimisations if needed:

### Option 1: PCA9685 ALL_CALL broadcast
- All 9 boards share address 0x70 (ALL_CALL, enabled by default in MODE1 ALLCALL bit)
- A single write to 0x70 updates all 144 channels to the same value simultaneously
- Useful for all-off reset (safety stop in < 1 ms)
- Cannot set individual motor values via ALL_CALL

### Option 2: Parallel I2C buses using Pi I2C_VC (hardware second bus)
- The Pi 4 has a second hardware I2C bus on GPIO0/GPIO1 (I2C0, normally reserved for HAT EEPROM)
- Can be freed with `dtparam=i2c_vc=on`
- Split 9 boards across two buses: 5 on I2C1, 4 on I2C0
- Update both buses concurrently using Python threading
- Reduces I2C write time to ~5 ms

### Option 3: Reduce update resolution
- Only update boards whose motor intensities changed since last frame
- Typical scenario: 3–4 boards near the obstacle are active; others are all-zero
- Skip zero boards with a fast all-channels-off burst (ALL_LED_OFF register write, 4 bytes)
- Can reduce average I2C time to ~3 ms

---

## ERM Rise Time

The 310-113 ERM has a typical rise time (0→63% rated amplitude) of ~15 ms. This is mechanical and cannot be shortened in software. However:

- **Preemptive activation**: activate motors at low intensity (~10% duty cycle) when obstacles are detected at > 2 m range. This keeps the motor spinning slightly, reducing rise time to full intensity to ~5 ms when the obstacle enters the danger zone.
- This "standby spin" pattern only activates motors in cells that have any obstacle closer than 5 m, at < 5% duty cycle — below perception threshold for most users.

With preemptive activation, effective onset latency can be reduced to **~25 ms total**.

---

## Worst-Case Latency Analysis

Worst case (two cameras simultaneously produce large depth frames, I2C bus has retries):

| Stage | Worst-case time (ms) |
|---|---|
| Frame capture (90 fps) | 11.1 |
| USB3 + SDK | 5.0 |
| Processing | 4.0 |
| I2C writes (with one retry per board) | 18.0 |
| ERM rise | 20.0 |
| **Total worst-case** | **~58 ms** |

Worst case slightly exceeds 50 ms due to ERM mechanical delay. The 50 ms target is met for the electrical + computational path (≤ 38 ms worst case). Adding preemptive motor spin eliminates the ERM rise contribution and achieves < 40 ms reliably.
