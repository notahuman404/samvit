# Known Gaps — Features Described in the Doc But Not Yet Implemented

This file tracks the delta between the product specification and the codebase.
Each entry notes what was missing and the current status after the fix pass.

---

## 1. Continuous GPS Location Broadcasting during Emergency (doc §7)

**Status: ✅ CLOSED**

**Fix:** `LocationBroadcastManager.kt` added in `emergency/`.
- Uses `FusedLocationProviderClient.requestLocationUpdates()` (not the stale
  `lastLocation`) to get a fresh GPS fix every 15 seconds.
- On each update, sends an SMS to every trusted contact with a Google Maps link
  and timestamp, prefixed `[EMERGENCY]` or `[MAYDAY]` depending on tier.
- `EmergencyManager.triggerTier1()` now calls `locationBroadcast.start()`.
- `EmergencyManager.triggerTier2()` calls `locationBroadcast.start(hyper=true)`.
- `EmergencyManager.resolveEmergency()` stops updates and releases the callback.

---

## 2. Encryption at Rest (doc §privacy)

**Status: ✅ CLOSED**

**Fix:**
- `SamvitDatabase` now uses SQLCipher 4.5.4 via `SupportFactory(passphrase)`.
  The passphrase is a 32-character randomly-generated string created on first
  launch and stored in `EncryptedSharedPreferences` (backed by Android Keystore).
- Room schema version bumped from 1 → 2 to account for the `responseText` column.
- New dependencies added to `build.gradle.kts`:
  - `net.zetetic:android-database-sqlcipher:4.5.4` — SQLCipher AES-256 engine
  - `androidx.sqlite:sqlite-ktx:2.4.0` — `SupportFactory` adapter
  - `androidx.security:security-crypto:1.1.0-alpha06` — `EncryptedSharedPreferences`

---

## 3. Dashboard Access Audit Trail (doc §privacy)

**Status: ✅ CLOSED**

**Fix:**
- `CommandHistory` entity gains a `DASHBOARD_ACCESS` category value.
- `CommandHistoryDao` gains `getAuditLog()` (Flow) and `getLatestDashboardAccess()`.
- `SamvitRepository.logDashboardAccess()` inserts an audit row.
- `ObserverViewModel.logDashboardAccess()` is called via `LaunchedEffect` when
  `ObserverScreen` first enters composition — one row per authenticated access.
- `ObserverScreen` gains an **Audit** tab listing all access entries with
  full timestamps.
- `VoiceOrchestrator` handles the `RECALL_AUDIT` intent (e.g. "when was the
  dashboard last accessed") and reads the most recent entry aloud via TTS.

---

## 4. Ambiguity Resolution Protocol (doc §command architecture)

**Status: ✅ CLOSED**

**Fix (`GeminiIntentResolver.kt`):**
- `ResolvedIntent` gains a `confidence: Float` field (0.0–1.0).
- System prompt updated to explicitly instruct Gemini:
  *"If your confidence is below 0.85, set confirmation to a spoken question
  reflecting your interpretation.  If confidence is high, leave it empty."*
- A `CONFIDENCE_THRESHOLD = 0.85f` constant is defined.
- `parseJson()` synthesises a fallback confirmation question when Gemini returns
  `confidence < 0.85` but an empty confirmation string — ensuring low-confidence
  intents *always* ask before acting (belt-and-suspenders).
- `VoiceOrchestrator` already routes to the confirmation flow when
  `intent.confirmation.isNotBlank()`.

---

## 5. Session Transcript Storage (doc, Observer Dashboard)

**Status: ✅ CLOSED**

**Fix:**
- `CommandHistory` entity gains `responseText: String?` (nullable, defaults null).
- `CommandHistoryDao.updateResponseText(id, response)` persists the reply.
- `SamvitRepository.updateCommandResponse(id, response)` exposes it.
- `VoiceOrchestrator` saves the `lastCommandId` returned by `logCommand()` and
  calls `repo.updateCommandResponse()` in `reply()` before speaking.
- `ObserverScreen.ActivityEntry` shows the agent reply on a second line in
  `SamvitAccent` (muted blue), beneath the user utterance in `SamvitText` (white).

---

## 6. Call Summarization Pipeline (doc §6)

**Status: ✅ CLOSED (dictation approach)**

**Note:** Full automatic call recording is restricted on many Android versions
and OEMs.  The implemented approach uses post-call user dictation instead, which
is reliable cross-device.

**Fix:**
- `VoiceForegroundService` registers a `PhoneStateListener` that detects when a
  call transitions from `OFFHOOK → IDLE`.
- `VoiceOrchestrator.agentInitiatedCall` is set to `true` when executing a
  `CALL_CONTACT` intent.
- When an agent-initiated call ends, `VoiceOrchestrator.onAgentCallEnded()` is
  called, which prompts: *"Call ended. Would you like me to summarize what was
  discussed?"*
- On user confirmation, the dictated notes are stored in memory under
  `call_summary_{timestamp}` for later voice recall.

---

## 7. Always-On Listening / Wake Word Engine (doc §1)

**Status: ✅ CLOSED (architecture in place; key/model provisioning needed)**

**Fix:**
- `PorcupineWakeWordEngine.kt` added to `voice/`.
- Runs Picovoice Porcupine 3.0.1 on a daemon thread continuously.
- When the wake word fires, calls `orchestrator.speech.startListening()` — no
  silence-timeout gap, no button click required.
- Pauses during `SPEAKING`/`PROCESSING` to avoid triggering on TTS output.
- `VoiceForegroundService` instantiates and manages the engine lifecycle.
- Gracefully no-ops (with a WARN log) if `PORCUPINE_ACCESS_KEY` is blank or the
  `.ppn` model file is absent from `assets/`.
- Notification title now reflects LISTENING / PROCESSING / SPEAKING / EMERGENCY.

**Remaining developer action:**
1. `PORCUPINE_ACCESS_KEY=<key>` in `local.properties` (free at picovoice.ai).
2. Download `samvit_android.ppn` from the Picovoice console → `assets/`.

---

## 8. AI Camera Forensics in Hyper Emergency (doc §7)

**Status: ✅ CLOSED**

**Fix (`EmergencyManager.kt`):**
- `triggerTier2()` (after the countdown) calls `startCameraForensics()`.
- Uses CameraX `ImageAnalysis` (camera-camera2 + camera-lifecycle 1.3.4) to
  capture rear-camera frames without needing a preview surface.
- Every 3 seconds, posts a JPEG frame to `POST /camera-frame` on the backend.
- Parses `scene_description` from the JSON response.
- Sends each description as an SMS to trusted contacts with prefix `LIVE SCENE: `.
- Accumulates all descriptions in `incidentArchive`.
- `resolveEmergency()` writes the full archive to `SharedPreferences` under
  `incident_{timestamp}` for evidentiary preservation.
- New dependencies: `androidx.camera:camera-camera2:1.3.4`,
  `androidx.camera:camera-lifecycle:1.3.4`.

---

## 9. Backend ↔ Android Integration (doc §backend)

**Status: ✅ CLOSED**

**Fix:**
- `BACKEND_URL` and `USE_BACKEND_AGENT` build-config fields added to
  `build.gradle.kts` (sourced from `local.properties`).
- `local.properties.example` documents both with the emulator default
  (`http://10.0.2.2:8000`).
- `GeminiIntentResolver.resolve()` checks `BuildConfig.USE_BACKEND_AGENT`.
  When true, it posts to `POST /agent/plan` with an `X-Session-ID` header
  (ties to the session-keyed backend agent from the earlier backend commit).
- Falls back to on-device Gemini transparently if the backend is unreachable.
- `PORCUPINE_ACCESS_KEY` also added to `local.properties.example`.

---

## 10. Sub-3-Second AI Cycle (doc §7)

**Status: ⏳ DEFERRED**

All inference still goes to Gemini over the network.  Adding an on-device
TFLite / MediaPipe model for the initial fast pass is a significant ML-ops
effort that requires model selection, training/fine-tuning, and quantisation
outside the scope of this fix pass.  Offline operation will remain degraded
until this is addressed.
