#pragma once
// Master orchestrator: wires cameras → fusion → depth processing → motor I2C.

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <vector>

#include "camera_fusion.h"
#include "config.h"
#include "depth_processing.h"
#include "motor_driver.h"

namespace vest {

struct LoopStats {
    int iterations       = 0;
    int frames_processed = 0;
    int frames_skipped   = 0;
    double last_loop_ms  = 0.0;
    double max_loop_ms   = 0.0;
    double avg_loop_ms   = 0.0;
private:
    double total_ms_     = 0.0;
    friend class HapticVestConnector;
public:
    void record(double elapsed_ms) {
        ++iterations;
        last_loop_ms = elapsed_ms;
        total_ms_ += elapsed_ms;
        avg_loop_ms = total_ms_ / iterations;
        if (elapsed_ms > max_loop_ms) max_loop_ms = elapsed_ms;
    }
};

// Optional per-frame callback signature.
using FrameCallback = std::function<void(const DepthGrid&, const std::vector<uint16_t>&, const LoopStats&)>;

class HapticVestConnector {
public:
    HapticVestConnector(std::unique_ptr<I2CBus> bus,
                        std::unique_ptr<CameraSource> upper,
                        std::unique_ptr<CameraSource> lower,
                        float target_hz = TARGET_LOOP_HZ);

    // Lifecycle
    void initialise_hardware();
    void start_cameras();
    void run(int max_iterations = -1);  // -1 = run forever until stop()
    void stop();
    void shutdown();
    void emergency_stop();

    void set_frame_callback(FrameCallback cb) { on_frame_ = std::move(cb); }

    LoopStats stats;

private:
    void sleep_remainder(double loop_start_s) const;

    std::unique_ptr<I2CBus> bus_;
    DualCameraFusion fusion_;
    double target_period_s_;
    FrameCallback on_frame_;
    std::atomic<bool> stop_flag_{false};
};

// Factory helpers
std::unique_ptr<HapticVestConnector> build_real(
    const std::string& upper_serial = "",
    const std::string& lower_serial = "",
    int bus_num = I2C_BUS_NUM,
    float target_hz = TARGET_LOOP_HZ);

std::unique_ptr<HapticVestConnector> build_mock(float target_hz = TARGET_LOOP_HZ);

}  // namespace vest
