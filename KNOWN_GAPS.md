# Known Gaps — Features Described in the Doc But Not Yet Implemented

This file tracks the delta between the product specification and the current
codebase.  Each entry notes what is missing, why it matters, and what needs
to be built to close the gap.

---

## 1. Call Summarization (doc §6)

**What the doc says:** After the agent executes a call, it distils the
conversation into plain spoken language ("They confirmed walk-ins before 3pm.
Bring your ID and insurance card.").

**What exists:** `CALL_PHONE` permission in the manifest; a stub endpoint
`POST /call/summarize` in `backend/main.py` that processes a transcript if
the client supplies one.

**What is missing:**
- No call recording pipeline on the Android side.
- No server-side STT (e.g. Whisper) to transcribe the audio.
- The Android `SpeechRecognizer` API does not record the remote party.

**To close:** Implement a `MediaRecorder`-based call recording service on
Android (requires `RECORD_AUDIO` + a VoIP or call-recording workaround),
pipe the audio to a Whisper or equivalent STT endpoint, then send the
transcript to `POST /call/summarize`.

---

## 2. AI Camera Forensics during Hyper Emergency (doc §7)

**What the doc says:** On "Mayday Mayday", the camera feed is analyzed in
real time for crowd density, threat signatures, body language, etc., and
structured reports are sent to relatives and emergency services.

**What exists:** A generic `POST /camera-frame` endpoint in
`backend/main.py` that describes a single frame.  No integration with
the emergency activation path.

**What is missing:**
- No background camera recording service triggered by the emergency command.
- No streaming loop that feeds frames to `/camera-frame` during an emergency.
- No routing of forensics output to contacts or emergency services.
- No 5-second cancellation window UI.

**To close:** Wire the emergency voice trigger into a `CameraRecordingService`
that feeds a continuous frame loop to the backend; route the structured output
to the contact broadcast and emergency SMS payloads.

---

## 3. Continuous GPS Location Broadcasting during Emergency (doc §7)

**What the doc says:** On Tier 1 emergency activation, the system transmits
GPS coordinates continuously until a relative confirms receipt or the user
cancels.

**What exists:** `ACCESS_FINE_LOCATION` and `ACCESS_BACKGROUND_LOCATION`
permissions in the manifest; `FOREGROUND_SERVICE_LOCATION` declared on
`VoiceForegroundService`.

**What is missing:**
- No `LocationManager`/`FusedLocationProviderClient` loop in the foreground
  service.
- No coordinate broadcast mechanism (SMS, push, or WebSocket to contacts).
- No receipt-confirmation handshake from contacts.

**To close:** Add a `LocationBroadcastManager` inside `VoiceForegroundService`
that polls location at ~10-second intervals and pushes to a backend endpoint
or directly via SMS.

---

## 4. Ambiguity Resolution / Clarification Before Acting (doc §command architecture)

**What the doc says:** Before executing an ambiguous command, the agent
reflects its interpretation verbally ("I think you want me to message Khalid
— is that right?") and waits for confirmation.

**What partially exists:** `GeminiIntentResolver` has a `confirmation` field;
`VoiceOrchestrator` has `pendingConfirmation` logic; the plan prompt now
includes a `[CLARIFY]` step convention.

**What is missing:**
- Gemini is not reliably prompted to emit a confirmation string for ambiguous
  utterances.  The plan prompt asks for `[CLARIFY]` steps but Gemini may omit
  them.
- There is no dedicated ambiguity-detection pass before planning.

**To close:** Add an explicit pre-planning prompt: ask Gemini "Is this
utterance unambiguous?  If not, return the clarification question."  Only
proceed to planning when the utterance is confirmed unambiguous or the user
has confirmed the interpretation.

---

## 5. Dashboard Access Audit Trail (doc §privacy)

**What the doc says:** Users can hear "the dashboard was accessed on Tuesday
at 3pm."

**What exists:** Nothing.

**To close:** Log each dashboard access (timestamp, IP or device ID) to the
database and expose a `GET /audit/access-log` endpoint; wire TTS narration
of recent entries into the voice command handler.

---

## 6. Session Replays / Transcript Storage (doc, Observer Dashboard table)

**What the doc says:** The Observer Dashboard shows session replays.

**What exists:** `action_history` in `VisionAgent` is kept in memory only
and cleared on `reset()`.

**To close:** Persist `action_history` entries to the database keyed by
session ID; add a `GET /sessions/{id}/replay` endpoint.

---

## 7. Perpetual Listening Gap (doc §1)

**What the doc says:** "Perpetually-listening microphone, zero button clicks
after activation."

**Reality:** `SpeechRecognitionManager` uses Android's built-in
`SpeechRecognizer`, which has a device-imposed silence timeout (~5–8 seconds)
and must be restarted after each utterance.  Audible gaps are unavoidable
with this approach.

**To close:** Integrate a wake-word engine (e.g. Porcupine, Vosk) running
continuously in the foreground service, triggering the full STT flow on
detection.  This requires a native library dependency and a wake-word model.

---

## 8. Sub-3-Second AI Cycle Claim (doc §7)

**What the doc says:** "Sub-3-second AI cycle — on-device inference for
initial analysis, cloud augmentation for deeper contextual interpretation."

**Reality:** All inference calls go to Gemini over the network.  There is
no on-device model.  On a poor connection latency will exceed 3 seconds and
the system will not function offline at all.

**To close:** Add an on-device lightweight model (e.g. MediaPipe, TFLite)
for the initial fast pass, reserving cloud calls for deep analysis.

---

## 9. Encryption at Rest (doc §privacy)

**What the doc says:** "Logs are encrypted at rest."

**Reality:** The Room database is configured with no encryption.
`agent_memory.json` is written as plain JSON.

**To close:**
- Wrap the Room database with SQLCipher (`androidx.sqlite:sqlite-cipher`) or
  use `EncryptedSharedPreferences` for small key-value memory.
- Encrypt `agent_memory.json` using a key stored in Android Keystore.

---

## 10. Backend / Android Integration Gap

**Reality:** The FastAPI backend (`backend/`) and the Android app are
essentially two independent implementations of the agent.  The Android app
calls Gemini directly via `GeminiIntentResolver` and does not use the
backend endpoints.  The backend `VisionAgent` and the Android agent do not
share state.

**To close:** Decide on a single canonical agent location.  The most
practical path is to keep AI calls in the Android app (low latency, offline
capable) and use the backend only for persistence (memory, audit log, session
storage) and heavier async tasks (call summarization, forensics).  Document
this division clearly and remove the duplicate agent logic from whichever side
is retired.
