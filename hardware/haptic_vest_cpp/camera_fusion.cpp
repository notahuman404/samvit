#include "camera_fusion.h"

#include <algorithm>
#include <chrono>
#include <cstring>
#include <numeric>
#include <stdexcept>

namespace vest {

// ── RealSenseCamera ─────────────────────────────────────────────────

RealSenseCamera::RealSenseCamera(const std::string& serial, const std::string& name)
    : name_(name), serial_(serial) {}

RealSenseCamera::~RealSenseCamera() { stop(); }

void RealSenseCamera::start() {
    rs2::config cfg;
    if (!serial_.empty()) cfg.enable_device(serial_);
    cfg.enable_stream(RS2_STREAM_DEPTH, 0, 0, 0, RS2_FORMAT_Z16, 30);
    pipeline_.start(cfg);

    running_ = true;
    thread_ = std::thread(&RealSenseCamera::capture_loop, this);
}

void RealSenseCamera::stop() {
    running_ = false;
    if (thread_.joinable()) thread_.join();
    try { pipeline_.stop(); } catch (...) {}
}

DepthGrid RealSenseCamera::read_grid() {
    std::lock_guard<std::mutex> lk(mtx_);
    if (!has_frame_)
        throw std::runtime_error(name_ + ": no frame captured yet");
    return latest_grid_;
}

void RealSenseCamera::capture_loop() {
    while (running_) {
        rs2::frameset frames;
        try {
            frames = pipeline_.wait_for_frames(1000);
        } catch (...) {
            continue;  // timeout / dropped frame — retry
        }
        auto depth = frames.get_depth_frame();
        if (!depth) continue;

        int w = depth.get_width();
        int h = depth.get_height();
        auto* data = reinterpret_cast<const uint16_t*>(depth.get_data());

        DepthGrid grid = downsample(data, w, h);

        {
            std::lock_guard<std::mutex> lk(mtx_);
            latest_grid_ = std::move(grid);
            has_frame_ = true;
        }
    }
}

DepthGrid RealSenseCamera::downsample(const uint16_t* data, int w, int h) {
    // Block-average raw depth frame down to GRID_ROWS x GRID_COLS.
    // Zero (invalid) pixels excluded from the average for each block.
    DepthGrid grid(GRID_ROWS * GRID_COLS, 0.0f);

    for (int r = 0; r < GRID_ROWS; ++r) {
        int r0 = r * h / GRID_ROWS;
        int r1 = (r + 1) * h / GRID_ROWS;
        for (int c = 0; c < GRID_COLS; ++c) {
            int c0 = c * w / GRID_COLS;
            int c1 = (c + 1) * w / GRID_COLS;

            double sum = 0.0;
            int count = 0;
            for (int y = r0; y < r1; ++y) {
                for (int x = c0; x < c1; ++x) {
                    uint16_t val = data[y * w + x];
                    if (val > 0) { sum += val; ++count; }
                }
            }
            grid[r * GRID_COLS + c] = (count > 0) ? static_cast<float>(sum / count) : 0.0f;
        }
    }
    return grid;
}

// ── MockCamera ──────────────────────────────────────────────────────

MockCamera::MockCamera(const std::string& name, uint16_t static_mm)
    : name_(name), static_mm_(static_mm) {}

void MockCamera::start() { started_ = true; }
void MockCamera::stop()  { started_ = false; }

DepthGrid MockCamera::read_grid() {
    if (!started_) throw std::runtime_error(name_ + ": start() must be called first");
    return DepthGrid(GRID_ROWS * GRID_COLS, static_cast<float>(static_mm_));
}

// ── Fusion ──────────────────────────────────────────────────────────

DepthGrid fuse_depth_grids(const DepthGrid& upper, const DepthGrid& lower) {
    if (upper.size() != GRID_ROWS * GRID_COLS || lower.size() != GRID_ROWS * GRID_COLS)
        throw std::invalid_argument("fuse_depth_grids: grids must be GRID_ROWS*GRID_COLS");

    DepthGrid fused(GRID_ROWS * GRID_COLS, 0.0f);

    for (int r = 0; r < GRID_ROWS; ++r) {
        bool upper_covers = r < UPPER_CAM_ROW_END;
        bool lower_covers = r >= LOWER_CAM_ROW_START;

        for (int c = 0; c < GRID_COLS; ++c) {
            int idx = r * GRID_COLS + c;
            float u = upper[idx];
            float l = lower[idx];

            if (upper_covers && lower_covers) {
                // Overlap: min-distance, treating 0 as "no data"
                bool u_ok = u > 0.0f;
                bool l_ok = l > 0.0f;
                if (u_ok && l_ok)       fused[idx] = std::min(u, l);
                else if (u_ok)          fused[idx] = u;
                else if (l_ok)          fused[idx] = l;
                // else stays 0
            } else if (upper_covers) {
                fused[idx] = u;
            } else if (lower_covers) {
                fused[idx] = l;
            }
        }
    }
    return fused;
}

// ── DualCameraFusion ────────────────────────────────────────────────

DualCameraFusion::DualCameraFusion(std::unique_ptr<CameraSource> upper,
                                   std::unique_ptr<CameraSource> lower)
    : upper_(std::move(upper)), lower_(std::move(lower)) {}

void DualCameraFusion::start() { upper_->start(); lower_->start(); }
void DualCameraFusion::stop()  { upper_->stop();  lower_->stop();  }

DepthGrid DualCameraFusion::get_fused_grid() {
    return fuse_depth_grids(upper_->read_grid(), lower_->read_grid());
}

}  // namespace vest
