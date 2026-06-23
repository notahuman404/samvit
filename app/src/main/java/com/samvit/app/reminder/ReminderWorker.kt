package com.samvit.app.reminder

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import android.speech.tts.TextToSpeech
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

    private fun speakReminder(text: String) {
        TextToSpeech(context) { status ->
            if (status == TextToSpeech.SUCCESS) {
                val tts = TextToSpeech(context) {}
                tts.language = Locale.UK
                tts.setSpeechRate(0.92f)
                tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, UUID.randomUUID().toString())
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
