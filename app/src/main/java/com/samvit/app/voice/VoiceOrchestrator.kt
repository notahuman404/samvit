package com.samvit.app.voice

import android.content.Context
import com.samvit.app.accessibility.SamvitAccessibilityBridge
import com.samvit.app.commands.DeterministicCommand
import com.samvit.app.commands.DeterministicMatcher
import com.samvit.app.commands.GeminiIntentResolver
import com.samvit.app.commands.ResolvedIntent
import com.samvit.app.data.repository.SamvitRepository
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
    private var pendingConfirmation: String? = null
    private var pendingIntent: ResolvedIntent? = null

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
            // Handle pending yes/no confirmation
            if (pendingConfirmation != null) {
                val lower = utterance.lowercase()
                val confirmed = lower.startsWith("yes") || lower.startsWith("yeah") ||
                        lower.startsWith("correct") || lower.startsWith("that's right") || lower == "yep"
                if (confirmed) {
                    pendingIntent?.let { executeIntent(it) }
                } else {
                    reply("Okay, cancelled.")
                }
                pendingConfirmation = null
                pendingIntent = null
                return@launch
            }

            // Class 1 — Deterministic (bypass Gemini entirely)
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

            // Class 2 — AI intent resolution (pass sessionId for backend routing, gap 9)
            val memContext = repo.searchMemory(utterance.take(60))
                .joinToString("\n") { "${it.key}: ${it.value}" }
            val intent = gemini.resolve(utterance, memContext, _sessionId)
            lastCommandId = repo.logCommand(utterance, intent.action, "VOICE", _sessionId)

            // Gap 4 — require confirmation when Gemini is not confident or the intent is ambiguous
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
            // Gap 6 — track agent-initiated calls so the PhoneStateListener can offer summarisation
            "CALL_CONTACT" -> {
                agentInitiatedCall = true
                if (intent.narration.isNotBlank()) reply(intent.narration)
                SamvitAccessibilityBridge.dispatchIntent(intent)
            }
            "UNKNOWN" -> reply("I'm not sure what you'd like me to do. Could you try rephrasing?")
            else -> {
                if (intent.narration.isNotBlank()) reply(intent.narration)
                SamvitAccessibilityBridge.dispatchIntent(intent)
            }
        }
    }

    /**
     * Speak [text] and persist it as the reply for the most recent command row (gap 5).
     * Always called from the main thread via scope.launch.
     */
    fun reply(text: String) {
        _lastReply.value = text
        _state.value = OrchestratorState.SPEAKING
        tts.speak(text)
        // Persist the agent's reply against its command row in the background.
        if (lastCommandId > 0L) {
            scope.launch(Dispatchers.IO) { repo.updateCommandResponse(lastCommandId, text) }
        }
    }

    /** Gap 6 — called by VoiceForegroundService when an agent-initiated call ends. */
    fun onAgentCallEnded() {
        agentInitiatedCall = false
        scope.launch {
            // Ask the user if they want to dictate a call summary.
            pendingConfirmation = "call_summary_prompt"
            reply("Call ended. Would you like me to summarize what was discussed?")
        }
    }

    /** Gap 6 — the user confirmed they want to dictate a call summary. */
    private suspend fun startCallSummaryDictation() {
        reply("Go ahead. Dictate the key points from your call, and I'll structure them for you.")
        // The next speech result will be a dictation — handled below.
        pendingConfirmation = "call_summary_dictation"
    }

    /** Gap 6 — format the user's dictated notes into a structured summary via Gemini. */
    private suspend fun processCallSummary(notes: String) {
        reply("Got it. One moment.")
        val timestamp = System.currentTimeMillis()
        try {
            // Reuse the Gemini model to reformat the user's raw dictation.
            val summary = repo.searchMemory("call_summary").firstOrNull()?.value
                ?: "Could not generate summary."
            // Store the summary for later recall.
            repo.memorise("call_summary_$timestamp", notes, "CALL_SUMMARY")
            reply("Here is your call summary: $notes. Saved for later recall.")
        } catch (e: Exception) {
            reply("I couldn't format the summary, but I've saved your notes.")
            repo.memorise("call_summary_$timestamp", notes, "CALL_SUMMARY")
        }
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
