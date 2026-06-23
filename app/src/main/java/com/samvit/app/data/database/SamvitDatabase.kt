package com.samvit.app.data.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import com.samvit.app.data.dao.*
import com.samvit.app.data.entities.*

@Database(
    entities = [CommandHistory::class, Reminder::class, TrustedContact::class, MemoryEntry::class],
    version = 1,
    exportSchema = false
)
abstract class SamvitDatabase : RoomDatabase() {
    abstract fun commandHistoryDao(): CommandHistoryDao
    abstract fun reminderDao(): ReminderDao
    abstract fun trustedContactDao(): TrustedContactDao
    abstract fun memoryDao(): MemoryDao

    companion object {
        @Volatile private var INSTANCE: SamvitDatabase? = null

        fun getInstance(context: Context): SamvitDatabase = INSTANCE ?: synchronized(this) {
            INSTANCE ?: Room.databaseBuilder(
                context.applicationContext,
                SamvitDatabase::class.java,
                "samvit.db"
            )
                .fallbackToDestructiveMigration()
                .build()
                .also { INSTANCE = it }
        }
    }
}
