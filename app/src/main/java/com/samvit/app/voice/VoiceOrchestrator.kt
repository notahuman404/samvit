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
import java.util.UUID

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

    private var sessionId = UUID.randomUUID().toString()
    private var activeJob: Job? = null
    private var pendingConfirmation: String? = null
    private var pendingIntent: ResolvedIntent? = null

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
                    repo.logCommand(utterance, "STOP", "VOICE", sessionId)
                    reply("Stopped.")
                    return@launch
                }
                DeterministicCommand.EMERGENCY -> {
                    repo.logCommand(utterance, "EMERGENCY_TIER1", "EMERGENCY", sessionId)
                    _state.value = OrchestratorState.EMERGENCY
                    emergency.triggerTier1()
                    return@launch
                }
                DeterministicCommand.MAYDAY -> {
                    repo.logCommand(utterance, "EMERGENCY_TIER2", "EMERGENCY", sessionId)
                    emergency.triggerTier2 { _state.value = OrchestratorState.EMERGENCY }
                    return@launch
                }
                DeterministicCommand.CANCEL -> {
                    emergency.cancelCountdown()
                    pendingConfirmation = null
                    pendingIntent = null
                    repo.logCommand(utterance, "CANCEL", "VOICE", sessionId)
                    reply("Cancelled.")
                    return@launch
                }
                DeterministicCommand.DISMISS -> {
                    repo.logCommand(utterance, "DISMISS", "REMINDER", sessionId)
                    reply("Dismissed.")
                    return@launch
                }
                DeterministicCommand.READ_SCREEN -> {
                    val text = SamvitAccessibilityBridge.getCurrentScreenText()
                    repo.logCommand(utterance, "READ_SCREEN", "VOICE", sessionId)
                    reply(text.ifBlank { "I can't read the screen right now. Please enable the Samvit Accessibility Service in Settings." })
                    return@launch
                }
                DeterministicCommand.HEADING_TO -> {
                    repo.logCommand(utterance, "BROADCAST:${det.param}", "BROADCAST", sessionId)
                    broadcast.initiateBroadcast(det.param)
                    return@launch
                }
                DeterministicCommand.NONE -> { /* fall through */ }
            }

            // Class 2 — AI intent resolution
            val memContext = repo.searchMemory(utterance.take(60))
                .joinToString("\n") { "${it.key}: ${it.value}" }
            val intent = gemini.resolve(utterance, memContext)
            repo.logCommand(utterance, intent.action, "VOICE", sessionId)

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
            "UNKNOWN" -> reply("I'm not sure what you'd like me to do. Could you try rephrasing?")
            else -> {
                if (intent.narration.isNotBlank()) reply(intent.narration)
                SamvitAccessibilityBridge.dispatchIntent(intent)
            }
        }
    }

    fun reply(text: String) {
        _lastReply.value = text
        _state.value = OrchestratorState.SPEAKING
        tts.speak(text)
    }

    fun clearEmergency() {
        _state.value = OrchestratorState.IDLE
        sessionId = UUID.randomUUID().toString()
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
