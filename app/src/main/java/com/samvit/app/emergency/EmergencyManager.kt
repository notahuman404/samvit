package com.samvit.app.emergency

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.net.Uri
import android.telephony.SmsManager
import androidx.core.content.ContextCompat
import com.google.android.gms.location.LocationServices
import com.samvit.app.data.database.SamvitDatabase
import com.samvit.app.voice.TTSManager
import kotlinx.coroutines.*
import kotlinx.coroutines.tasks.await

class EmergencyManager(
    private val context: Context,
    private val tts: TTSManager
) {
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private val db = SamvitDatabase.getInstance(context)
    private var countdownJob: Job? = null
    private var countdownActive = false

    // ── Tier 1 — Standard Emergency ───────────────────────────────────────────
    fun triggerTier1() {
        tts.speak("Emergency activated. Calling your contacts and sending your location.")
        scope.launch {
            val location = getLocation()
            val contacts = db.trustedContactDao().getAllOnce()

            contacts.forEach { contact ->
                sendEmergencySms(contact.phone, location)
                delay(500)
                makeCall(contact.phone)
                delay(1000)
            }
        }
    }

    // ── Tier 2 — Hyper Emergency (5-second cancel window) ─────────────────────
    fun triggerTier2(onEscalate: () -> Unit) {
        countdownActive = true
        tts.speak("Hyper Emergency activating in 5 seconds. Say cancel to abort.")
        countdownJob = scope.launch {
            for (i in 5 downTo 1) {
                delay(1000)
                if (!countdownActive) return@launch
                if (i <= 3) tts.speak("$i")
            }
            if (countdownActive) {
                onEscalate()
                escalateToTier2()
            }
        }
    }

    fun cancelCountdown() {
        countdownActive = false
        countdownJob?.cancel()
    }

    private fun escalateToTier2() {
        tts.speak("Hyper Emergency activated. Contacting emergency services.")
        scope.launch {
            val location = getLocation()
            val contacts = db.trustedContactDao().getAllOnce()

            // Everything from Tier 1
            contacts.forEach { contact ->
                sendEmergencySms(contact.phone, location, hyper = true)
                delay(500)
                makeCall(contact.phone)
                delay(800)
            }

            // Plus emergency services
            delay(500)
            makeCall("911")
        }
    }

    private fun sendEmergencySms(phone: String, location: Location?, hyper: Boolean = false) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS)
            != PackageManager.PERMISSION_GRANTED) return

        val tier = if (hyper) "HYPER EMERGENCY" else "EMERGENCY"
        val locationStr = if (location != null)
            "Location: https://maps.google.com/?q=${location.latitude},${location.longitude}"
        else "Location unavailable"

        val message = "[$tier] Samvit alert from your trusted contact. $locationStr"

        try {
            @Suppress("DEPRECATION")
            SmsManager.getDefault().sendTextMessage(phone, null, message, null, null)
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private fun makeCall(phone: String) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE)
            != PackageManager.PERMISSION_GRANTED) return

        val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:$phone"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
    }

    private suspend fun getLocation(): Location? {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED) return null
        return try {
            LocationServices.getFusedLocationProviderClient(context)
                .lastLocation.await()
        } catch (e: Exception) { null }
    }
}
