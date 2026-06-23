package com.samvit.app.data.database

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys
import androidx.sqlite.db.SupportSQLiteOpenHelper
import com.samvit.app.data.dao.*
import com.samvit.app.data.entities.*
import net.sqlcipher.database.SQLiteDatabase
import net.sqlcipher.database.SupportFactory

/**
 * Room database with SQLCipher AES-256 encryption at rest (gap 2).
 *
 * The passphrase is a randomly-generated 32-character string that is created
 * on the first launch and stored inside EncryptedSharedPreferences (backed by
 * Android Keystore).  It never leaves the device and is never visible in logs.
 *
 * Schema version 2: added responseText column to command_history (gap 5).
 * fallbackToDestructiveMigration() handles dev-time schema changes; production
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

        private fun buildDatabase(context: Context): SamvitDatabase {
            val passphrase = getOrCreatePassphrase(context)
            val factory: SupportSQLiteOpenHelper.Factory =
                SupportFactory(SQLiteDatabase.getBytes(passphrase.toCharArray()))

            return Room.databaseBuilder(
                context,
                SamvitDatabase::class.java,
                "samvit.db"
            )
                .openHelperFactory(factory)   // enables AES-256 encryption via SQLCipher
                .fallbackToDestructiveMigration()
                .build()
        }

        /**
         * Return the stored passphrase, generating and persisting a new one if
         * this is the first launch.  EncryptedSharedPreferences wraps the value
         * with AES-256-GCM, keyed by the Android Keystore master key.
         */
        private fun getOrCreatePassphrase(context: Context): String {
            val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
            val prefs = EncryptedSharedPreferences.create(
                "samvit_secure_prefs",
                masterKeyAlias,
                context,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
            )
            val key = "db_passphrase"
            return prefs.getString(key, null) ?: run {
                val generated = generatePassphrase()
                prefs.edit().putString(key, generated).apply()
                generated
            }
        }

        /** 32 random printable ASCII characters — sufficient entropy for AES-256. */
        private fun generatePassphrase(): String {
            val chars = ('a'..'z') + ('A'..'Z') + ('0'..'9')
            return (1..32).map { chars.random() }.joinToString("")
        }
    }
}
