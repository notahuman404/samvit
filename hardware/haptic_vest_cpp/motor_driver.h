#pragma once
// PCA9685 driver for the 9-board motor grid.
// Uses raw I2C (I2C_RDWR ioctl) — no SMBus 32-byte cap (bug #11 fix).
// Keeps ALLCALL enabled in MODE1 (bug #12 fix).

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

#include "config.h"

namespace vest {

// ── I2C bus abstraction ─────────────────────────────────────────────

class I2CBus {
public:
    virtual ~I2CBus() = default;
    virtual void write_byte_data(uint8_t addr, uint8_t reg, uint8_t value) = 0;
    virtual void raw_write(uint8_t addr, const std::vector<uint8_t>& data) = 0;
};

// Real I2C via /dev/i2c-* and I2C_RDWR ioctl.
class LinuxI2CBus : public I2CBus {
public:
    explicit LinuxI2CBus(int bus_num = I2C_BUS_NUM);
    ~LinuxI2CBus() override;
    void write_byte_data(uint8_t addr, uint8_t reg, uint8_t value) override;
    void raw_write(uint8_t addr, const std::vector<uint8_t>& data) override;
private:
    int fd_{-1};
};

// Mock I2C — records writes for testing.
class MockI2CBus : public I2CBus {
public:
    void write_byte_data(uint8_t addr, uint8_t reg, uint8_t value) override;
    void raw_write(uint8_t addr, const std::vector<uint8_t>& data) override;

    struct ByteWrite { uint8_t addr, reg, value; };
    struct RawWrite  { uint8_t addr; std::vector<uint8_t> data; };
    std::vector<ByteWrite> byte_writes;
    std::vector<RawWrite>  raw_writes;
};

// ── Board helpers ───────────────────────────────────────────────────

uint8_t board_address(int board_idx);
std::pair<int, int> motor_to_board_channel(int motor_idx);

void init_board(I2CBus& bus, int board_idx);
void init_all_boards(I2CBus& bus);

uint16_t intensity_to_off_count(int intensity);
std::vector<uint8_t> build_board_payload(const uint16_t* channels_16);
void update_board(I2CBus& bus, int board_idx, const uint16_t* channels_16);
void update_all_motors(I2CBus& bus, const std::vector<uint16_t>& motor_intensities);
void all_off(I2CBus& bus);

}  // namespace vest
