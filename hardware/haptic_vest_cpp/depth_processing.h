#pragma once
// Converts a fused depth grid (mm) into per-motor PWM intensity values.
// Preserves the invalid-depth masking fix: zero/invalid readings map to
// intensity 0 (no buzz), not maximum intensity.

#include <cstdint>
#include <vector>

#include "config.h"

namespace vest {

// depth_grid_mm: GRID_ROWS*GRID_COLS floats, 0 = invalid.
// Returns same-sized vector of uint16_t in [0, PWM_MAX].
std::vector<uint16_t> grid_to_intensity(const std::vector<float>& depth_grid_mm);

// Flatten intensity grid to motor array (already flat, but asserts size).
std::vector<uint16_t> grid_to_motor_array(const std::vector<uint16_t>& intensity_grid);

}  // namespace vest
