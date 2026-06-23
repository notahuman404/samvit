package com.samvit.app.data.entities

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "command_history")
data class CommandHistory(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val utterance: String,
    val resolvedAction: String,
    val category: String, // VOICE, EMERGENCY, REMINDER, BROADCAST, CALL
    val timestamp: Long = System.currentTimeMillis(),
    val sessionId: String
)
