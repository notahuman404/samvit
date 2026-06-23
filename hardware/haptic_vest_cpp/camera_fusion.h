#pragma once
// Dual D435i depth-camera capture + fusion for the haptic vest pipeline.
// Each camera runs in its own background thread, continuously writing its
// latest depth grid into a shared, lock-protected buffer.

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <librealsense2/rs.hpp>

#include "config.h"

namespace vest {

// A GRID_ROWS x GRID_COLS float grid (row-major), values in mm, 0 = invalid.
using DepthGrid = std::vector<float>;

// ── Camera abstraction ──────────────────────────────────────────────

class CameraSource {
public:
    virtual ~CameraSource() = default;
    virtual void start() = 0;
    virtual void stop()  = 0;
    // Returns a GRID_ROWS*GRID_COLS grid (already downsampled).
    // Throws std::runtime_error if no frame captured yet.
    virtual DepthGrid read_grid() = 0;
};

// ── RealSense D435i ─────────────────────────────────────────────────

class RealSenseCamera : public CameraSource {
public:
    explicit RealSenseCamera(const std::string& serial = "", const std::string& name = "camera");
    ~RealSenseCamera() override;

    void start() override;
    void stop()  override;
    DepthGrid read_grid() override;

private:
    void capture_loop();
    static DepthGrid downsample(const uint16_t* data, int w, int h);

    std::string name_;
    std::string serial_;
    rs2::pipeline pipeline_;
    std::thread thread_;
    std::atomic<bool> running_{false};
    std::mutex mtx_;
    DepthGrid latest_grid_;
    bool has_frame_{false};
};

// ── Mock camera (no hardware) ───────────────────────────────────────

class MockCamera : public CameraSource {
public:
    explicit MockCamera(const std::string& name = "mock", uint16_t static_mm = 1500);
    void start() override;
    void stop()  override;
    DepthGrid read_grid() override;
private:
    std::string name_;
    uint16_t static_mm_;
    bool started_{false};
};

// ── Fusion ──────────────────────────────────────────────────────────

// Fuse two grids: upper-only rows, overlap (min-distance), lower-only rows.
DepthGrid fuse_depth_grids(const DepthGrid& upper, const DepthGrid& lower);

// Convenience wrapper owning two cameras.
class DualCameraFusion {
public:
    DualCameraFusion(std::unique_ptr<CameraSource> upper,
                     std::unique_ptr<CameraSource> lower);
    void start();
    void stop();
    DepthGrid get_fused_grid();
private:
    std::unique_ptr<CameraSource> upper_;
    std::unique_ptr<CameraSource> lower_;
};

}  // namespace vest
