package com.samvit.app.data.dao

import androidx.room.*
import com.samvit.app.data.entities.MemoryEntry
import kotlinx.coroutines.flow.Flow

@Dao
interface MemoryDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(entry: MemoryEntry)

    @Query("SELECT * FROM memory ORDER BY timestamp DESC")
    fun getAll(): Flow<List<MemoryEntry>>

    @Query("SELECT * FROM memory WHERE category = :cat ORDER BY timestamp DESC")
    fun getByCategory(cat: String): Flow<List<MemoryEntry>>

    @Query("SELECT * FROM memory WHERE `key` LIKE '%' || :query || '%' OR value LIKE '%' || :query || '%' ORDER BY timestamp DESC LIMIT 5")
    suspend fun search(query: String): List<MemoryEntry>

    @Delete
    suspend fun delete(entry: MemoryEntry)
}
