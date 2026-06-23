# Samvit 👁️🌉

> *Samvit (संवित्) — Sanskrit for "Conscious Awareness"*

> **"We don't just navigate the system for blind users — we navigate the world."**

An AI-powered assistive system that helps visually impaired individuals independently find, understand, and physically reach public services — starting with healthcare.

---

## 🧩 The Problem

Visually impaired individuals face **two walls**, not one:

1. They can't independently navigate apps or screens to find nearby healthcare, benefits, or public services
2. Even when someone helps them find it — **they still can't get there alone**

Existing solutions solve neither problem completely. Screen readers tell you *what's on screen* but don't help you *understand* or *act*. Navigation apps help sighted people. Nothing bridges both worlds.

---

## 💡 The Solution

Samvit is a **two-layer assistive system** combining AI software and sensory hardware:

### 🧠 Layer 1 — Software (The Brain)
A Jarvis-like voice AI that understands your phone screen and the web on your behalf.

- Say *"Find me the nearest free clinic"* — it searches, reads, filters, and explains results in plain language
- Guides users through benefits eligibility questions conversationally
- Makes phone calls on command (*"Call the clinic and ask if they take walk-ins"*)
- Reads and interprets any screen content aloud with context, not just raw text

### 👁️ Layer 2 — Hardware (The Game-Changer)
A wearable sensory substitution device inspired by Neil Harbisson's pioneering work in human sensory extension.

- Uses **heatmapping** to translate the visual environment into sensory feedback
- Converts spatial information (obstacles, paths, destinations) into perceivable signals
- Allows the user to **physically navigate** to their destination — independently, without a guide
- Works in real-time alongside the software layer for end-to-end assistance

---

## 🎯 Challenge Alignment

**Brief 4 — Public Service, Direction A: Benefits Navigator**

| Requirement | Samvit |
|---|---|
| Help users interpret rules and reduce confusion | ✅ Voice AI simplifies eligibility criteria in plain language |
| Translate criteria into plain language | ✅ Reads and contextualizes screen content aloud |
| Ask questions to guide users through their situation | ✅ Conversational AI walks users step by step |
| Healthcare as a primary use case | ✅ Core use case of the product |
| Go beyond a directory — help users actually act | ✅ Hardware ensures they can physically reach the service |

---

## 🏗️ Architecture Overview

```
User Voice Input
      │
      ▼
┌─────────────────────┐
│   Voice AI Layer    │  ← Understands intent, reads screen, navigates web
│  (Jarvis Engine)    │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Screen & Web       │  ← Finds clinics, reads eligibility, makes calls
│  Understanding      │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Hardware Layer     │  ← Heatmap-based sensory substitution wearable
│  (Sensory Bridge)   │    guides user to physical destination
└─────────────────────┘
```

---

## 🔬 Inspiration

- **Neil Harbisson** — Pioneer of sensory substitution; the first human officially recognized as a cyborg, who perceives color through sound via his "eyeborg" antenna
- **Sensory Substitution Research** — The science of routing one sense's information through another (e.g., visual data → tactile or auditory feedback)
- **Heatmap Navigation** — Using thermal/spatial density mapping to encode environmental information into perceivable signals

---

## 🔩 Hardware Validation & Testing

Our hardware pipeline — from depth sensing through motor actuation — has been validated through a **datasheet-driven simulation** that goes well beyond simple mocking. Rather than stubbing out I2C calls and calling it tested, we built physically-accurate models of every component in the signal chain and ran them against the actual firmware logic.

### What we validated

| Component | Validation Method |
|---|---|
| Intel RealSense D435i depth cameras | Noise model fitted to Intel's published accuracy data: quadratic noise growth (σ = 2mm at 1m, 8mm at 2m, 32mm at 4m), distance-dependent dropout rates, edge artifacts, flying pixel simulation |
| NXP PCA9685 motor drivers (×9) | Full I2C protocol verification against datasheet Rev.4: init sequence timing, register payload format, ALLCALL broadcast, 65-byte raw writes (bypassing SMBus 32-byte cap) |
| Dual-camera depth fusion | Min-distance overlap logic with statistically-verified output across 100+ noisy frames. Invalid readings (0) never corrupt fusion — verified with 50,000 samples |
| 144-motor grid (12×12) | Bijective channel mapping (144 → 9 boards × 16 channels), single-motor precision addressing, rapid on/off cycling stability |
| I2C bus (BCM2711 BSC, 400kHz) | Timing budget calculated from first principles (9 clocks/byte × 400kHz), bus utilization analysis, clock stretching model |

### Fault injection (not just happy-path)

The simulation injects real hardware failures and verifies graceful degradation:

- **Board failure isolation** — one PCA9685 dies, the other 8 continue operating (128/144 motors still active)
- **Brown-out detection** — supply drops below 2.7V, bus operations halt safely before corrupting registers
- **Stuck I2C bus** — SCL held low (common with loose connections), detected and reported within one transaction attempt
- **Bus contention (NACK storms)** — 5% random NACK rate with retry logic achieves 100% frame delivery
- **Thermal performance** — I2C transactions validated at 70°C operating temperature with oscillator drift model

### Stress testing

- **1,000 continuous frames** with dynamically moving obstacles — zero errors, 0.28ms avg loop time (99.4% headroom on 50ms budget)
- **500 rapid on/off cycles** — verifies register write stability under worst-case duty cycling
- **Bug regression suite** — 3 previously-identified firmware bugs verified fixed (SMBus cap #11, ALLCALL bit #12, invalid-depth mapping #13)

### How to run

```bash
cd hardware/tests
python hil_simulation.py --verbose
```

Outputs a structured JSON report (`hil_results.json`) suitable for CI integration, with per-test metrics, timing data, and pass/fail status.

---

## 🚀 MVP Scope

**Phase 1 — Software MVP**
- [x] Voice-activated screen reader with contextual understanding
- [x] Healthcare clinic finder with eligibility pre-screening
- [x] Conversational benefits guidance flow
- [x] One-tap call routing to clinics/services
- [x] Agentic flow: multi-step goal execution with voice control

**Phase 2 — Hardware Prototype**
- [x] Wearable sensor unit (C++ firmware, ARM-compiled)
- [x] Heatmap generation from dual depth cameras
- [x] Sensory feedback output (144 vibration motors, 12×12 grid)
- [x] Integration with software navigation layer
- [x] Hardware validation suite (22 tests, datasheet-verified)

---

## 👥 Target Users

- Visually impaired individuals (partial or full vision loss)
- Blind individuals navigating public services independently
- Families assisting visually impaired members remotely
- Community organizations supporting disability access

---

## 🌍 Impact

Every other Benefits Navigator is just an app. Samvit goes further:

- **Finds** the nearest relevant service
- **Explains** eligibility in plain language
- **Calls** on your behalf
- **Gets you there** — physically, independently

This isn't just accessibility software. It's **independence as a service.**

---

## 🛠️ Running Locally

### Prerequisites

- [Android Studio](https://developer.android.com/studio) (Ladybug or newer recommended)
- Python 3.10+ (for backend)
- A [Gemini API key](https://aistudio.google.com/apikey) (free tier works)
- A `google-services.json` from your Firebase project (for Firebase AI SDK)

### Step 1 — Clone the repo

```bash
git clone https://github.com/mrehan0516/Vision_Guide.git
cd Vision_Guide
```

### Step 2 — Set up the Gemini API key

Create a `.env` file in the project root (same level as `settings.gradle.kts`):

```bash
cp .env.example .env
```

Edit `.env` and replace the placeholder with your real key:

```
GEMINI_API_KEY=your_actual_gemini_api_key_here
```

This key is used by both the Android app (via the Secrets Gradle Plugin) and the Python backend.

### Step 3 — Firebase setup

Place your `google-services.json` file in the `app/` directory. You can get this from your [Firebase Console](https://console.firebase.google.com/) → Project Settings → General → Your Apps → Download `google-services.json`.

### Step 4 — Run the Android app

1. Open Android Studio
2. Select **Open** and choose the `Vision_Guide` directory
3. Let Gradle sync complete (it will download all dependencies automatically)
4. If you see a signing config error, remove this line from `app/build.gradle.kts`:
   ```
   signingConfig = signingConfigs.getByName("debugConfig")
   ```
5. Connect a physical Android device (recommended — accessibility features work best on real devices) or start an emulator
6. Click **Run** (green play button) or press `Shift+F10`

> **Note:** The app uses a `MockVisionPilotClient` by default, so it works without the backend running. The mock simulates the full agent plan → step → confirm flow for demo purposes.

### Step 5 — Run the backend (optional, for full Gemini-powered agent)

```bash
cd backend
pip install fastapi uvicorn google-generativeai pydantic
```

Set the API key in your terminal:

```bash
export GEMINI_API_KEY=your_actual_gemini_api_key_here
```

Start the server:

```bash
python main.py
```

The backend runs on `http://localhost:8000`. API docs are available at `http://localhost:8000/docs`.

### Step 6 — Run the hardware simulation (no hardware needed)

```bash
cd hardware/tests
python hil_simulation.py --verbose
```

This runs the full 22-test HIL validation suite and outputs results to `hil_results.json`.

### Quick reference — what runs where

| Component | How to run | Needs hardware? |
|---|---|---|
| Android app (mock mode) | Android Studio → Run | No (phone or emulator) |
| Android app (live agent) | Android Studio → Run + backend on | No (phone + laptop) |
| Backend API | `python main.py` | No |
| Hardware simulation | `python hil_simulation.py` | No |
| Haptic vest firmware | `./haptic_vest` (on RPi4) | Yes (RPi4 + cameras + motors) |

---

## 🙏 Credits & Acknowledgments

### AI Tools Used in Development

| Tool | Role | Tier |
|---|---|---|
| **Google Gemini 2.0 Flash** | Core AI backbone — powers the agentic reasoning engine, screen understanding, multimodal vision (screenshot OCR), goal decomposition, and step planning | Free tier |
| **Devin** (by Cognition AI) | AI software engineer — built the C++ firmware port, HIL simulation suite, agentic backend (`agent.py`), and Android integration | Free tier |
| **Claude** (by Anthropic) | AI assistant — helped with architecture planning, code review, and documentation | Free tier |

### Open-Source Libraries & Frameworks

**Android App:**
| Library | Purpose |
|---|---|
| [Jetpack Compose](https://developer.android.com/jetpack/compose) | Declarative UI framework |
| [Firebase AI](https://firebase.google.com/docs/vertex-ai) | Gemini model access via Firebase |
| [Retrofit](https://square.github.io/retrofit/) + [OkHttp](https://square.github.io/okhttp/) | HTTP client for backend communication |
| [Moshi](https://github.com/square/moshi) | JSON serialization |
| [CameraX](https://developer.android.com/training/camerax) | Camera capture pipeline |
| [Kotlin Coroutines](https://kotlinlang.org/docs/coroutines-overview.html) | Async/concurrent programming |
| [Accompanist Permissions](https://google.github.io/accompanist/permissions/) | Runtime permission handling |
| [Room](https://developer.android.com/training/data-storage/room) | Local database |
| [Navigation Compose](https://developer.android.com/jetpack/compose/navigation) | In-app navigation |

**Backend (Python):**
| Library | Purpose |
|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | REST API framework |
| [google-generativeai](https://github.com/google-gemini/generative-ai-python) | Gemini API client |
| [Pydantic](https://docs.pydantic.dev/) | Data validation & serialization |
| [Uvicorn](https://www.uvicorn.org/) | ASGI server |

**Hardware Firmware (C++):**
| Library | Purpose |
|---|---|
| [Intel RealSense SDK (librealsense2)](https://github.com/IntelRealSense/librealsense) | Dual D435i depth camera capture |
| [CMake](https://cmake.org/) | Cross-platform build system |
| C++ Standard Library (`std::thread`, `std::mutex`) | Threading & synchronization |
| Linux I2C (`i2c-dev`, `I2C_RDWR` ioctl) | Raw I2C communication with PCA9685 boards |

**Hardware Components:**
| Component | Spec |
|---|---|
| Raspberry Pi 4B | Cortex-A72, BCM2711, I2C Fast Mode (400kHz) |
| Intel RealSense D435i (×2) | Stereo depth cameras, 640×480 @ 30fps |
| NXP PCA9685 (×9) | 16-channel 12-bit PWM drivers |
| ERM Vibration Motors (×144) | 12×12 haptic grid, 3V/75mA each |

### Methodology Note

The hardware simulation (`hardware/tests/hil_simulation.py`) uses noise models and timing parameters derived from published datasheets — not arbitrary mock values. All protocol sequences were validated against NXP PCA9685 Datasheet Rev.4 (2015) and Intel RealSense D435i specifications (2019).

---

## 📄 License

MIT License — Open for contribution and community development.

---

*Built for the Undergraduate Track — AI for Life & Work | Brief 4: Public Service*
