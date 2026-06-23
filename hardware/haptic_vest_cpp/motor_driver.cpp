#include "motor_driver.h"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdexcept>
#include <sys/ioctl.h>
#include <unistd.h>

namespace vest {

// ── LinuxI2CBus ─────────────────────────────────────────────────────

LinuxI2CBus::LinuxI2CBus(int bus_num) {
    std::string path = "/dev/i2c-" + std::to_string(bus_num);
    fd_ = ::open(path.c_str(), O_RDWR);
    if (fd_ < 0)
        throw std::runtime_error("Failed to open " + path + ": " + std::strerror(errno));
}

LinuxI2CBus::~LinuxI2CBus() {
    if (fd_ >= 0) ::close(fd_);
}

void LinuxI2CBus::write_byte_data(uint8_t addr, uint8_t reg, uint8_t value) {
    uint8_t buf[2] = {reg, value};
    struct i2c_msg msg{};
    msg.addr  = addr;
    msg.flags = 0;
    msg.len   = 2;
    msg.buf   = buf;

    struct i2c_rdwr_ioctl_data packets{};
    packets.msgs  = &msg;
    packets.nmsgs = 1;

    if (::ioctl(fd_, I2C_RDWR, &packets) < 0)
        throw std::runtime_error(std::string("I2C write_byte_data failed: ") + std::strerror(errno));
}

void LinuxI2CBus::raw_write(uint8_t addr, const std::vector<uint8_t>& data) {
    struct i2c_msg msg{};
    msg.addr  = addr;
    msg.flags = 0;
    msg.len   = static_cast<uint16_t>(data.size());
    msg.buf   = const_cast<uint8_t*>(data.data());

    struct i2c_rdwr_ioctl_data packets{};
    packets.msgs  = &msg;
    packets.nmsgs = 1;

    if (::ioctl(fd_, I2C_RDWR, &packets) < 0)
        throw std::runtime_error(std::string("I2C raw_write failed: ") + std::strerror(errno));
}

// ── MockI2CBus ──────────────────────────────────────────────────────

void MockI2CBus::write_byte_data(uint8_t addr, uint8_t reg, uint8_t value) {
    byte_writes.push_back({addr, reg, value});
}

void MockI2CBus::raw_write(uint8_t addr, const std::vector<uint8_t>& data) {
    raw_writes.push_back({addr, data});
}

// ── Board helpers ───────────────────────────────────────────────────

uint8_t board_address(int board_idx) {
    if (board_idx < 0 || board_idx >= NUM_BOARDS)
        throw std::out_of_range("board_idx out of range");
    return BOARD_BASE_ADDR + static_cast<uint8_t>(board_idx);
}

std::pair<int, int> motor_to_board_channel(int motor_idx) {
    if (motor_idx < 0 || motor_idx >= NUM_MOTORS)
        throw std::out_of_range("motor_idx out of range");
    return {motor_idx / CHANNELS_PER_BOARD, motor_idx % CHANNELS_PER_BOARD};
}

void init_board(I2CBus& bus, int board_idx) {
    // PCA9685 init: sleep → set prescale → wake with AI + ALLCALL (bug #12 fix)
    uint8_t addr = board_address(board_idx);
    bus.write_byte_data(addr, REG_MODE1, MODE1_SLEEP | MODE1_ALLCALL);
    bus.write_byte_data(addr, REG_PRE_SCALE, PRESCALE_200HZ);
    bus.write_byte_data(addr, REG_MODE1, MODE1_AI | MODE1_ALLCALL);  // SLEEP=0, AI=1, ALLCALL=1
}

void init_all_boards(I2CBus& bus) {
    for (int i = 0; i < NUM_BOARDS; ++i)
        init_board(bus, i);
}

uint16_t intensity_to_off_count(int intensity) {
    return static_cast<uint16_t>(std::clamp(intensity, 0, PWM_MAX));
}

std::vector<uint8_t> build_board_payload(const uint16_t* channels_16) {
    // Leading register byte + 16 channels × 4 bytes = 65 bytes total.
    std::vector<uint8_t> payload;
    payload.reserve(1 + CHANNELS_PER_BOARD * 4);
    payload.push_back(REG_LED0_ON_L);  // auto-increment starts here

    for (int ch = 0; ch < CHANNELS_PER_BOARD; ++ch) {
        uint16_t off = intensity_to_off_count(static_cast<int>(channels_16[ch]));
        payload.push_back(0x00);                        // ON_L
        payload.push_back(0x00);                        // ON_H
        payload.push_back(off & 0xFF);                  // OFF_L
        payload.push_back((off >> 8) & 0x0F);           // OFF_H
    }
    return payload;
}

void update_board(I2CBus& bus, int board_idx, const uint16_t* channels_16) {
    uint8_t addr = board_address(board_idx);
    auto payload = build_board_payload(channels_16);
    bus.raw_write(addr, payload);
}

void update_all_motors(I2CBus& bus, const std::vector<uint16_t>& motor_intensities) {
    if (motor_intensities.size() != static_cast<size_t>(NUM_MOTORS))
        throw std::invalid_argument("update_all_motors: expected NUM_MOTORS values");

    for (int b = 0; b < NUM_BOARDS; ++b) {
        int start = b * CHANNELS_PER_BOARD;
        update_board(bus, b, &motor_intensities[start]);
    }
}

void all_off(I2CBus& bus) {
    uint16_t zeros[CHANNELS_PER_BOARD] = {};
    auto payload = build_board_payload(zeros);
    bus.raw_write(ALLCALL_ADDR, payload);
}

}  // namespace vest
