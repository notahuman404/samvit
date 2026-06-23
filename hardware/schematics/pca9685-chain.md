# PCA9685 I2C Chain — Wiring and Addressing

## Physical Chain Topology

All nine PCA9685 boards share a single I2C bus in parallel (not daisy-chained serially). Each board is independently addressable.

```
Raspberry Pi GPIO2 (SDA) ─────┬───────┬───────┬─── ... ─── PCA9 SDA
                               │       │       │
Raspberry Pi GPIO3 (SCL) ─────┼───┬───┼───┬───┼─── ... ─── PCA9 SCL
                               │   │   │   │   │
                              PCA1 │  PCA2 │  PCA3
                              SDA  │  SDA  │  SDA
                              SCL  │  SCL  │  SCL

Each board also receives:
  5V  → PCA9685 VCC
  GND → PCA9685 GND
  3.3V → PCA9685 V3V3 (logic reference for output drivers)

Pull-ups:
  SDA: 4.7kΩ to 3.3V (one resistor at Pi end, in addition to Pi internal ~1.8kΩ)
  SCL: 4.7kΩ to 3.3V (one resistor at Pi end, in addition to Pi internal ~1.8kΩ)
```

Use a JST-XH 4-pin (5V / GND / SDA / SCL) connector between each board for cleanly removable connections. The chain uses the same connector footprint on all nine boards; individual cables plug directly from a small distribution hub (a 4-pin screw terminal or bus bar on the vest frame).

---

## Address Configuration

The PCA9685 base address is 0x40. Pins A0–A5 are all pulled low by default (open-drain with no solder bridge = 0).

| Board | I2C Address | A5 | A4 | A3 | A2 | A1 | A0 |
|---|---|---|---|---|---|---|---|
| PCA1 | 0x40 | 0 | 0 | 0 | 0 | 0 | 0 |
| PCA2 | 0x41 | 0 | 0 | 0 | 0 | 0 | 1 |
| PCA3 | 0x42 | 0 | 0 | 0 | 0 | 1 | 0 |
| PCA4 | 0x43 | 0 | 0 | 0 | 0 | 1 | 1 |
| PCA5 | 0x44 | 0 | 0 | 0 | 1 | 0 | 0 |
| PCA6 | 0x45 | 0 | 0 | 0 | 1 | 0 | 1 |
| PCA7 | 0x46 | 0 | 0 | 0 | 1 | 1 | 0 |
| PCA8 | 0x47 | 0 | 0 | 0 | 1 | 1 | 1 |
| PCA9 | 0x48 | 0 | 0 | 1 | 0 | 0 | 0 |

On Adafruit #815 boards, address bits are set by bridging the solder pads labelled A0–A5 on the underside. A bridged pad = 1. Leave unbridged = 0. Bridge with a small blob of solder.

---

## I2C Bus Speed

Use 400 kHz (fast-mode). The Pi's I2C peripheral supports this natively.

Set in `/boot/config.txt`:
```
dtparam=i2c_arm=on,i2c_arm_baudrate=400000
```

Or via `raspi-config` → Interface Options → I2C → enable.

At 400 kHz, updating all 144 channels requires:

- Per channel: 1 address byte + 1 register byte + 4 data bytes (LED_ON_L, LED_ON_H, LED_OFF_L, LED_OFF_H) = 6 bytes
- Per PCA9685: 16 channels × 6 bytes = 96 bytes, plus start/stop framing ≈ 100 bytes total per board
- Nine boards: 900 bytes
- At 400 kHz, 1 bit ≈ 2.5 µs: 900 × 8 × 2.5 µs = 18 ms

**This is too slow for 50 ms target if done naively.** Use the PCA9685 ALL_CALL feature to broadcast to all boards simultaneously if all channels get the same value (e.g., all-off reset), and batch writes using auto-increment mode. For individual per-motor updates, use the smbus2 `write_i2c_block_data` call to write all 64 bytes per board in one transaction:

- Per board in one transaction: ~1 ms at 400 kHz
- Nine boards sequentially: ~9 ms
- Total I2C update budget: ~9 ms — well within 50 ms target

See `firmware-notes/latency-budget.md` for full pipeline timing.

---

## PCA9685 Initialization Sequence

For each board (pseudocode):

```python
# 1. Enter SLEEP mode to allow PRE_SCALE write
write_byte(addr, MODE1, 0x10)       # SLEEP=1, ALLCALL=0

# 2. Set PWM frequency to ~200 Hz
# PRE_SCALE = round(25_000_000 / (4096 × freq)) - 1
write_byte(addr, PRE_SCALE, 0x1E)   # 0x1E = 30 → ≈196.9 Hz

# 3. Wake up; enable auto-increment
write_byte(addr, MODE1, 0xA0)       # SLEEP=0, AI=1, ALLCALL=0

# 4. Wait 500 µs oscillator stabilisation
time.sleep(0.0005)

# 5. Set all channels to 0 (motors off)
write_byte(addr, ALL_LED_ON_L,  0x00)
write_byte(addr, ALL_LED_ON_H,  0x00)
write_byte(addr, ALL_LED_OFF_L, 0x00)
write_byte(addr, ALL_LED_OFF_H, 0x10)  # 0x1000 = full OFF
```

Register addresses (from PCA9685 datasheet):

| Register | Address |
|---|---|
| MODE1 | 0x00 |
| MODE2 | 0x01 |
| LED0_ON_L | 0x06 |
| LED0_ON_H | 0x07 |
| LED0_OFF_L | 0x08 |
| LED0_OFF_H | 0x09 |
| ALL_LED_ON_L | 0xFA |
| ALL_LED_ON_H | 0xFB |
| ALL_LED_OFF_L | 0xFC |
| ALL_LED_OFF_H | 0xFD |
| PRE_SCALE | 0xFE |
