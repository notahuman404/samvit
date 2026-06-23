#include <csignal>
#include <cstdio>
#include <cstring>
#include <string>

#include "connector.h"

static vest::HapticVestConnector* g_connector = nullptr;

static void signal_handler(int sig) {
    std::fprintf(stderr, "\n[main] Signal %d received — stopping\n", sig);
    if (g_connector) g_connector->stop();
}

static void print_usage(const char* prog) {
    std::fprintf(stderr,
        "Usage: %s [OPTIONS]\n"
        "\n"
        "Haptic vest controller — full pipeline from cameras to motors.\n"
        "\n"
        "Options:\n"
        "  --mock              Use mock cameras and I2C (no hardware needed)\n"
        "  --hz <rate>         Target loop rate in Hz (default 20)\n"
        "  --upper-serial <s>  Serial number of upper D435i camera\n"
        "  --lower-serial <s>  Serial number of lower D435i camera\n"
        "  -n, --iterations N  Stop after N iterations (default: run forever)\n"
        "  -v, --verbose       Print per-frame stats every 20 iterations\n"
        "  -h, --help          Show this help\n",
        prog);
}

int main(int argc, char* argv[]) {
    bool mock = false;
    bool verbose = false;
    float hz = vest::TARGET_LOOP_HZ;
    int iterations = -1;
    std::string upper_serial, lower_serial;

    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--mock") == 0) {
            mock = true;
        } else if (std::strcmp(argv[i], "--hz") == 0 && i + 1 < argc) {
            hz = std::stof(argv[++i]);
        } else if (std::strcmp(argv[i], "--upper-serial") == 0 && i + 1 < argc) {
            upper_serial = argv[++i];
        } else if (std::strcmp(argv[i], "--lower-serial") == 0 && i + 1 < argc) {
            lower_serial = argv[++i];
        } else if ((std::strcmp(argv[i], "-n") == 0 || std::strcmp(argv[i], "--iterations") == 0) && i + 1 < argc) {
            iterations = std::stoi(argv[++i]);
        } else if (std::strcmp(argv[i], "-v") == 0 || std::strcmp(argv[i], "--verbose") == 0) {
            verbose = true;
        } else if (std::strcmp(argv[i], "-h") == 0 || std::strcmp(argv[i], "--help") == 0) {
            print_usage(argv[0]);
            return 0;
        } else {
            std::fprintf(stderr, "Unknown argument: %s\n", argv[i]);
            print_usage(argv[0]);
            return 1;
        }
    }

    std::unique_ptr<vest::HapticVestConnector> connector;
    if (mock) {
        std::fprintf(stderr, "[main] Building MOCK connector (no hardware)\n");
        connector = vest::build_mock(hz);
    } else {
        std::fprintf(stderr, "[main] Building REAL connector (hardware mode)\n");
        connector = vest::build_real(upper_serial, lower_serial, vest::I2C_BUS_NUM, hz);
    }

    g_connector = connector.get();
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    if (verbose) {
        connector->set_frame_callback(
            [](const vest::DepthGrid&, const std::vector<uint16_t>&, const vest::LoopStats& s) {
                if (s.iterations % 20 == 0) {
                    std::fprintf(stderr,
                        "[stats] iter=%d  processed=%d  skipped=%d  "
                        "loop=%.1f/%.1f/%.1f ms (last/avg/max)\n",
                        s.iterations, s.frames_processed, s.frames_skipped,
                        s.last_loop_ms, s.avg_loop_ms, s.max_loop_ms);
                }
            });
    }

    std::fprintf(stderr, "[main] Starting haptic vest pipeline\n");
    connector->run(iterations);

    std::fprintf(stderr, "[main] Final stats: iter=%d processed=%d skipped=%d "
                 "avg=%.2f ms max=%.2f ms\n",
                 connector->stats.iterations,
                 connector->stats.frames_processed,
                 connector->stats.frames_skipped,
                 connector->stats.avg_loop_ms,
                 connector->stats.max_loop_ms);

    return 0;
}
