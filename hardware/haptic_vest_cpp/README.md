# Haptic Vest C++ — Production Port

C++ port of the Python haptic vest control pipeline (Raspberry Pi 4, dual Intel RealSense D435i, 9× PCA9685, 144 ERM motors).

## Building (on Raspberry Pi 4 / ARM Linux)

```bash
sudo apt install cmake librealsense2-dev
mkdir build && cd build
cmake ..
make -j4
```

The binary is `build/haptic_vest`.

## Usage

```bash
# Real hardware (Pi with cameras + I2C boards):
./haptic_vest

# Mock mode (no hardware):
./haptic_vest --mock

# Options:
./haptic_vest --mock -n 100 -v          # 100 iterations, verbose stats
./haptic_vest --hz 30                   # 30 Hz loop rate
./haptic_vest --upper-serial XXXX --lower-serial YYYY
```

## File Layout

| File | Description |
|---|---|
| `config.h` | All shared constants (grid size, I2C addresses, PCA9685 registers, thresholds) |
| `camera_fusion.h/.cpp` | Threaded dual D435i capture + min-distance overlap fusion |
| `depth_processing.h/.cpp` | Depth grid → motor intensity mapping with invalid-pixel masking |
| `motor_driver.h/.cpp` | PCA9685 I2C driver using raw `I2C_RDWR` ioctl (no SMBus 32-byte cap) |
| `connector.h/.cpp` | Master orchestrator: init → loop → shutdown |
| `main.cpp` | CLI entry point with signal handling |
| `CMakeLists.txt` | Build configuration |
| `compiled/` | Pre-compiled binary (built on x86_64 Ubuntu 22.04; rebuild on Pi for ARM) |

## Behavioral Differences from Python Version

1. **Downsampling moved into CameraSource**: In Python, `DualCameraFusion.get_fused_grid()` calls `_downsample_to_grid()` on each raw frame. In C++, each `RealSenseCamera` downsamples inside its capture thread (before writing to the shared buffer), so the main loop never touches raw high-resolution frames. This reduces lock contention and avoids copying large frames across threads.

2. **No `pyrealsense2` wrapper — uses librealsense2 C++ API directly**: Same SDK, just the native C++ bindings instead of the Python wrapper. Behavior is identical.

3. **I2C uses `I2C_RDWR` ioctl directly**: Python used `smbus2.i2c_msg.write()` which internally does the same ioctl. The C++ version calls `ioctl(fd, I2C_RDWR, ...)` directly — identical wire behavior, no library dependency.

4. **Performance**: Mock-mode loop time is ~0.03 ms (vs ~2.75 ms in Python). Real-hardware I2C timing will be identical (I2C bus speed is the bottleneck, not CPU).

5. **No `--diag` mode**: The Python `connector.py` had a `--diag` flag that scanned the I2C bus. The C++ port omits this — use `i2cdetect -y 1` directly on the Pi instead.

6. **Signal handling**: Uses `std::signal(SIGINT/SIGTERM)` for clean shutdown. Same behavior as the Python version's signal handler.

## Note on Pre-compiled Binary

The binary in `compiled/` was built on **x86_64 Ubuntu 22.04** (Devin's build environment). You must **rebuild on your Raspberry Pi 4** (ARM) for it to run on the actual hardware. The source code and CMakeLists.txt are ready for a Pi build with no changes needed.
