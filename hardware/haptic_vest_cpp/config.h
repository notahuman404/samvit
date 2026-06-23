#pragma once
// Shared configuration constants for the haptic vest pipeline.
// Mirrors FirmwareSamvit/config.py — all hardware-specific values live here.

#include <cstdint>

namespace vest {

// ── Grid / Motor Layout ─────────────────────────────────────────────
constexpr int GRID_ROWS         = 12;
constexpr int GRID_COLS         = 12;
constexpr int NUM_MOTORS        = GRID_ROWS * GRID_COLS;  // 144

// ── PCA9685 Board Topology ──────────────────────────────────────────
constexpr int NUM_BOARDS        = 9;
constexpr int CHANNELS_PER_BOARD = 16;
constexpr uint8_t BOARD_BASE_ADDR = 0x40;                 // PCA1=0x40 … PCA9=0x48
constexpr uint8_t ALLCALL_ADDR    = 0x70;                 // broadcast address
constexpr int I2C_BUS_NUM        = 1;                     // /dev/i2c-1

// ── PCA9685 Registers ───────────────────────────────────────────────
constexpr uint8_t REG_MODE1       = 0x00;
constexpr uint8_t REG_MODE2       = 0x01;
constexpr uint8_t REG_LED0_ON_L   = 0x06;
constexpr uint8_t REG_ALL_LED_ON_L = 0xFA;
constexpr uint8_t REG_PRE_SCALE   = 0xFE;

// MODE1 bit masks
constexpr uint8_t MODE1_ALLCALL   = 0x01;
constexpr uint8_t MODE1_SLEEP     = 0x10;
constexpr uint8_t MODE1_AI        = 0x20;  // auto-increment

// PRE_SCALE for ~200 Hz PWM
constexpr uint8_t PRESCALE_200HZ  = 0x1E;

// ── PWM / Intensity ─────────────────────────────────────────────────
constexpr int PWM_MAX             = 4095;  // 12-bit

// ── Depth-to-Intensity Mapping ──────────────────────────────────────
constexpr float MIN_DIST_MM       = 300.0f;
constexpr float MAX_DIST_MM       = 3000.0f;

// ── Control Loop ────────────────────────────────────────────────────
constexpr float TARGET_LOOP_HZ    = 20.0f;  // 50 ms period

// ── Camera Overlap Layout ───────────────────────────────────────────
// Upper camera covers rows 0..7, lower covers rows 4..11, overlap = [4,8)
constexpr int UPPER_CAM_ROW_END   = 8;
constexpr int LOWER_CAM_ROW_START = 4;

}  // namespace vest
