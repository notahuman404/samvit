package com.samvit.app.reminder

import android.content.Context
import androidx.work.*
import com.samvit.app.data.entities.Reminder
import com.samvit.app.data.repository.SamvitRepository
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

class ReminderScheduler(
    private val context: Context,
    private val repo: SamvitRepository
) {
    /**
     * Schedule a reminder from a voice utterance.
     * Parses natural language time like "at 6pm", "in 2 hours", "every 2 hours".
     * Returns the reminder DB id on success, -1 on failure.
     */
    suspend fun scheduleFromVoice(text: String, timeStr: String): Long {
        val (triggerMs, intervalMs) = parseTime(timeStr) ?: return -1

        val reminder = Reminder(
            text = text,
            triggerTimeMs = triggerMs,
            recurrenceIntervalMs = intervalMs
        )
        val id = repo.addReminder(reminder)

        val delay = (triggerMs - System.currentTimeMillis()).coerceAtLeast(0)

        val data = workDataOf(
            "reminder_id" to id,
            "reminder_text" to text
        )

        val request = OneTimeWorkRequestBuilder<ReminderWorker>()
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .setInputData(data)
            .addTag("reminder_$id")
            .build()

        WorkManager.getInstance(context).enqueue(request)

        // Store worker ID
        repo.updateReminder(reminder.copy(id = id, workerId = request.id.toString()))
        return id
    }

    /**
     * Returns Pair(triggerTimestampMs, recurrenceIntervalMs).
     * recurrenceIntervalMs = 0 means one-time.
     */
    private fun parseTime(timeStr: String): Pair<Long, Long>? {
        val now = System.currentTimeMillis()
        val lower = timeStr.lowercase()

        // "every N hours/minutes"
        val everyPattern = Pattern.compile("every\\s+(\\d+)\\s+(hour|minute|min|hr)")
        val everyMatcher = everyPattern.matcher(lower)
        if (everyMatcher.find()) {
            val amount = everyMatcher.group(1)?.toLongOrNull() ?: return null
            val unit = everyMatcher.group(2) ?: return null
            val intervalMs = if (unit.startsWith("hour") || unit.startsWith("hr"))
                amount * 3600_000L else amount * 60_000L
            return Pair(now + intervalMs, intervalMs)
        }

        // "in N hours/minutes"
        val inPattern = Pattern.compile("in\\s+(\\d+)\\s+(hour|minute|min|hr|second|sec)")
        val inMatcher = inPattern.matcher(lower)
        if (inMatcher.find()) {
            val amount = inMatcher.group(1)?.toLongOrNull() ?: return null
            val unit = inMatcher.group(2) ?: return null
            val delayMs = when {
                unit.startsWith("hour") || unit.startsWith("hr") -> amount * 3600_000L
                unit.startsWith("minute") || unit.startsWith("min") -> amount * 60_000L
                else -> amount * 1000L
            }
            return Pair(now + delayMs, 0L)
        }

        // "at 6pm", "at 14:30"
        val atPattern = Pattern.compile("at\\s+(\\d{1,2})(?::(\\d{2}))?\\s*(am|pm)?")
        val atMatcher = atPattern.matcher(lower)
        if (atMatcher.find()) {
            var hour = atMatcher.group(1)?.toIntOrNull() ?: return null
            val minute = atMatcher.group(2)?.toIntOrNull() ?: 0
            val ampm = atMatcher.group(3)
            if (ampm == "pm" && hour < 12) hour += 12
            if (ampm == "am" && hour == 12) hour = 0

            val cal = java.util.Calendar.getInstance().apply {
                set(java.util.Calendar.HOUR_OF_DAY, hour)
                set(java.util.Calendar.MINUTE, minute)
                set(java.util.Calendar.SECOND, 0)
            }
            if (cal.timeInMillis <= now) cal.add(java.util.Calendar.DAY_OF_YEAR, 1)
            return Pair(cal.timeInMillis, 0L)
        }

        return null
    }
}
