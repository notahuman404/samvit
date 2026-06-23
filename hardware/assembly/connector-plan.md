# Connector Plan

## I2C Bus Chain — JST-XH 4-Pin

Used between the Raspberry Pi I2C breakout header and each PCA9685 board.

| Pin | Signal | Wire Color (suggested) |
|---|---|---|
| 1 | 5V | Red |
| 2 | GND | Black |
| 3 | SDA | White |
| 4 | SCL | Yellow |

**Connector:** JST-XH B4B-XH-A (board-side header) + XHP-4 (housing) + SXH-001T-P0.6 (crimp terminal)

**Mating cable length:** 150–200 mm between boards, routed under the vest liner. Use the same 4-pin JST-XH cable to daisy-chain from a small bus distribution PCB (or terminal block strip) mounted at the center of the vest.

Recommended distribution approach: one JST-XH 4-pin bus bar (a small breakout with one input and 9 outputs) fed from the Pi header. This avoids a daisy-chain where removing one board breaks the downstream chain.

---

## Motor Harness — JST-SH 2-Pin

Used between the MOSFET driver board output and each ERM motor.

| Pin | Signal | Wire Color |
|---|---|---|
| 1 | Motor + (3V) | Red |
| 2 | Motor − (MOSFET Drain) | Black |

**Connector:** JST-SH SM02B-SRSS-TB (board-side SMD header) + SHR-02V-S (housing) + SSH-003T-P0.2 (crimp terminal)

**Cable:** 28 AWG silicone-insulated wire, 100–150 mm length. Pre-crimped pigtail pairs (JST-SH 2-pin, 150 mm) are available from Adafruit (#4046) and save significant assembly time — strongly recommended.

**Motor lead:** The Precision Microdrives 310-113 ships with 50 mm wire leads with tinned ends. Solder these directly to the JST-SH female housing pins (no crimping needed at the motor end), then heat-shrink the solder joint.

---

## Power Rail — Ring/Fork Terminals on Bus Bar

The 5V rail and 3V motor rail run as bus bars along the vest frame (a rigid PCB strip or copper foil tape).

| Connection | Terminal | Gauge |
|---|---|---|
| PD board → 5V bus bar | M3 ring terminal | 20 AWG |
| Buck converter output → 3V bus bar | M3 ring terminal | 20 AWG |
| PCA9685 VCC taps from 5V bar | JST-XH (shared with I2C cable) | 24 AWG |
| MOSFET 3V supply taps from 3V bar | 0.1" pin header, 2-pin | 24 AWG |

---

## Camera USB Cables

The Intel RealSense D435i ships with a USB 3.2 Gen1 Type-A to Type-C cable (1 m). Use the factory cable. If a replacement is needed:

- Must be USB 3.2 Gen 1 (5 Gbps) rated
- Length: 0.5–1.0 m (longer cables increase susceptibility to bandwidth issues)
- Connector: Type-A (Pi) to Type-C (camera)
- Do not use USB 2.0 cables — the D435i depth stream requires USB 3 bandwidth

Secure cable runs along the vest shoulder straps with cable clips or hook-and-loop ties to prevent snagging.

---

## Audio — MAX98357A to Pi and Speaker

| Signal | Connection |
|---|---|
| Pi GPIO18 → BCLK | 3-pin 0.1" dupont header (female) or direct solder |
| Pi GPIO19 → LRCLK | same |
| Pi GPIO21 → DIN | same |
| Pi 5V → VIN | same |
| Pi GND → GND | same |
| Speaker + → OUT+ | 2-pin screw terminal on MAX98357A board |
| Speaker − → OUT− | 2-pin screw terminal on MAX98357A board |

Speaker cable: 26 AWG, 500 mm (shoulder to chest mount). Use a 2-pin JST-PH connector at the speaker for removability.

---

## Main Power Input

| Connection | Details |
|---|---|
| Power bank → PD trigger board | USB-C 5A rated cable, 200 mm |
| PD board output → Pi 5V input | USB-C to USB-C, or bare wire to Pi GPIO header pins 2,4 (5V) and 6 (GND) |
| PD board output → 5V bus bar | Direct solder + ring terminal |

If powering the Pi via GPIO pins 2/4 and 6 (instead of the USB-C port): note that this bypasses the Pi's onboard polyfuse. This is acceptable if you have a polyfuse on the 5V bus bar itself. GPIO 5V pins are rated for 5A per the Pi 4 schematic.

---

## Connector Summary Table

| Interface | Connector Family | Board-side | Cable-side | Qty |
|---|---|---|---|---|
| I2C bus to each PCA9685 | JST-XH 4-pin | B4B-XH-A | XHP-4 + pigtail | 9 |
| Motor harness | JST-SH 2-pin | SM02B-SRSS-TB | SHR-02V-S + 150mm | 144 |
| Speaker | JST-PH 2-pin | S2B-PH-K-S | PHR-2 + pigtail | 1 |
| Power rail taps (5V) | JST-XH (shared with I2C) | — | — | — |
| USB cameras | USB-A to USB-C | — | Factory cable | 2 |
| Main power | USB-C | — | 5A cable | 1 |
