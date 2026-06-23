package com.samvit.app.data.dao

import androidx.room.*
import com.samvit.app.data.entities.TrustedContact
import kotlinx.coroutines.flow.Flow

@Dao
interface TrustedContactDao {
    @Insert
    suspend fun insert(c: TrustedContact): Long

    @Update
    suspend fun update(c: TrustedContact)

    @Delete
    suspend fun delete(c: TrustedContact)

    @Query("SELECT * FROM trusted_contacts ORDER BY name ASC")
    fun getAll(): Flow<List<TrustedContact>>

    @Query("SELECT * FROM trusted_contacts")
    suspend fun getAllOnce(): List<TrustedContact>
}
