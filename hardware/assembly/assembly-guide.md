# Assembly Guide

Follow this sequence exactly. Each step assumes the previous one is complete and verified.

---

## Tools Required

- Soldering iron + solder (63/37, 0.6 mm)
- Hot air station (for SOD-323 diodes and SOT-23 MOSFETs if building on PCB)
- Multimeter (voltage and continuity)
- JST-SH crimping tool (PA-09 or Engineer PA-21)
- Small diagonal cutters and wire strippers
- 3D-printed 35 mm spacing template (optional but recommended)
- Fabric marker
- Double-sided foam tape (3M VHB 1 mm)

---

## Step 1 — Prepare the Vest

1. Lay the vest flat on a work surface, back panel facing up.
2. Locate the center of the back panel (width and height midpoint).
3. Mark the 12×12 grid with a fabric marker:
   - Start 17.5 mm from the intended grid edges (half a motor pitch)
   - Columns spaced 35 mm apart
   - Rows spaced 35 mm apart
   - Total 144 intersection points
4. Verify the outer grid bounds fit within the vest back panel dimensions.
5. Stitch 5 mm × 50 mm hook-and-loop strips in horizontal runs at every row for cable routing.

---

## Step 2 — Attach Motors

1. Cut 144 squares of 3M VHB double-sided foam tape, approximately 7 mm × 7 mm.
2. Peel one side; apply to the back (non-vibrating) face of each motor.
3. For each intersection point on the grid:
   - Peel the second foam tape face
   - Press the motor flat on the mark, vibrating mass facing the vest fabric
   - Apply firm pressure for 30 seconds
4. Label each motor M001–M144 with a small adhesive label on the motor body before attachment (easier to trace faults later).
5. Run motor pigtail wires along the nearest horizontal cable route, secured with hook-and-loop.

---

## Step 3 — Build MOSFET Driver Boards

For prototype: use 9 separate perfboard panels, one per PCA9685 group (16 driver cells each).

For each of the 16 driver cells per board:

1. Install AO3400A MOSFET in SOT-23 orientation (Gate=pin1, Source=pin3, Drain=pin2).
2. Install 220Ω resistor (0402) between PCA9685 channel output pad and MOSFET gate.
3. Install 1N4148WS diode (SOD-323) across motor pads — cathode (+) toward 3V rail, anode (−) toward MOSFET drain.
4. Install 100nF ceramic capacitor between MOSFET drain pad and 3V rail (local supply decoupling).
5. Install JST-SH 2-pin header for motor connection.
6. Install JST-XH 4-pin header for I2C + power input from Pi chain.

Verify continuity (no short between 3V rail and GND) before proceeding.

---

## Step 4 — Install PCA9685 Boards

1. Set address solder jumpers on each PCA9685 board per the addressing table in `schematics/pca9685-chain.md`.
2. Verify each board's I2C address with a continuity meter across the address jumpers.
3. Mount the 9 PCA9685 boards in the vest's rear electronics pocket or on a rigid backing plate.
4. Connect the JST-XH 4-pin I2C/power cable from the Pi distribution hub to each board.
5. Add one 100µF electrolytic capacitor across VCC–GND on each PCA9685 board (solder across the power rails).

---

## Step 5 — Mount Raspberry Pi

1. Mount the Pi in its rear enclosure (3D-printed or ABS box) on the lower back section of the vest.
2. Secure with M2.5 standoffs and screws.
3. Connect I2C distribution hub to Pi GPIO pins 3 (SDA) and 5 (SCL), plus 3.3V (pin 1) and GND (pin 6).
4. Solder 4.7kΩ pull-up resistors from SDA to 3.3V and SCL to 3.3V at the Pi header.
5. Connect MAX98357A audio amp to Pi GPIO18/19/21 and 5V/GND per pinout table.
6. Route USB-C power cable from power bank to PD trigger board.
7. Route PD board 5V output to Pi USB-C input and to 5V bus bar.

---

## Step 6 — Connect RealSense Cameras

1. Mount camera #1 (upper, +35° tilt) on the front chest strap, top position.
   - Use a 3D-printed bracket angled at 35° downward from horizontal.
   - Fasten bracket to MOLLE webbing with a 25 mm strap.
2. Mount camera #2 (lower, 0° / horizontal) on the front chest strap, lower position, ~150 mm below camera #1.
3. Route USB3 cables from both cameras over the shoulder to the Pi USB3 (blue) ports.
4. Use cable clips every 150 mm along the vest strap to secure the cables.
5. Do not strain-relieve the USB connector with tape — use proper cable hooks to allow connector removal.

Camera placement rationale:
- Upper camera at +35° captures ground plane from ~1.5 m range at eye level when standing
- Lower camera at 0° captures obstacles at chest height; combined FOV covers roughly ground to head height within 3 m

---

## Step 7 — Install Audio

1. Mount MAX98357A board inside the electronics pocket, secured with foam tape.
2. Connect speaker wire (26 AWG, ~500 mm) from MAX98357A OUT+/OUT− to shoulder-mounted speaker.
3. Mount speaker in a 3D-printed housing on the shoulder strap with M2 screws.
4. Route speaker wire under the shoulder padding.

---

## Step 8 — Power Rail Verification

Before enabling motors:

1. Measure voltage at 5V bus bar with multimeter: should read 4.95–5.05 V.
2. Measure voltage at 3V motor rail output with multimeter: trim buck converter until it reads 3.00–3.05 V. Do this **before** connecting motors.
3. Verify GND continuity between Pi GND pin, 5V bus bar GND, and 3V rail GND (all should be 0Ω).
4. Verify no short between 5V bus and GND, and between 3V motor rail and GND.
5. With motors disconnected, enable power and re-measure all rails under logic load (Pi + PCA9685 boards powered).
6. Connect motor harnesses only after all rails are verified.

---

## Step 9 — Software Setup and First Boot

1. Flash Raspberry Pi OS Lite (64-bit) to a microSD card.
2. Enable I2C and I2S in `/boot/config.txt` (see `schematics/raspberry-pi-pinout.md`).
3. Install dependencies:
   ```bash
   sudo apt-get update
   sudo apt-get install -y python3-smbus2 python3-pip librealsense2-dev
   pip3 install pyrealsense2 adafruit-circuitpython-pca9685
   ```
4. Run `i2cdetect -y 1` and verify all 9 PCA9685 addresses appear (0x40–0x48).
5. Proceed to validation tests in `tests/validation-procedures.md`.
