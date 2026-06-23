package com.samvit.app.data.entities

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "reminders")
data class Reminder(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val text: String,
    val triggerTimeMs: Long,
    val recurrenceIntervalMs: Long = 0L, // 0 = one-time
    val isActive: Boolean = true,
    val createdAt: Long = System.currentTimeMillis(),
    val workerId: String = ""
)
