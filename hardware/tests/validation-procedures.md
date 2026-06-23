# Hardware Validation Procedures

Run these tests in order. Do not proceed to the next test until the current one passes.

---

## Pre-Power Safety Checklist

Before connecting any power:

- [ ] 5V rail: no short between 5V bus bar and GND (multimeter continuity test)
- [ ] 3V rail: no short between 3V motor rail and GND
- [ ] 5V–3V isolation: no short between 5V bus and 3V bus
- [ ] All nine PCA9685 address jumpers verified against the addressing table
- [ ] Buck converter output trimmed to 3.00–3.05 V (measure with motor rail disconnected)
- [ ] All JST connectors fully seated (click should be felt)
- [ ] No exposed solder bridges visible on MOSFET driver boards

---

## Test 1 — Logic Power-On

**Goal:** Pi boots cleanly; I2C bus detects all 9 PCA9685 boards.

**Procedure:**

1. Connect power bank; enable Pi only (motor rail disconnected).
2. Wait for Pi to boot (~30 s).
3. SSH into Pi or connect display.
4. Run:
   ```bash
   sudo i2cdetect -y 1
   ```
5. Expected output: addresses 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48 all visible. Address 0x70 also visible (ALL_CALL).

**Pass:** All 9 addresses detected. No error messages in `dmesg | grep i2c`.

**Fail:** If any address is missing — check solder jumpers on that board, check I2C cable connection, check 5V supply to that board.

---

## Test 2 — Single Motor Activation

**Goal:** Verify one motor activates, no others, no damage.

**Procedure:**

1. Connect motor rail (3V). Measure rail voltage: confirm 3.00–3.05 V.
2. Connect only motor M001 (board PCA1, channel 0). Leave all other motors disconnected.
3. Run:
   ```python
   import smbus2, time
   bus = smbus2.SMBus(1)
   # Set PCA1 (0x40) MODE1 to normal operating mode
   bus.write_byte_data(0x40, 0x00, 0xA0)
   time.sleep(0.001)
   # Set PWM freq to ~200Hz
   bus.write_byte_data(0x40, 0x00, 0x10)  # sleep
   bus.write_byte_data(0x40, 0xFE, 0x1E)  # PRE_SCALE for 200Hz
   bus.write_byte_data(0x40, 0x00, 0xA0)  # wake, auto-increment
   time.sleep(0.001)
   # Set channel 0 to full on (duty=4095)
   bus.write_i2c_block_data(0x40, 0x06, [0x00, 0x00, 0xFF, 0x0F])
   print("Motor M001 should be vibrating")
   time.sleep(3)
   # Turn off
   bus.write_i2c_block_data(0x40, 0x06, [0x00, 0x00, 0x00, 0x10])
   print("Motor M001 should be off")
   ```
4. Measure current on 3V rail during activation: should read ~80 mA (± 20 mA).
5. Feel or observe M001 vibrating. No other motor should activate.

**Pass:** M001 vibrates clearly; current reading ~80 mA; no other motors active; motor stops cleanly when turned off.

**Fail common causes:**
- Motor silent: check MOSFET gate connection, 220Ω resistor, motor harness polarity.
- Motor stays on: MOSFET gate stuck high — check for solder bridge between gate and drain.
- Current > 150 mA: motor is stalled or shorted — disconnect and inspect motor.

---

## Test 3 — Full Row Activation

**Goal:** Verify 12 motors in a row activate together; check for cross-talk.

**Procedure:**

1. Connect all 144 motors (all harnesses).
2. Run the activation script for row 1 (motors M001–M012):
   ```python
   # Initialize all 9 PCA boards first (run init sequence for each)
   # Then set motors 0–11 to full intensity, all others to 0
   heatmap = [4095 if i < 12 else 0 for i in range(144)]
   update_all_motors(bus, heatmap)
   ```
3. Physically feel row 1 of the vest. Only the top row should vibrate.
4. Observe that no motors in rows 2–12 activate.
5. Measure total 3V rail current: should be ~12 × 80 mA = ~960 mA.

**Pass:** Only row 1 vibrates; measured current between 700–1100 mA; no other motors active.

---

## Test 4 — Full Column Activation

**Goal:** Verify directional spatial perception along a column.

**Procedure:**

1. Activate column 1 (motors M001, M013, M025, M037, M049, M061, M073, M085, M097, M109, M121, M133):
   ```python
   col_1_indices = [row * 12 for row in range(12)]  # 0, 12, 24, 36, 48, 60, 72, 84, 96, 108, 120, 132
   heatmap = [4095 if i in col_1_indices else 0 for i in range(144)]
   update_all_motors(bus, heatmap)
   ```
2. Put on vest and verify you feel a vertical strip on the left side of the back.
3. Repeat for column 12 (rightmost) — you should feel the same on the right side.

**Pass:** Distinct left-only and right-only vibration bands are felt; spatial resolution is clear.

---

## Test 5 — Depth-to-Grid Mapping

**Goal:** Verify end-to-end pipeline — camera depth drives haptic pattern correctly.

**Procedure:**

1. Run the depth-to-heatmap integration:
   ```bash
   python3 firmware/haptic_main.py
   ```
2. Stand in front of a flat wall at ~3 m distance. Vest should be silent or near-silent.
3. Walk toward the wall slowly. At ~1.5 m, you should begin to feel uniform vibration across the entire vest.
4. At ~0.5 m (close to wall), the entire vest should vibrate at high intensity.
5. Hold one hand at ~0.3 m in front of the camera. Only the cells corresponding to the hand's position in the 12×12 grid should vibrate strongly.

**Pass:** Vibration intensity increases smoothly and monotonically as distance decreases; spatial localisation is discernible for a single close object; no spurious activations when field is clear.

**Fail common causes:**
- All motors activate regardless of scene: check depth frame is valid (not all zeros), check MIN/MAX_DIST_MM constants.
- No motors activate: verify cameras are streaming (run `rs-depth-viewer` to confirm D435i output), verify I2C is responding.
- Spatial mapping is mirrored: flip the depth frame horizontally before resizing if the grid is mirrored left-right compared to expectation.

---

## Test 6 — Audio

**Goal:** Verify MAX98357A plays audio through speaker.

**Procedure:**

1. Ensure I2S overlay is enabled in `/boot/config.txt` (`dtoverlay=hifiberry-dac`).
2. Run:
   ```bash
   aplay -l      # verify card 0 is hifiberry-dac
   speaker-test -c 2 -t sine -f 1000
   ```
3. You should hear a 1 kHz tone from the shoulder speaker.

**Pass:** Audible sine wave from speaker; no distortion at moderate volume.

---

## Test 7 — Thermal and Endurance

**Goal:** Confirm system runs stably for 30 minutes with 30% motor load.

**Procedure:**

1. Activate random 30% of motors at 50% duty cycle continuously for 30 minutes.
2. Monitor Pi CPU temperature:
   ```bash
   watch -n 5 vcgencmd measure_temp
   ```
3. Monitor 3V rail current with a multimeter or inline current shunt.

**Pass criteria:**
- Pi temperature stays below 80°C (throttling threshold)
- 3V rail voltage stays within 2.95–3.05 V throughout
- No motors cut out (loss of vibration at any position)
- No I2C errors in `dmesg` log
- Power bank retains charge (not dead after 30 min)

**Expected temperature:** ~65–70°C for Pi under camera load; add a heatsink to the Pi CPU if temperatures exceed 75°C.
