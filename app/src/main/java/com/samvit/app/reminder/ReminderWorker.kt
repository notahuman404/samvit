package com.samvit.app.reminder

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import java.util.Locale
import java.util.UUID

class ReminderWorker(
    private val context: Context,
    params: WorkerParameters
) : CoroutineWorker(context, params) {

    companion object {
        const val CHANNEL_ID = "samvit_reminders"
    }

    override suspend fun doWork(): Result {
        val text = inputData.getString("reminder_text") ?: return Result.failure()
        val message = "Reminder: $text"

        // Speak via TTS
        speakReminder(message)

        // Also show notification
        showNotification(message)

        return Result.success()
    }

    /**
     * Speaks [text] through a single TTS instance that shuts itself down once
     * the utterance completes (or fails).
     *
     * Previous implementation created two nested TextToSpeech objects — the outer
     * one was never shut down and the inner one called speak() before its own
     * onInit had fired, producing a resource leak and a race condition where the
     * reminder might never actually be spoken.
     */
    private fun speakReminder(text: String) {
        var tts: TextToSpeech? = null
        tts = TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale.UK
                tts?.setSpeechRate(0.92f)
                val utteranceId = UUID.randomUUID().toString()
                tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utteranceId: String) {}
                    override fun onDone(utteranceId: String) { tts?.shutdown() }
                    @Deprecated("Deprecated in API 21")
                    override fun onError(utteranceId: String) { tts?.shutdown() }
                })
                tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, utteranceId)
            } else {
                tts?.shutdown()
            }
        }
    }

    private fun showNotification(text: String) {
        val nm = context.getSystemService(NotificationManager::class.java) ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Samvit Reminders", NotificationManager.IMPORTANCE_HIGH)
            )
        }
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle("Samvit Reminder")
            .setContentText(text)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .build()
        nm.notify(System.currentTimeMillis().toInt(), notification)
    }
}
