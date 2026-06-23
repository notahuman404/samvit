package com.samvit.app.data.entities

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "memory")
data class MemoryEntry(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val key: String,
    val value: String,
    val category: String, // SEARCH, PREFERENCE, ELIGIBILITY, CONTACT, CALL
    val timestamp: Long = System.currentTimeMillis()
)
