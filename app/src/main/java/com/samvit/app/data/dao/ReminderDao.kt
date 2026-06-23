package com.samvit.app.data.dao

import androidx.room.*
import com.samvit.app.data.entities.Reminder
import kotlinx.coroutines.flow.Flow

@Dao
interface ReminderDao {
    @Insert
    suspend fun insert(r: Reminder): Long

    @Update
    suspend fun update(r: Reminder)

    @Delete
    suspend fun delete(r: Reminder)

    @Query("SELECT * FROM reminders WHERE isActive = 1 ORDER BY triggerTimeMs ASC")
    fun getActive(): Flow<List<Reminder>>

    @Query("SELECT * FROM reminders ORDER BY createdAt DESC")
    fun getAll(): Flow<List<Reminder>>

    @Query("SELECT * FROM reminders WHERE id = :id")
    suspend fun getById(id: Long): Reminder?
}
