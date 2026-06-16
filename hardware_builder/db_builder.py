import sqlite3

db_path = "./samvit_parts.db"
conn = sqlite3.connect(db_path)
c = conn.cursor()

c.execute('''CREATE TABLE parts (
    id INTEGER PRIMARY KEY,
    name TEXT,
    category TEXT,
    description TEXT,
    voltage_v TEXT,
    current_ma TEXT,
    package TEXT,
    footprint TEXT,
    cost_usd REAL,
    compatibility TEXT,
    notes TEXT
)''')

parts = [
    # Microcontrollers
    ("Raspberry Pi 4B", "SBC", "Main compute unit for AI/voice processing", "5V", "3000", "Board", "RPi4B", 45.00, "Layer 1 Software", "Runs Jarvis engine"),
    ("Raspberry Pi Zero 2W", "SBC", "Lightweight compute for wearable hardware layer", "5V", "800", "Board", "RPiZero2W", 15.00, "Layer 2 Hardware", "Low power wearable option"),
    ("ESP32-WROOM-32", "MCU", "WiFi+BT MCU for sensor coordination", "3.3V", "240", "Module", "ESP32-WROOM", 3.50, "Layer 2 Hardware", "Controls haptic/audio feedback"),
    ("STM32F103C8T6", "MCU", "ARM Cortex-M3 for real-time feedback control", "3.3V", "50", "LQFP-48", "LQFP48", 2.80, "Layer 2 Hardware", "Blue Pill board"),
    ("Arduino Nano", "MCU", "Prototyping microcontroller", "5V/3.3V", "200", "Through-hole", "Nano", 4.00, "Layer 2 Hardware", "Rapid prototype use"),

    # Cameras & Depth Sensors
    ("Intel RealSense D435", "Depth Sensor", "Stereo depth camera for spatial mapping", "5V", "1500", "Module", "RealSense-D435", 179.00, "Layer 2 Hardware", "Primary heatmap input"),
    ("OAK-D Lite", "Depth Sensor", "Spatial AI camera with onboard compute", "5V", "1000", "Module", "OAK-D-Lite", 149.00, "Layer 2 Hardware", "Alternative to RealSense"),
    ("Raspberry Pi Camera v3", "Camera", "12MP camera module", "3.3V", "250", "Module", "RPiCam-v3", 25.00, "Layer 2 Hardware", "2D visual input fallback"),
    ("TF-Luna LiDAR", "LiDAR", "Single-point LiDAR distance sensor", "3.3-5V", "35", "Module", "TF-Luna", 18.00, "Layer 2 Hardware", "Short-range obstacle detection"),
    ("VL53L1X", "ToF Sensor", "Time-of-Flight distance sensor", "2.6-3.5V", "20", "SXGA", "VL53L1X-Breakout", 5.50, "Layer 2 Hardware", "I2C, up to 4m range"),

    # Haptic / Feedback
    ("DRV2605L", "Haptic Driver", "I2C haptic motor driver", "2.7-5.5V", "200", "WSON-10", "DRV2605L-Breakout", 3.95, "Layer 2 Hardware", "Drives ERM/LRA motors"),
    ("ERM Vibration Motor 10mm", "Actuator", "Eccentric rotating mass vibration motor", "3V", "85", "Through-hole", "10mm-Disc", 1.20, "Layer 2 Hardware", "Primary haptic output"),
    ("LRA Linear Resonant Actuator", "Actuator", "Precise frequency haptic actuator", "1.8V", "150", "SMD", "LRA-8mm", 2.50, "Layer 2 Hardware", "Higher fidelity than ERM"),
    ("PAM8403", "Audio Amp", "3W stereo audio amplifier", "5V", "600", "SOP-16", "SOP16", 0.80, "Layer 2 Hardware", "Audio feedback output"),
    ("MAX98357A", "Audio Amp", "I2S DAC + 3W amp", "2.7-5.5V", "600", "TDFN-8", "MAX98357A-Breakout", 1.50, "Layer 2 Hardware", "For RPi I2S audio"),

    # Power Management
    ("TP4056", "Charger IC", "Li-Ion/LiPo single cell charger", "4.5-5.5V", "1000", "SOP-8", "SOP8", 0.50, "Layer 2 Hardware", "USB-C charging"),
    ("BQ24295", "Charger IC", "USB fast charger with power path", "3.9-5.5V", "2000", "VQFN-24", "VQFN24", 3.20, "Layer 2 Hardware", "Advanced power path mgmt"),
    ("TPS63020", "Buck-Boost", "Buck-boost converter 1.8-5.5V", "1.8-5.5V", "2000", "VSON-10", "VSON10", 3.80, "Layer 2 Hardware", "Stable 3.3V from LiPo"),
    ("MT3608", "Boost Converter", "2A boost converter to 28V", "2-24V", "2000", "SOT-23-6", "SOT23-6", 0.40, "Layer 2 Hardware", "5V rail from battery"),
    ("18650 Li-Ion Cell", "Battery", "3.7V 3000mAh rechargeable cell", "3.7V nominal", "3000mAh", "Cylindrical", "18650", 5.00, "Layer 2 Hardware", "Main power source"),

    # IMU / Motion
    ("MPU-6050", "IMU", "6-axis accel + gyro", "3.3-5V", "3.9", "QFN-24", "MPU6050-Breakout", 1.50, "Layer 2 Hardware", "Orientation tracking"),
    ("ICM-42688-P", "IMU", "6-axis high precision IMU", "1.71-3.6V", "0.65", "LGA-14", "ICM42688", 3.20, "Layer 2 Hardware", "Better noise than MPU6050"),
    ("BNO055", "IMU", "9-axis absolute orientation sensor", "2.4-3.6V", "12.3", "LGA-28", "BNO055-Breakout", 5.00, "Layer 2 Hardware", "Onboard sensor fusion"),
    ("BMP280", "Barometer", "Pressure + temperature sensor", "1.71-3.6V", "2.7", "LGA-8", "BMP280-Breakout", 1.20, "Layer 2 Hardware", "Altitude awareness"),

    # Wireless / Comms
    ("HC-05 Bluetooth", "BT Module", "Classic Bluetooth serial module", "3.3-5V", "35", "Module", "HC05", 4.00, "Layer 1 + 2", "Phone-to-device comms"),
    ("nRF52840", "BLE SoC", "BLE 5.0 + 802.15.4 SoC", "1.7-3.6V", "15", "AQFN-73", "nRF52840-Dongle", 9.00, "Layer 1 + 2", "Low power BLE link"),
    ("SIM7600G-H", "LTE Module", "4G LTE + GPS module", "3.4-4.2V", "2000", "LCC", "SIM7600-Board", 35.00, "Layer 1 Software", "Mobile data for voice AI"),
    ("LoRa Ra-02 SX1278", "LoRa", "Long range 433MHz LoRa module", "3.3V", "120", "Module", "Ra-02", 4.50, "Layer 2 Hardware", "Low power long range fallback"),

    # Audio Input
    ("INMP441", "Microphone", "I2S MEMS omnidirectional mic", "1.8-3.3V", "1.4", "LGA-6", "INMP441-Breakout", 3.00, "Layer 1 Software", "Voice input for Jarvis"),
    ("SPH0645LM4H", "Microphone", "I2S MEMS microphone", "1.62-3.6V", "0.6", "LGA-6", "SPH0645-Breakout", 2.50, "Layer 1 Software", "Alternative voice mic"),
    ("MAX9814", "Mic Amp", "Auto gain control mic amplifier", "2.7-5.5V", "3", "TDFN-8", "MAX9814-Breakout", 2.00, "Layer 1 Software", "Analog mic preamp"),

    # Display / Indicators (minimal, for dev)
    ("SSD1306 OLED 0.96\"", "Display", "128x64 I2C OLED display", "3.3-5V", "20", "Module", "SSD1306", 3.50, "Development", "Debug/status display"),
    ("WS2812B", "LED", "Addressable RGB LED", "5V", "60", "5050-SMD", "5050", 0.20, "Layer 2 Hardware", "Status indication"),
    ("KY-016 RGB LED", "LED", "Common cathode RGB LED module", "5V", "20", "Through-hole", "5mm-RGB", 0.30, "Development", "Debug indicator"),

    # Memory / Storage
    ("W25Q128", "Flash", "128Mbit SPI NOR Flash", "2.7-3.6V", "25", "SOIC-8", "SOIC8", 1.50, "Layer 2 Hardware", "Firmware/model storage"),
    ("MicroSD Module", "Storage", "SPI MicroSD card adapter", "3.3V", "100", "Module", "MicroSD-Breakout", 1.00, "Layer 1 + 2", "Logging and data storage"),

    # Logic / Interface
    ("TXS0108E", "Level Shifter", "8-bit bidirectional voltage translator", "1.2-3.6V / 1.65-5.5V", "50", "TSSOP-20", "TSSOP20", 1.50, "Layer 2 Hardware", "3.3V↔5V signal bridging"),
    ("PCA9685", "PWM Driver", "16-channel 12-bit PWM driver", "2.3-5.5V", "10", "TSSOP-28", "PCA9685-Breakout", 2.00, "Layer 2 Hardware", "Multi-motor/haptic control"),
    ("MCP23017", "IO Expander", "16-bit I2C GPIO expander", "1.8-5.5V", "1", "SOIC-28", "SOIC28", 1.80, "Layer 2 Hardware", "Extra GPIO via I2C"),
    ("74AHCT125", "Buffer", "Quad bus buffer, level shift 3.3→5V", "4.5-5.5V", "8", "SOIC-14", "SOIC14", 0.40, "Layer 2 Hardware", "Drive 5V WS2812B from 3.3V"),

    # Connectors / Passives
    ("USB-C Receptacle", "Connector", "USB Type-C female connector", "5V", "3000", "SMD", "USB-C-Mid-Mount", 0.60, "Layer 2 Hardware", "Charging + data port"),
    ("JST PH 2-pin", "Connector", "2mm pitch battery connector", "—", "2000", "Through-hole", "JST-PH-2", 0.30, "Layer 2 Hardware", "LiPo battery connection"),
    ("100nF MLCC 0402", "Capacitor", "Decoupling capacitor", "10V", "—", "0402", "0402", 0.02, "General", "Power decoupling"),
    ("10uF Electrolytic", "Capacitor", "Bulk decoupling capacitor", "16V", "—", "Through-hole", "Radial-5mm", 0.10, "General", "Bulk supply filtering"),
    ("10k Resistor 0402", "Resistor", "General purpose resistor", "—", "—", "0402", "0402", 0.01, "General", "Pull-up/pull-down"),
    ("1N4007 Diode", "Diode", "General purpose rectifier diode", "1000V", "1000", "DO-41", "DO41", 0.05, "General", "Reverse polarity protection"),
    ("SS34 Schottky", "Diode", "3A 40V Schottky rectifier", "40V", "3000", "SMA", "SMA", 0.15, "General", "Low drop power path"),
    ("AMS1117-3.3", "LDO", "1A 3.3V LDO regulator", "4.75-15V", "1000", "SOT-223", "SOT223", 0.30, "Layer 2 Hardware", "3.3V rail from 5V"),
    ("IRF540N MOSFET", "MOSFET", "N-channel power MOSFET 33A 100V", "100V", "33000", "TO-220", "TO220", 0.80, "Layer 2 Hardware", "Motor / load switching"),
    ("IRLML6244 MOSFET", "MOSFET", "N-channel logic level MOSFET", "20V", "6300", "SOT-23", "SOT23", 0.35, "Layer 2 Hardware", "Low-side switching from MCU"),
]

c.executemany('''INSERT INTO parts 
    (name, category, description, voltage_v, current_ma, package, footprint, cost_usd, compatibility, notes)
    VALUES (?,?,?,?,?,?,?,?,?,?)''', parts)

conn.commit()
print(f"Inserted {len(parts)} parts")

# Verify
c.execute("SELECT category, COUNT(*) FROM parts GROUP BY category")
for row in c.fetchall():
    print(row)

conn.close()
