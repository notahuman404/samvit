package com.samvit.app.data.entities

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "command_history")
data class CommandHistory(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val utterance: String,
    val resolvedAction: String,
    /** VOICE, EMERGENCY, REMINDER, BROADCAST, CALL, DASHBOARD_ACCESS */
    val category: String,
    val timestamp: Long = System.currentTimeMillis(),
    val sessionId: String,
    /** The TTS string Samvit spoke in reply; null until reply() is called. */
    val responseText: String? = null
)
