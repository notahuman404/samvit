package com.samvit.app.data.entities

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "trusted_contacts")
data class TrustedContact(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val name: String,
    val phone: String,
    val allowCameraStream: Boolean = false,
    val addedAt: Long = System.currentTimeMillis()
)
