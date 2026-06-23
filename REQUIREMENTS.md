# VisionPilot Architecture & Requirements

## Overview
VisionPilot is an Android application that functions as a smart, accessible mobile agent. It allows users to execute voice commands that control their device securely via Accessibility Services, the Android MediaProjection API, and an external Agent Backend.

The architecture is divided into two primary parts:
1. **The Android Client (VisionPilot):** An aggressive, standalone Kotlin-based service framework utilizing Jetpack Compose, Room DB, Audio Capture, Screen Capture (MediaProjection), and UI Hierarchy extraction (AccessibilityService).
2. **The Agent Backend (WebSocket Server):** A server acting as the intelligence layer, processing screenshots, UI layout data, and user queries to determine the next immediate UI interaction.

This document serves as the guide for anyone looking to set up the corresponding backend capable of interpreting the VisionPilot payloads.

---

## The Android Client Data Flow
When a user issues a command (e.g., "Open YouTube and search for cats"):
1. The `AgentActionExecutor` initiates a 10-step event loop.
2. At every step:
   - The `ScreenCaptureService` grabs a compressed Base64 JPEG of the screen.
   - The `VisionPilotAccessibilityService` structures the current UI tree into a JSON array, mapping `className`, `label`, `center_x`, and `center_y`.
   - The command, screenshot, and UI tree are pushed over WebSocket to the URL configured in `WebSocketManager` (`ws://agent/connect`).
3. The Backend responds with a discrete `AgentAction` JSON payload telling the Android client what to do next.

---

## Backend Requirements
To successfully run the AI model backend that talks to VisionPilot, you need a WebSocket-capable server (tested typically with Python/FastAPI) and an LLM capable of Vision and JSON reasoning (e.g., Gemini 1.5 Pro).

### `requirements.txt`
The included `requirements.txt` file contains the Python dependencies needed to build the server:
- **FastAPI / Uvicorn:** For WebSocket hosting.
- **WebSockets / Pydantic:** For data modeling and socket handling.
- **Google Generative AI:** To pass the bounding boxes, screenshot, and command into the Gemini model.
- **Pillow:** For image parsing if you intend to draw debug overlays server-side.

### Expected Payload from Android -> Backend
The client sends payload requests in this standard JSON format:
```json
{
  "session_id": "c4d7e2-45a8-...",
  "command": "call mom",
  "screenshot": "<base64_jpeg_string>",
  "package_name": "com.android.launcher",
  "ui_tree": [
    {
      "index": 0,
      "role": "android.widget.TextView",
      "label": "Messages",
      "center_x": 450,
      "center_y": 1200
    }
  ]
}
```

### Expected Payload from Backend -> Android
The backend must evaluate the screenshot, the tree, and the goal, then select a single action to reply with. The reply must map perfectly to the Android `AgentAction` class structure:

```json
{
  "type": "tap", 
  "x": 450, 
  "y": 1200,
  "text": "Messages",
  "packageId": null,
  "contactName": null,
  "message": null
}
```

### Actions Supported by `AgentActionExecutor.kt`
- `"tap"`: Clicks at `{x, y}` or uses `text` to find the node.
- `"type"`: Types `text` into the currently focused or clicked input field.
- `"scroll"`: Triggers `ACTION_SCROLL_FORWARD` or backward.
- `"back"`: Uses `GLOBAL_ACTION_BACK`.
- `"home"`: Uses `GLOBAL_ACTION_HOME`.
- `"launch_app"`: Requires `packageId`. Uses Android's `PackageManager` to boot the app.
- `"call"`: Requires `contactName` or `text`. Uses `ContactsContract` resolving, then opens `tel:` intent.
- `"whatsapp"`: Requires `contactName` and optionally `message`. Resolves contact and fires the `wa.me/` Intent URL.
- `"speak"`: Uses the in-app TTS engine to read `message` to the user.
- `"done"`: The loop is finished successfully. `message` provides summary.
- `"error"`: Abort the loop if stuck or failed.

## Environment Variables Needed for Backend
```env
GEMINI_API_KEY="AIzaSy..."
PORT=8000
HOST="0.0.0.0"
```

## Testing Protocol
1. Start the Python API with `uvicorn main:app --host 0.0.0.0 --port 8000`
2. Make sure your Android device / emulator shares the same network.
3. In Android `WebSocketManager.kt`, change `WS_URL = "ws://agent/connect"` to `ws://YOUR_LOCAL_IP:8000/connect` (e.g., `ws://192.168.1.100:8000/connect`).
4. Rebuild the Android app. 
5. Start dictation or type a command. The AgentLoop will spin up, passing data to Python and reacting to your AI's responses.
