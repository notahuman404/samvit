# Raspberry Pi 4B GPIO Pin Assignments

## Physical Pin Header (40-pin, BCM numbering)

```
                    3V3  1 ●│● 2  5V
    I2C SDA   GPIO2  3 ●│● 4  5V
    I2C SCL   GPIO3  5 ●│● 6  GND ◄── I2C chain GND, PCA9685 GND
              GPIO4  7 ○│○ 8  GPIO14 (TXD)
                   GND  9 ●│○ 10 GPIO15 (RXD)
             GPIO17 11 ○│○ 12 GPIO18 ◄── I2S BCLK (MAX98357A)
             GPIO27 13 ○│● 14 GND
             GPIO22 15 ○│○ 16 GPIO23
                3V3 17 ○│○ 18 GPIO24
    SPI MOSI GPIO10 19 ○│● 20 GND
    SPI MISO  GPIO9 21 ○│○ 22 GPIO25
    SPI SCLK GPIO11 23 ○│○ 24 GPIO8 (CE0)
                   GND 25 ○│○ 26 GPIO7 (CE1)
              GPIO0 27 ○│○ 28 GPIO1
              GPIO5 29 ○│○ 30 GND
              GPIO6 31 ○│○ 32 GPIO12
             GPIO13 33 ○│● 34 GND
I2S LRCLK  GPIO19 35 ●│○ 36 GPIO16
             GPIO26 37 ○│○ 38 GPIO20
                   GND 39 ○│● 40 GPIO21 (I2S DIN → MAX98357A)

● = used    ○ = available
```

---

## Pin Assignment Table

| BCM GPIO | Physical Pin | Signal | Destination | Notes |
|---|---|---|---|---|
| GPIO2 | 3 | I2C1 SDA | PCA9685 boards ×9 SDA | Hardware I2C; add 4.7kΩ pull-up to 3.3V |
| GPIO3 | 5 | I2C1 SCL | PCA9685 boards ×9 SCL | Hardware I2C; add 4.7kΩ pull-up to 3.3V |
| GPIO18 | 12 | I2S BCLK | MAX98357A BCLK | Hardware I2S audio |
| GPIO19 | 35 | I2S LRCLK / PCM_FS | MAX98357A LRCLK | Also labelled PCM_FS in some schematics |
| GPIO21 | 40 | I2S DIN / PCM_DOUT | MAX98357A DIN | Data out from Pi to amp |
| — | 1 | 3.3V | PCA9685 V3V3 (×9) | Also pull-up reference for I2C resistors |
| — | 4 | 5V | PCA9685 VCC (×9), MAX98357A VIN | 5V logic rail |
| — | 6,9,14,20,25,30,34,39 | GND | All ground references | Star ground back to PD board |

---

## MAX98357A Wiring Detail

| MAX98357A Pin | Pi Physical Pin | Signal | Notes |
|---|---|---|---|
| BCLK | Pin 12 | GPIO18 (I2S CLK) | Bit clock |
| LRC / LRCLK | Pin 35 | GPIO19 (I2S LRCLK) | Word select / frame clock |
| DIN | Pin 40 | GPIO21 (I2S DOUT) | Audio data from Pi to amp |
| GND | Pin 6 | GND | |
| VIN | Pin 4 | 5V | |
| SD (shutdown) | — | Leave floating | Float = normal operation; pull low to mute |
| GAIN | — | Leave floating | Float = 9 dB gain |

Speaker + and − connect to MAX98357A output terminals (labelled OUT+ / OUT− on Adafruit board). Polarity does not matter for a single speaker.

---

## Camera Connections

Both D435i cameras connect to **USB 3.0 Type-A** ports on the Pi 4B (the blue ports). The Pi 4B has two USB 3.0 ports, which exactly matches two cameras.

No GPIO wiring required for cameras.

---

## I2C Bus Enable

Enable I2C on the Pi before first use:

```bash
sudo raspi-config
# → Interface Options → I2C → Yes

# Or directly:
sudo sh -c 'echo "dtparam=i2c_arm=on,i2c_arm_baudrate=400000" >> /boot/config.txt'
sudo reboot

# Verify devices detected:
sudo i2cdetect -y 1
```

Expected output (9 PCA9685 boards):

```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: 40 41 42 43 44 45 46 47 48 -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- 70                          --
```

0x70 is the PCA9685 ALL_CALL address (broadcast to all boards). This is expected.

---

## I2S Audio Enable

Enable I2S overlay:

```bash
sudo sh -c 'echo "dtoverlay=hifiberry-dac" >> /boot/config.txt'
sudo reboot

# Verify audio device:
aplay -l
# Should list: card 0: sndrpihifiberry [snd_rpi_hifiberry_dac]
```

Set playback volume:

```bash
alsamixer -c 0
# or
amixer -c 0 set Digital 80%
```
