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
 * Fix 4 — when the engine cannot start (missing key or model asset), [onFallback]
 * is invoked so the caller can speak a user-facing warning rather than silently
 * dropping wake-word support.  VoiceForegroundService passes
 * `{ msg -> orchestrator.tts.speak(msg) }` so the user always hears what happened.
 *
 * Setup required (not automated — developer action needed):
 *  1. Obtain a free AccessKey from https://console.picovoice.ai/ and set
 *     PORCUPINE_ACCESS_KEY=<key> in local.properties.
 *  2. Download the "Hey Samvit" or "Samvit" .ppn keyword model from the Picovoice
 *     console and place it in app/src/main/assets/samvit_android.ppn.
 *  3. Rebuild.  If either is missing, [onFallback] is called with a descriptive message.
 *
 * Thread safety: start()/stop() are safe to call from any thread.
 *
 * @param onFallback Called (on the calling thread) when the engine cannot start.
 *                   The string argument is a user-facing spoken message.
 */
class PorcupineWakeWordEngine(
    private val context: Context,
    private val orchestrator: VoiceOrchestrator,
    private val onFallback: (message: String) -> Unit = {}
) {
    companion object {
        private const val TAG = "PorcupineWakeWord"
        private const val KEYWORD_MODEL_ASSET = "samvit_android.ppn"
        private const val FALLBACK_MESSAGE =
            "Wake word detection is not available. I will listen after each response, " +
            "but you will need to wait for me to finish speaking before I can hear you."
    }

    @Volatile private var running = false
    private var thread: Thread? = null
    private var porcupine: Porcupine? = null

    fun start() {
        val accessKey = BuildConfig.PORCUPINE_ACCESS_KEY
        if (accessKey.isBlank()) {
            Log.w(TAG, "PORCUPINE_ACCESS_KEY not set in local.properties — wake-word engine disabled.")
            // Fix 4 — audible warning so the user knows they must wait for TTS to finish
            onFallback(FALLBACK_MESSAGE)
            return
        }

        val hasModel = try {
            context.assets.open(KEYWORD_MODEL_ASSET).close(); true
        } catch (e: Exception) { false }

        if (!hasModel) {
            Log.w(TAG, "$KEYWORD_MODEL_ASSET not found in assets/ — wake-word engine disabled.")
            onFallback(FALLBACK_MESSAGE)
            return
        }

        try {
            porcupine = Porcupine.Builder()
                .setAccessKey(accessKey)
                .setKeywordPath(KEYWORD_MODEL_ASSET)
                .setSensitivity(0.7f)
                .build(context)
        } catch (e: PorcupineException) {
            Log.e(TAG, "Failed to initialise Porcupine: ${e.message}")
            // Fix 4 — initialisation failures are also surfaced audibly
            onFallback(FALLBACK_MESSAGE)
            return
        }

        running = true
        thread = Thread({
            val engine = porcupine ?: return@Thread
            try {
                val frameLength = engine.frameLength
                val sampleRate = engine.sampleRate
                val minBufferSize = android.media.AudioRecord.getMinBufferSize(
                    sampleRate,
                    android.media.AudioFormat.CHANNEL_IN_MONO,
                    android.media.AudioFormat.ENCODING_PCM_16BIT
                )
                val bufferSize = maxOf(frameLength * 2, minBufferSize)
                val recorder = android.media.AudioRecord(
                    android.media.MediaRecorder.AudioSource.VOICE_RECOGNITION,
                    sampleRate,
                    android.media.AudioFormat.CHANNEL_IN_MONO,
                    android.media.AudioFormat.ENCODING_PCM_16BIT,
                    bufferSize
                )
                if (recorder.state != android.media.AudioRecord.STATE_INITIALIZED) {
                    Log.e(TAG, "AudioRecord failed to initialize")
                    return@Thread
                }
                recorder.startRecording()
                if (recorder.recordingState != android.media.AudioRecord.RECORDSTATE_RECORDING) {
                    Log.e(TAG, "AudioRecord failed to start recording")
                    return@Thread
                }
                val frame = ShortArray(frameLength)

                while (running) {
                    val state = orchestrator.state.value
                    if (state == OrchestratorState.IDLE || state == OrchestratorState.LISTENING) {
                        recorder.read(frame, 0, frameLength)
                        val keywordIndex = engine.process(frame)
                        if (keywordIndex >= 0) {
                            Log.d(TAG, "Wake word detected — activating SpeechRecognizer")
                            orchestrator.speech.startListening()
                        }
                    } else {
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
