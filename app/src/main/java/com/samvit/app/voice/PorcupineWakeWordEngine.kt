package com.samvit.app.voice

import android.content.Context
import android.util.Log
import com.samvit.app.BuildConfig
import ai.picovoice.porcupine.Porcupine
import ai.picovoice.porcupine.PorcupineException

/**
 * Gap 7 — Always-on wake-word engine powered by Picovoice Porcupine.
 *
 * Porcupine runs entirely on-device on a background thread.  When the wake word
 * fires, it transitions Samvit into LISTENING state via SpeechRecognitionManager,
 * which handles one full command cycle.  After the command is complete
 * (OrchestratorState returns to IDLE/LISTENING), Porcupine resumes — there is
 * no silence-timeout gap.
 *
 * Setup required (not automated — developer action needed):
 *  1. Obtain a free AccessKey from https://console.picovoice.ai/ and set
 *     PORCUPINE_ACCESS_KEY=<key> in local.properties.
 *  2. Download the "Hey Samvit" or "Samvit" .ppn keyword model from the Picovoice
 *     console and place it in app/src/main/assets/samvit_android.ppn.
 *  3. Rebuild.  If either is missing the engine start() is a no-op (logged at WARN).
 *
 * Thread safety: start()/stop() are safe to call from any thread.
 */
class PorcupineWakeWordEngine(
    private val context: Context,
    private val orchestrator: VoiceOrchestrator
) {
    companion object {
        private const val TAG = "PorcupineWakeWord"
        private const val KEYWORD_MODEL_ASSET = "samvit_android.ppn"
    }

    @Volatile private var running = false
    private var thread: Thread? = null
    private var porcupine: Porcupine? = null

    fun start() {
        val accessKey = BuildConfig.PORCUPINE_ACCESS_KEY
        if (accessKey.isBlank()) {
            Log.w(TAG, "PORCUPINE_ACCESS_KEY not set in local.properties — wake-word engine disabled. " +
                    "Samvit will fall back to manual mic activation.")
            return
        }

        // Check that the .ppn model was bundled into assets
        val hasModel = try {
            context.assets.open(KEYWORD_MODEL_ASSET).close(); true
        } catch (e: Exception) {
            false
        }
        if (!hasModel) {
            Log.w(TAG, "$KEYWORD_MODEL_ASSET not found in assets/ — wake-word engine disabled. " +
                    "Download the keyword model from https://console.picovoice.ai/ and place it in assets/.")
            return
        }

        try {
            porcupine = Porcupine.Builder()
                .setAccessKey(accessKey)
                .setKeywordPath(KEYWORD_MODEL_ASSET)  // resolved from assets
                .setSensitivity(0.7f)                  // 0.0 (strict) – 1.0 (permissive)
                .build(context)
        } catch (e: PorcupineException) {
            Log.e(TAG, "Failed to initialise Porcupine: ${e.message}")
            return
        }

        running = true
        thread = Thread({
            val engine = porcupine ?: return@Thread
            try {
                val frameLength = engine.frameLength
                val sampleRate = engine.sampleRate
                val recorder = android.media.AudioRecord(
                    android.media.MediaRecorder.AudioSource.VOICE_RECOGNITION,
                    sampleRate,
                    android.media.AudioFormat.CHANNEL_IN_MONO,
                    android.media.AudioFormat.ENCODING_PCM_16BIT,
                    frameLength * 2
                )
                recorder.startRecording()
                val frame = ShortArray(frameLength)

                while (running) {
                    val state = orchestrator.state.value
                    // Only run Porcupine when Samvit is idle/listening (not mid-command)
                    if (state == OrchestratorState.IDLE || state == OrchestratorState.LISTENING) {
                        recorder.read(frame, 0, frameLength)
                        val keywordIndex = engine.process(frame)
                        if (keywordIndex >= 0) {
                            Log.d(TAG, "Wake word detected — activating SpeechRecognizer")
                            orchestrator.speech.startListening()
                        }
                    } else {
                        // Pause reading while Samvit is speaking/processing to avoid
                        // accidentally triggering on TTS audio.
                        Thread.sleep(100)
                    }
                }
                recorder.stop()
                recorder.release()
            } catch (e: Exception) {
                Log.e(TAG, "Porcupine audio loop error: ${e.message}")
            }
        }, "PorcupineThread").also { it.isDaemon = true }
        thread?.start()
    }

    fun stop() {
        running = false
        thread?.interrupt()
        thread = null
        try { porcupine?.delete() } catch (_: Exception) {}
        porcupine = null
    }
}
