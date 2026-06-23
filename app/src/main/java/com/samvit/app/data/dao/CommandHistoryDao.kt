package com.samvit.app.data.dao

import androidx.room.*
import com.samvit.app.data.entities.CommandHistory
import kotlinx.coroutines.flow.Flow

@Dao
interface CommandHistoryDao {
    @Insert
    suspend fun insert(entry: CommandHistory): Long

    @Query("SELECT * FROM command_history ORDER BY timestamp DESC LIMIT 300")
    fun getAll(): Flow<List<CommandHistory>>

    @Query("SELECT * FROM command_history WHERE category = :cat ORDER BY timestamp DESC")
    fun getByCategory(cat: String): Flow<List<CommandHistory>>

    /** Persist the agent's spoken reply for a command row (gap 5 — session transcripts). */
    @Query("UPDATE command_history SET responseText = :response WHERE id = :id")
    suspend fun updateResponseText(id: Long, response: String)

    /** All dashboard-access audit entries, newest first (gap 3). */
    @Query("SELECT * FROM command_history WHERE category = 'DASHBOARD_ACCESS' ORDER BY timestamp DESC")
    fun getAuditLog(): Flow<List<CommandHistory>>

    /** The single most recent dashboard access — used for voice recall (gap 3). */
    @Query("SELECT * FROM command_history WHERE category = 'DASHBOARD_ACCESS' ORDER BY timestamp DESC LIMIT 1")
    suspend fun getLatestDashboardAccess(): CommandHistory?

    @Query("DELETE FROM command_history WHERE timestamp < :before")
    suspend fun pruneOlderThan(before: Long)
}
