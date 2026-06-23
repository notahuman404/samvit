package com.samvit.app.voice

import android.app.*
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.telephony.PhoneStateListener
import android.telephony.TelephonyManager
import androidx.core.app.NotificationCompat
import com.samvit.app.MainActivity
import com.samvit.app.R

/**
 * Foreground service hosting VoiceOrchestrator and (optionally) PorcupineWakeWord.
 *
 * Gap 6 — PhoneStateListener detects when an agent-initiated call ends and routes
 * the event back to VoiceOrchestrator so the user can dictate a call summary.
 *
 * Gap 7 — PorcupineWakeWordEngine runs on a background thread while Samvit is in
 * IDLE/LISTENING state.  When the wake word fires, SpeechRecognitionManager takes
 * over for that command cycle, then Porcupine resumes.
 *
 * Fix 4 — if Porcupine cannot start (missing AccessKey or .ppn model), the engine
 * calls the [onFallback] lambda which speaks a warning via TTS so the user
 * understands they must wait for Samvit to finish speaking before it can hear them.
 *
 * Notification title/subtitle updates reflect LISTENING / PROCESSING / SPEAKING /
 * EMERGENCY states so the user's lock-screen glance shows the current state.
 */
class VoiceForegroundService : Service() {

    companion object {
        const val CHANNEL_ID = "samvit_voice_channel"
        const val NOTIFICATION_ID = 1
    }

    private lateinit var orchestrator: VoiceOrchestrator
    private var wakeWordEngine: PorcupineWakeWordEngine? = null
    private var telephonyManager: TelephonyManager? = null

    // Gap 6 — monitors phone call state to detect when an agent-initiated call ends
    @Suppress("DEPRECATION")
    private val phoneStateListener = object : PhoneStateListener() {
        private var wasOffhook = false

        @Deprecated("Deprecated in Java")
        override fun onCallStateChanged(state: Int, phoneNumber: String?) {
            when (state) {
                TelephonyManager.CALL_STATE_OFFHOOK -> wasOffhook = true
                TelephonyManager.CALL_STATE_IDLE -> {
                    if (wasOffhook && orchestrator.agentInitiatedCall) {
                        orchestrator.onAgentCallEnded()
                    }
                    wasOffhook = false
                }
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIFICATION_ID, buildNotification("Listening", "Say a command"))

        orchestrator = VoiceOrchestrator(this)
        orchestrator.start()

        // Gap 7 / Fix 4 — start Porcupine; pass a TTS fallback so the user hears a warning
        // if the engine is unavailable instead of silently degrading.
        wakeWordEngine = PorcupineWakeWordEngine(
            context      = this,
            orchestrator = orchestrator,
            onFallback   = { message ->
                // Speak the warning via the orchestrator TTS.
                // orchestrator.start() has already initialised TTS by this point.
                orchestrator.tts.speak(message)
            }
        )
        wakeWordEngine?.start()

        // Gap 6 — register call-state listener
        telephonyManager = getSystemService(TELEPHONY_SERVICE) as? TelephonyManager
        @Suppress("DEPRECATION")
        telephonyManager?.listen(phoneStateListener, PhoneStateListener.LISTEN_CALL_STATE)

        // Mirror orchestrator state into the notification via a lightweight polling thread.
        Thread {
            var lastState = OrchestratorState.IDLE
            while (true) {
                val current = orchestrator.state.value
                if (current != lastState) {
                    lastState = current
                    updateNotification(current)
                }
                Thread.sleep(500)
            }
        }.also { it.isDaemon = true }.start()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        wakeWordEngine?.stop()
        @Suppress("DEPRECATION")
        telephonyManager?.listen(phoneStateListener, PhoneStateListener.LISTEN_NONE)
        orchestrator.stop()
        super.onDestroy()
    }

    private fun updateNotification(state: OrchestratorState) {
        val (title, subtitle) = when (state) {
            OrchestratorState.IDLE       -> "Samvit — Wake word active" to "Say \"Hey Samvit\" or tap to speak"
            OrchestratorState.LISTENING  -> "Samvit — Listening" to "Speak your command now"
            OrchestratorState.PROCESSING -> "Samvit — Thinking" to "Processing your request…"
            OrchestratorState.SPEAKING   -> "Samvit — Speaking" to "Replying…"
            OrchestratorState.EMERGENCY  -> "Samvit — EMERGENCY ACTIVE" to "Emergency services contacted"
        }
        val nm = getSystemService(NotificationManager::class.java)
        nm?.notify(NOTIFICATION_ID, buildNotification(title, subtitle))
    }

    private fun buildNotification(title: String, subtitle: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle(title)
            .setContentText(subtitle)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID, "Samvit Voice Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply { description = "Keeps Samvit listening for voice commands" }
            getSystemService(NotificationManager::class.java)?.createNotificationChannel(channel)
        }
    }
}
