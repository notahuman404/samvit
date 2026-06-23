package com.samvit.app.data.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import com.samvit.app.data.dao.*
import com.samvit.app.data.entities.*
import net.sqlcipher.database.SQLiteDatabase
import net.sqlcipher.database.SupportFactory

/**
 * Room database with SQLCipher AES-256 encryption at rest (gap 2).
 *
 * The passphrase is a randomly-generated 32-character string created on first
 * launch and stored inside the shared [SecurePrefs] EncryptedSharedPreferences
 * (backed by Android Keystore).  It never leaves the device.
 *
 * Using [SecurePrefs] here rather than opening a second EncryptedSharedPreferences
 * instance ensures that EmergencyManager's incident archive and the DB passphrase
 * are both protected by the same Keystore master key — closing the regression
 * introduced in round 1 (fix 1).
 *
 * Schema version 2: added responseText column to command_history (gap 5).
 * fallbackToDestructiveMigration() is used for dev-time schema changes; production
 * builds should use a proper Migration instead.
 */
@Database(
    entities = [CommandHistory::class, Reminder::class, TrustedContact::class, MemoryEntry::class],
    version = 2,
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
            INSTANCE ?: buildDatabase(context.applicationContext).also { INSTANCE = it }
        }

        private val MIGRATION_1_2 = object : androidx.room.migration.Migration(1, 2) {
            override fun migrate(database: androidx.sqlite.db.SupportSQLiteDatabase) {
                database.execSQL("ALTER TABLE command_history ADD COLUMN responseText TEXT")
            }
        }

        private fun buildDatabase(context: Context): SamvitDatabase {
            val passphrase = getOrCreatePassphrase(context)
            val factory: SupportSQLiteOpenHelper.Factory =
                SupportFactory(SQLiteDatabase.getBytes(passphrase.toCharArray()))

            return Room.databaseBuilder(
                context,
                SamvitDatabase::class.java,
                "samvit.db"
            )
                .openHelperFactory(factory)
                .addMigrations(MIGRATION_1_2)
                .build()
        }

        /**
         * Return the stored passphrase, generating and persisting a new one if this
         * is the first launch.  Delegates to [SecurePrefs] so the same Keystore
         * master key guards both the passphrase and the incident archive.
         */
        private fun getOrCreatePassphrase(context: Context): String {
            val prefs = SecurePrefs.get(context)
            val key = "db_passphrase"
            return prefs.getString(key, null) ?: run {
                val generated = generatePassphrase()
                prefs.edit().putString(key, generated).apply()
                generated
            }
        }

        private fun generatePassphrase(): String {
            val chars = ('a'..'z') + ('A'..'Z') + ('0'..'9')
            return (1..32).map { chars.random() }.joinToString("")
        }
    }
}
