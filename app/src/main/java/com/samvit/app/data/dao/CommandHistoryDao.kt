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

    @Query("DELETE FROM command_history WHERE timestamp < :before")
    suspend fun pruneOlderThan(before: Long)
}
