package com.samvit.app.emergency

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Location
import android.net.Uri
import android.telephony.SmsManager
import androidx.camera.camera2.Camera2Config
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import com.google.android.gms.location.LocationServices
import com.samvit.app.BuildConfig
import com.samvit.app.data.database.SamvitDatabase
import com.samvit.app.voice.TTSManager
import kotlinx.coroutines.*
import kotlinx.coroutines.tasks.await
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.nio.ByteBuffer
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class EmergencyManager(
    private val context: Context,
    private val tts: TTSManager
) {
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private val db = SamvitDatabase.getInstance(context)
    private var countdownJob: Job? = null
    private var countdownActive = false

    /** Gap 1 — sustained GPS broadcasting during an active emergency. */
    private val locationBroadcast = LocationBroadcastManager(context)

    /** Gap 8 — accumulates scene descriptions captured during Tier 2 camera forensics. */
    private val incidentArchive = mutableListOf<String>()
    private var cameraForensicsJob: Job? = null

    private val httpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .build()
    }

    // ── Tier 1 — Standard Emergency ───────────────────────────────────────────
    fun triggerTier1() {
        tts.speak("Emergency activated. Calling your contacts and sending your location.")
        // Gap 1 — start repeating location SMS every 15 seconds
        locationBroadcast.start(hyper = false)
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

    /**
     * Stop all ongoing emergency broadcasting.  Called when the user PIN-cancels
     * or a trusted contact confirms receipt (gap 1).
     */
    fun resolveEmergency() {
        locationBroadcast.stop()
        cameraForensicsJob?.cancel()
        // Gap 8 — persist the incident archive on resolution
        if (incidentArchive.isNotEmpty()) {
            val timestamp = System.currentTimeMillis()
            val prefs = context.getSharedPreferences("samvit_incidents", Context.MODE_PRIVATE)
            prefs.edit().putString("incident_$timestamp", incidentArchive.joinToString("\n")).apply()
        }
        incidentArchive.clear()
    }

    private fun escalateToTier2() {
        tts.speak("Hyper Emergency activated. Contacting emergency services.")
        // Gap 1 — hyper-tier broadcasts every 15 s with MAYDAY prefix
        locationBroadcast.start(hyper = true)
        scope.launch {
            val location = getLocation()
            val contacts = db.trustedContactDao().getAllOnce()

            contacts.forEach { contact ->
                sendEmergencySms(contact.phone, location, hyper = true)
                delay(500)
                makeCall(contact.phone)
                delay(800)
            }
            delay(500)
            makeCall("911")
        }
        // Gap 8 — start camera forensics for Tier 2
        startCameraForensics()
    }

    // ── Gap 8 — AI Camera Forensics ───────────────────────────────────────────
    /**
     * Opens the rear camera using CameraX and sends a frame to the backend
     * /camera-frame endpoint every 3 seconds.  Each scene description is:
     *  - sent as an SMS to trusted contacts with prefix "LIVE SCENE: "
     *  - added to incidentArchive for evidentiary preservation on resolution
     *
     * Note: requires a lifecycle owner to bind CameraX.  We get the ProcessCameraProvider
     * from context; in production the calling Activity/Service should be the lifecycle
     * owner — here we fall back to a non-lifecycle approach with ImageAnalysis only.
     */
    private fun startCameraForensics() {
        if (BuildConfig.BACKEND_URL.isBlank()) return
        val cameraProviderFuture = ProcessCameraProvider.getInstance(context)
        cameraProviderFuture.addListener({
            val cameraProvider = cameraProviderFuture.get()
            val imageAnalysis = ImageAnalysis.Builder()
                .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                .build()

            val analysisExecutor = Executors.newSingleThreadExecutor()
            var lastSentMs = 0L

            imageAnalysis.setAnalyzer(analysisExecutor) { imageProxy ->
                val now = System.currentTimeMillis()
                if (now - lastSentMs >= 3_000L) {
                    lastSentMs = now
                    val bytes = imageProxyToBytes(imageProxy)
                    imageProxy.close()
                    scope.launch(Dispatchers.IO) { sendFrameToBackend(bytes) }
                } else {
                    imageProxy.close()
                }
            }

            val selector = CameraSelector.DEFAULT_BACK_CAMERA
            try {
                cameraProvider.unbindAll()
                // Bind without lifecycle — suitable for foreground-service context.
                // The imageAnalysis use case does not need a preview surface.
                cameraProvider.bindToLifecycle(
                    context as LifecycleOwner,
                    selector,
                    imageAnalysis
                )
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }, ContextCompat.getMainExecutor(context))
    }

    private fun imageProxyToBytes(imageProxy: ImageProxy): ByteArray {
        val buffer: ByteBuffer = imageProxy.planes[0].buffer
        val bytes = ByteArray(buffer.remaining())
        buffer.get(bytes)
        return bytes
    }

    private suspend fun sendFrameToBackend(frameBytes: ByteArray) {
        if (frameBytes.isEmpty()) return
        try {
            val body = MultipartBody.Builder()
                .setType(MultipartBody.FORM)
                .addFormDataPart(
                    "frame", "frame.jpg",
                    frameBytes.toRequestBody("image/jpeg".toMediaType())
                )
                .build()
            val request = Request.Builder()
                .url("${BuildConfig.BACKEND_URL}/camera-frame")
                .post(body)
                .build()

            val response = httpClient.newCall(request).execute()
            if (response.isSuccessful) {
                val json = JSONObject(response.body?.string() ?: return)
                val description = json.optString("scene_description", "").ifBlank { return }
                // Store for the incident archive
                val timestamp = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
                incidentArchive.add("[$timestamp] $description")
                // SMS all trusted contacts with the live scene description
                sendSceneSms(description)
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    private suspend fun sendSceneSms(description: String) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS)
            != PackageManager.PERMISSION_GRANTED) return
        val contacts = db.trustedContactDao().getAllOnce()
        val message = "LIVE SCENE: $description"
        contacts.forEach { contact ->
            try {
                @Suppress("DEPRECATION")
                SmsManager.getDefault().sendTextMessage(contact.phone, null, message, null, null)
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
    }

    // ── Shared helpers ────────────────────────────────────────────────────────
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
