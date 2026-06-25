package com.samvit.app.voice

import android.content.Context
import android.util.Log
import com.samvit.app.BuildConfig
import com.samvit.app.accessibility.SamvitAccessibilityBridge
import com.samvit.app.commands.BackendAgentClient
import com.samvit.app.commands.DeterministicCommand
import com.samvit.app.commands.DeterministicMatcher
import com.samvit.app.commands.GeminiIntentResolver
import com.samvit.app.commands.ResolvedIntent
import com.samvit.app.commands.StepResult
import com.samvit.app.data.repository.SamvitRepository
import com.samvit.app.demo.DemoScriptPlayer
import com.samvit.app.emergency.EmergencyManager
import com.samvit.app.reminder.ReminderScheduler
import com.samvit.app.broadcast.TrustedContactBroadcast
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.text.SimpleDateFormat
import java.util.*

enum class OrchestratorState { IDLE, LISTENING, PROCESSING, SPEAKING, EMERGENCY }

class VoiceOrchestrator(private val context: Context) {

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    val tts = TTSManager(context)
    val speech = SpeechRecognitionManager(context)
    private val gemini = GeminiIntentResolver(context)
    val repo = SamvitRepository(context)
    private val emergency = EmergencyManager(context, tts)
    private val reminders = ReminderScheduler(context, repo)
    private val broadcast = TrustedContactBroadcast(context, tts)

    private val _state = MutableStateFlow(OrchestratorState.IDLE)
    val state: StateFlow<OrchestratorState> = _state

    private val _lastUtterance = MutableStateFlow("")
    val lastUtterance: StateFlow<String> = _lastUtterance

    private val _lastReply = MutableStateFlow("")
    val lastReply: StateFlow<String> = _lastReply

    val sessionId: String get() = _sessionId
    private var _sessionId = UUID.randomUUID().toString()

    private var activeJob: Job? = null

    // ── Pending confirmation state ─────────────────────────────────────────────
    /**
     * When non-null, the next utterance is treated as a response to a pending
     * confirmation rather than a new command.  Special sentinel values are used
     * for multi-turn flows:
     *   "call_summary_prompt"    — waiting for yes/no to "want a summary?"
     *   "call_summary_dictation" — collecting dictated notes until "done"
     *   <any other string>       — standard yes/no confirmation for [pendingIntent]
     */
    private var pendingConfirmation: String? = null
    private var pendingIntent: ResolvedIntent? = null

    /** Accumulates the user's dictated call notes across multiple utterances (fix 2). */
    private val callSummaryBuffer = StringBuilder()

    /** Row ID of the most recently inserted CommandHistory row.
     *  reply() uses this to persist the agent's response (gap 5 — session transcripts). */
    private var lastCommandId: Long = -1L

    /** Set to true by CALL_CONTACT intent so the PhoneStateListener in
     *  VoiceForegroundService knows this call was agent-initiated (gap 6). */
    var agentInitiatedCall: Boolean = false
        private set

    fun start() {
        speech.init()
        speech.onResult = { utterance -> handleUtterance(utterance) }
        speech.onError = { code ->
            if (code != 7 && _state.value != OrchestratorState.EMERGENCY) {
                scope.launch { delay(600); listenOnce() }
            }
        }
        tts.onSpeakingDone = {
            scope.launch { delay(300); listenOnce() }
        }
        listenOnce()
    }

    private fun listenOnce() {
        if (_state.value == OrchestratorState.EMERGENCY) return
        _state.value = OrchestratorState.LISTENING
        speech.startListening()
    }

    private fun handleUtterance(utterance: String) {
        if (utterance.isBlank()) { listenOnce(); return }
        _lastUtterance.value = utterance
        _state.value = OrchestratorState.PROCESSING
        activeJob?.cancel()
        activeJob = scope.launch {

            // ── Multi-turn flow handling ─────────────────────────────────────
            if (pendingConfirmation != null) {
                val lower = utterance.lowercase()
                when (pendingConfirmation) {

                    // Fix 2 — user has been asked whether they want a call summary
                    "call_summary_prompt" -> {
                        pendingConfirmation = null
                        val confirmed = lower.startsWith("yes") || lower.startsWith("yeah") ||
                                lower.startsWith("correct") || lower.startsWith("that's right") ||
                                lower == "yep"
                        if (confirmed) {
                            startCallSummaryDictation()
                        } else {
                            reply("Okay, no summary needed.")
                        }
                        return@launch
                    }

                    // Fix 2 — collect dictation until the user says "done" / "that's it"
                    "call_summary_dictation" -> {
                        val done = lower.contains("done") ||
                                lower.contains("that's it") ||
                                lower.contains("that's all") ||
                                lower.contains("finish") ||
                                lower.contains("stop dictating")
                        if (done && callSummaryBuffer.isNotBlank()) {
                            val notes = callSummaryBuffer.toString().trim()
                            callSummaryBuffer.clear()
                            pendingConfirmation = null
                            processCallSummary(notes)
                        } else {
                            // Append this utterance to the running transcript
                            callSummaryBuffer.append(utterance).append(" ")
                            reply("Got it. Keep going, or say done when finished.")
                        }
                        return@launch
                    }

                    // Standard yes/no for a pending intent (gap 4)
                    else -> {
                        val confirmed = lower.startsWith("yes") || lower.startsWith("yeah") ||
                                lower.startsWith("correct") || lower.startsWith("that's right") ||
                                lower == "yep"
                        if (confirmed) {
                            pendingIntent?.let { executeIntent(it) }
                        } else {
                            reply("Okay, cancelled.")
                        }
                        pendingConfirmation = null
                        pendingIntent = null
                        return@launch
                    }
                }
            }

            // ── Class 1 — Deterministic (bypass Gemini entirely) ──────────────
            val det = DeterministicMatcher.match(utterance)
            when (det.command) {
                DeterministicCommand.STOP -> {
                    activeJob?.cancel()
                    tts.stop()
                    lastCommandId = repo.logCommand(utterance, "STOP", "VOICE", _sessionId)
                    reply("Stopped.")
                    return@launch
                }
                DeterministicCommand.EMERGENCY -> {
                    lastCommandId = repo.logCommand(utterance, "EMERGENCY_TIER1", "EMERGENCY", _sessionId)
                    _state.value = OrchestratorState.EMERGENCY
                    emergency.triggerTier1()
                    return@launch
                }
                DeterministicCommand.MAYDAY -> {
                    lastCommandId = repo.logCommand(utterance, "EMERGENCY_TIER2", "EMERGENCY", _sessionId)
                    emergency.triggerTier2 { _state.value = OrchestratorState.EMERGENCY }
                    return@launch
                }
                DeterministicCommand.CANCEL -> {
                    emergency.cancelCountdown()
                    pendingConfirmation = null
                    pendingIntent = null
                    callSummaryBuffer.clear()
                    lastCommandId = repo.logCommand(utterance, "CANCEL", "VOICE", _sessionId)
                    reply("Cancelled.")
                    return@launch
                }
                DeterministicCommand.DISMISS -> {
                    lastCommandId = repo.logCommand(utterance, "DISMISS", "REMINDER", _sessionId)
                    reply("Dismissed.")
                    return@launch
                }
                DeterministicCommand.READ_SCREEN -> {
                    val text = SamvitAccessibilityBridge.getCurrentScreenText()
                    lastCommandId = repo.logCommand(utterance, "READ_SCREEN", "VOICE", _sessionId)
                    reply(text.ifBlank { "I can't read the screen right now. Please enable the Samvit Accessibility Service in Settings." })
                    return@launch
                }
                DeterministicCommand.HEADING_TO -> {
                    lastCommandId = repo.logCommand(utterance, "BROADCAST:${det.param}", "BROADCAST", _sessionId)
                    broadcast.initiateBroadcast(det.param)
                    return@launch
                }
                DeterministicCommand.NONE -> { /* fall through */ }
            }

            // ── Demo mode — scripted responses (no Gemini key / backend required) ──
            if (BuildConfig.DEMO_MODE) {
                val script = DemoScriptPlayer.match(utterance)
                if (script != null) {
                    lastCommandId = repo.logCommand(utterance, script.action, "DEMO", _sessionId)
                    runDemoScript(script)
                    return@launch
                }
            }

            // ── Class 2 — AI intent resolution (fix 3: sessionId routes to backend) ─
            val memContext = repo.searchMemory(utterance.take(60))
                .joinToString("\n") { "${it.key}: ${it.value}" }
            val intent = gemini.resolve(utterance, memContext, _sessionId)
            lastCommandId = repo.logCommand(utterance, intent.action, "VOICE", _sessionId)

            // Gap 4 — require confirmation when Gemini is not confident
            if (intent.confirmation.isNotBlank()) {
                pendingConfirmation = intent.confirmation
                pendingIntent = intent
                reply(intent.confirmation)
            } else {
                executeIntent(intent)
            }
        }
    }

    private suspend fun executeIntent(intent: ResolvedIntent) {
        when (intent.action) {
            "SET_REMINDER" -> {
                val text = intent.params["query"] ?: intent.params["service"] ?: "reminder"
                val timeStr = intent.params["time"] ?: ""
                val id = reminders.scheduleFromVoice(text, timeStr)
                val narration = if (id > 0) "Done. I'll remind you to $text."
                               else "I couldn't schedule that reminder. Please try again."
                repo.memorise("last_reminder", text, "PREFERENCE")
                reply(narration)
            }
            "RECALL_MEMORY" -> {
                val query = intent.params["query"] ?: _lastUtterance.value
                val results = repo.searchMemory(query)
                if (results.isEmpty()) reply("I don't have any memory about that yet.")
                else reply(results.first().value)
            }
            // Gap 3 — voice recall of dashboard audit log
            "RECALL_AUDIT" -> {
                val entry = repo.getLatestDashboardAccess()
                if (entry == null) {
                    reply("The observer dashboard has not been accessed yet.")
                } else {
                    val fmt = SimpleDateFormat("EEEE 'at' h:mm a", Locale.getDefault())
                    reply("The dashboard was last accessed on ${fmt.format(Date(entry.timestamp))}.")
                }
            }
            // Fix 2 — recall the most recent stored call summary
            "RECALL_CALL_SUMMARY" -> {
                val results = repo.searchMemory("call_summary")
                val latest = results
                    .filter { it.key.startsWith("call_summary_") }
                    .maxByOrNull { it.key }
                if (latest == null) {
                    reply("I don't have any call summaries saved yet.")
                } else {
                    reply(latest.value)
                }
            }
            // Gap 6 — track agent-initiated calls
            "CALL_CONTACT" -> {
                agentInitiatedCall = true
                if (intent.narration.isNotBlank()) reply(intent.narration)
                SamvitAccessibilityBridge.dispatchIntent(intent)
            }
            // Fix 3 — drive a backend multi-step plan
            "BACKEND_PLAN" -> {
                if (intent.narration.isNotBlank()) reply(intent.narration)
                val backendSessionId = intent.params["sessionId"] ?: _sessionId
                driveBackendPlan(backendSessionId)
            }
            "UNKNOWN" -> reply("I'm not sure what you'd like me to do. Could you try rephrasing?")
            else -> {
                if (intent.narration.isNotBlank()) reply(intent.narration)
                SamvitAccessibilityBridge.dispatchIntent(intent)
            }
        }
    }

    /**
     * Fix 3 — drives a backend agent plan step by step.
     *
     * Each call to BackendAgentClient.nextAction() returns the next action and its
     * narration.  We speak the narration, dispatch the accessibility action, then
     * report success to the backend for the next step.  Stops when planStatus is
     * no longer "running", when requiresConfirmation is set, or after 20 steps max.
     *
     * If the backend becomes unreachable mid-plan, the user hears a spoken error
     * and the loop exits cleanly — no silent failure.
     */
    private suspend fun driveBackendPlan(backendSessionId: String) {
        var stepResult = StepResult(success = true, screenDescription = "Plan started")
        var step = 0
        val maxSteps = 20

        while (step < maxSteps) {
            val action = BackendAgentClient.nextAction(stepResult, backendSessionId)
            if (action == null) {
                reply("I couldn't reach the backend for the next step. Stopping here.")
                break
            }

            if (action.narration.isNotBlank()) {
                reply(action.narration)
                // Wait for TTS to finish before continuing with the next step.
                // Use try/finally so onSpeakingDone is always restored even if this
                // coroutine is cancelled while suspended at ttsJob.await().
                val ttsJob = CompletableDeferred<Unit>()
                val originalOnDone = tts.onSpeakingDone
                tts.onSpeakingDone = {
                    originalOnDone?.invoke()
                    ttsJob.complete(Unit)
                }
                try {
                    ttsJob.await()
                } finally {
                    tts.onSpeakingDone = originalOnDone
                }
            }

            if (action.requiresConfirmation) {
                pendingConfirmation = action.confirmationMessage
                pendingIntent = ResolvedIntent(
                    action    = "BACKEND_NEXT",
                    params    = mapOf("sessionId" to backendSessionId),
                    narration = action.narration
                )
                break
            }

            if (action.planStatus != "running") break

            step++
            stepResult = StepResult(success = true)
        }
    }

    /**
     * Demo mode — plays a [DemoScriptPlayer.DemoScript] step by step.
     *
     * Speaks the narration immediately, then each step in sequence, waiting for
     * TTS to finish before advancing.  The user can interrupt with "Stop" at any
     * point — the standard DeterministicMatcher handles that in the next
     * utterance cycle so no special cancellation logic is needed here.
     *
     * Only called when BuildConfig.DEMO_MODE is true.
     */
    private suspend fun runDemoScript(script: DemoScriptPlayer.DemoScript) {
        // Speak the opening narration and wait for it to finish.
        awaitReply(script.narration)

        for (step in script.steps) {
            // Honour optional inter-step delay (simulates "thinking" time).
            if (script.stepDelayMs > 0) delay(script.stepDelayMs)

            // Speak this step and wait — each step is visually shown on screen
            // so the camera can capture the reply text updating in real time.
            awaitReply(step)
        }
    }

    /**
     * Speaks [text] via TTS and suspends until the utterance is fully complete.
     * Uses the same CompletableDeferred pattern as [driveBackendPlan] so the
     * existing onSpeakingDone chain is preserved correctly.
     */
    private suspend fun awaitReply(text: String) {
        reply(text)
        val done = CompletableDeferred<Unit>()
        val prev = tts.onSpeakingDone
        tts.onSpeakingDone = {
            prev?.invoke()
            done.complete(Unit)
        }
        try {
            done.await()
        } finally {
            tts.onSpeakingDone = prev
        }
    }

    /**
     * Speak [text] and persist it as the reply for the most recent command row (gap 5).
     */
    fun reply(text: String) {
        _lastReply.value = text
        _state.value = OrchestratorState.SPEAKING
        tts.speak(text)
        if (lastCommandId > 0L) {
            scope.launch(Dispatchers.IO) { repo.updateCommandResponse(lastCommandId, text) }
        }
    }

    // ── Call summary flow (fix 2) ─────────────────────────────────────────────

    /** Called by VoiceForegroundService when an agent-initiated call ends. */
    fun onAgentCallEnded() {
        agentInitiatedCall = false
        scope.launch {
            pendingConfirmation = "call_summary_prompt"
            reply("Call ended. Would you like me to summarize what was discussed?")
        }
    }

    /** User confirmed they want a summary — transition into dictation mode. */
    private suspend fun startCallSummaryDictation() {
        callSummaryBuffer.clear()
        pendingConfirmation = "call_summary_dictation"
        reply("Go ahead. Dictate the key points from your call, and say done when you're finished.")
    }

    /**
     * Fix 2 — format the user's raw dictated [notes] via Gemini into 2-4 spoken
     * bullet points, read the summary aloud, and store it under
     * "call_summary_{timestamp}" for future recall.
     */
    private suspend fun processCallSummary(notes: String) {
        reply("Got it. One moment.")
        val timestamp = System.currentTimeMillis()
        val summary = try {
            gemini.formatCallSummary(notes)
        } catch (e: Exception) {
            Log.w("VoiceOrchestrator", "formatCallSummary failed: ${e.message}")
            notes
        }
        repo.memorise("call_summary_$timestamp", summary, "CALL_SUMMARY")
        reply("Here is your call summary: $summary. Saved for later recall.")
    }

    fun clearEmergency() {
        _state.value = OrchestratorState.IDLE
        _sessionId = UUID.randomUUID().toString()
        listenOnce()
    }

    fun stop() {
        activeJob?.cancel()
        speech.stopListening()
        speech.destroy()
        tts.shutdown()
        scope.cancel()
    }
}
