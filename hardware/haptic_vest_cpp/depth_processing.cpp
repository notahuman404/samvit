#include "depth_processing.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace vest {

std::vector<uint16_t> grid_to_intensity(const std::vector<float>& depth_grid_mm) {
    const size_t n = GRID_ROWS * GRID_COLS;
    if (depth_grid_mm.size() != n)
        throw std::invalid_argument("grid_to_intensity: unexpected grid size");

    std::vector<uint16_t> intensity(n, 0);
    const float range = MAX_DIST_MM - MIN_DIST_MM;

    for (size_t i = 0; i < n; ++i) {
        float d = depth_grid_mm[i];
        if (d <= 0.0f) continue;  // invalid → intensity stays 0 (bug #13 fix)

        float clamped = std::clamp(d, MIN_DIST_MM, MAX_DIST_MM);
        float norm = (MAX_DIST_MM - clamped) / range;
        float val = norm * norm * static_cast<float>(PWM_MAX);
        intensity[i] = static_cast<uint16_t>(std::clamp(val, 0.0f, static_cast<float>(PWM_MAX)));
    }
    return intensity;
}

std::vector<uint16_t> grid_to_motor_array(const std::vector<uint16_t>& intensity_grid) {
    if (intensity_grid.size() != static_cast<size_t>(GRID_ROWS * GRID_COLS))
        throw std::invalid_argument("grid_to_motor_array: expected GRID_ROWS*GRID_COLS elements");
    return intensity_grid;  // already flat row-major
}

}  // namespace vest
