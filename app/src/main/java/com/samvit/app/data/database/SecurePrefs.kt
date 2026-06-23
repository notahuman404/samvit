package com.samvit.app.data.database

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKeys

/**
 * Singleton accessor for the app's EncryptedSharedPreferences file.
 *
 * Both SamvitDatabase (stores the SQLCipher passphrase) and EmergencyManager
 * (stores the incident archive) share this one instance so the same Android
 * Keystore master key is used throughout — avoiding a second AES-GCM key being
 * generated for a second prefs file.
 *
 * Thread-safe: double-checked locking on the lazy initialisation.
 */
object SecurePrefs {

    @Volatile private var instance: SharedPreferences? = null

    /** Return the singleton EncryptedSharedPreferences, creating it on first call. */
    fun get(context: Context): SharedPreferences = instance ?: synchronized(this) {
        instance ?: create(context.applicationContext).also { instance = it }
    }

    private fun create(context: Context): SharedPreferences {
        val masterKeyAlias = MasterKeys.getOrCreate(MasterKeys.AES256_GCM_SPEC)
        return EncryptedSharedPreferences.create(
            "samvit_secure_prefs",
            masterKeyAlias,
            context,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }
}
