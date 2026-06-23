package com.samvit.app.reminder

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val text = intent.getStringExtra("reminder_text") ?: return
        // Handled by WorkManager — this receiver is a fallback
    }
}
