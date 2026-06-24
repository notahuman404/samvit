package com.samvit.app.broadcast

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import androidx.core.content.ContextCompat
import com.samvit.app.data.database.SamvitDatabase
import com.samvit.app.voice.TTSManager
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class TrustedContactBroadcast(
    private val context: Context,
    private val tts: TTSManager
) {
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private val db = SamvitDatabase.getInstance(context)

    /**
     * Activated by "I'm heading to [destination]".
     * Sends SMS to all trusted contacts with the destination.
     */
    fun initiateBroadcast(destination: String) {
        tts.speak("Broadcasting your journey to $destination to your trusted contacts.")
        scope.launch {
            val contacts = db.trustedContactDao().getAllOnce()

            if (contacts.isEmpty()) {
                tts.speak("You don't have any trusted contacts set up yet. Please add contacts in the Observer Dashboard.")
                return@launch
            }

            contacts.forEach { contact ->
                sendJourneySms(contact.phone, destination)
                delay(500)
            }

            tts.speak("Your contacts have been notified. Stay safe.")
        }
    }

    private fun sendJourneySms(phone: String, destination: String) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS)
            != PackageManager.PERMISSION_GRANTED) return

        val message = "[Samvit] I'm heading to $destination. I'll keep you updated."
        val smsManager = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S) {
            context.getSystemService(android.telephony.SmsManager::class.java)
        } else {
            @Suppress("DEPRECATION")
            android.telephony.SmsManager.getDefault()
        }

        try {
            smsManager.sendTextMessage(phone, null, message, null, null)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }
}
