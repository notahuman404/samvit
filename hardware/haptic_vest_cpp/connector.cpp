#include "connector.h"

#include <chrono>
#include <cstdio>
#include <stdexcept>
#include <thread>

namespace vest {

static double now_s() {
    using clk = std::chrono::steady_clock;
    return std::chrono::duration<double>(clk::now().time_since_epoch()).count();
}

// ── HapticVestConnector ─────────────────────────────────────────────

HapticVestConnector::HapticVestConnector(
        std::unique_ptr<I2CBus> bus,
        std::unique_ptr<CameraSource> upper,
        std::unique_ptr<CameraSource> lower,
        float target_hz)
    : bus_(std::move(bus))
    , fusion_(std::move(upper), std::move(lower))
    , target_period_s_(1.0 / target_hz)
{}

void HapticVestConnector::initialise_hardware() {
    std::fprintf(stderr, "[connector] Initialising %d PCA9685 boards\n", NUM_BOARDS);
    init_all_boards(*bus_);
    all_off(*bus_);
    std::fprintf(stderr, "[connector] Hardware initialised — all motors OFF\n");
}

void HapticVestConnector::start_cameras() {
    std::fprintf(stderr, "[connector] Starting camera capture threads\n");
    fusion_.start();
}

void HapticVestConnector::stop() {
    stop_flag_ = true;
}

void HapticVestConnector::shutdown() {
    std::fprintf(stderr, "[connector] Shutting down\n");
    try { all_off(*bus_); } catch (...) {}
    try { fusion_.stop(); } catch (...) {}
    std::fprintf(stderr, "[connector] Shutdown complete\n");
}

void HapticVestConnector::emergency_stop() {
    std::fprintf(stderr, "[connector] EMERGENCY STOP\n");
    try { all_off(*bus_); } catch (...) {}
    stop();
}

void HapticVestConnector::run(int max_iterations) {
    initialise_hardware();
    start_cameras();

    std::fprintf(stderr, "[connector] Control loop started — target %.1f Hz (%.1f ms)\n",
                 1.0 / target_period_s_, target_period_s_ * 1000.0);

    try {
        while (!stop_flag_) {
            if (max_iterations >= 0 && stats.iterations >= max_iterations)
                break;

            double t0 = now_s();

            DepthGrid fused;
            try {
                fused = fusion_.get_fused_grid();
            } catch (const std::runtime_error&) {
                ++stats.frames_skipped;
                sleep_remainder(t0);
                continue;
            }

            auto intensity = grid_to_intensity(fused);
            auto motors = grid_to_motor_array(intensity);
            update_all_motors(*bus_, motors);

            double elapsed_ms = (now_s() - t0) * 1000.0;
            stats.record(elapsed_ms);
            ++stats.frames_processed;

            if (on_frame_) on_frame_(fused, intensity, stats);

            sleep_remainder(t0);
        }
    } catch (...) {
        shutdown();
        throw;
    }
    shutdown();
}

void HapticVestConnector::sleep_remainder(double loop_start_s) const {
    double elapsed = now_s() - loop_start_s;
    double remaining = target_period_s_ - elapsed;
    if (remaining > 0.0)
        std::this_thread::sleep_for(std::chrono::duration<double>(remaining));
}

// ── Factories ───────────────────────────────────────────────────────

std::unique_ptr<HapticVestConnector> build_real(
        const std::string& upper_serial,
        const std::string& lower_serial,
        int bus_num,
        float target_hz) {
    auto bus   = std::make_unique<LinuxI2CBus>(bus_num);
    auto upper = std::make_unique<RealSenseCamera>(upper_serial, "upper_d435i");
    auto lower = std::make_unique<RealSenseCamera>(lower_serial, "lower_d435i");
    return std::make_unique<HapticVestConnector>(
        std::move(bus), std::move(upper), std::move(lower), target_hz);
}

std::unique_ptr<HapticVestConnector> build_mock(float target_hz) {
    auto bus   = std::make_unique<MockI2CBus>();
    auto upper = std::make_unique<MockCamera>("mock_upper", 1500);
    auto lower = std::make_unique<MockCamera>("mock_lower", 1500);
    return std::make_unique<HapticVestConnector>(
        std::move(bus), std::move(upper), std::move(lower), target_hz);
}

}  // namespace vest
