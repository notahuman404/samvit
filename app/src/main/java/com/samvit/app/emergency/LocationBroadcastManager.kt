package com.samvit.app.emergency

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Looper
import android.telephony.SmsManager
import android.util.Log
import androidx.core.content.ContextCompat
import com.google.android.gms.location.*
import com.samvit.app.data.database.SamvitDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.*

/**
 * Gap 1 — Sustained GPS location broadcasting during an emergency.
 *
 * Requests location updates from FusedLocationProviderClient every [INTERVAL_MS]
 * and sends an SMS to every trusted contact with the live coordinates and timestamp.
 * The caller is responsible for calling [stop] once the emergency is resolved so
 * the LocationCallback is cleaned up and updates stop.
 *
 * Why not just call getLastLocation() repeatedly? getLastLocation() returns a cached
 * fix that may be stale or null indoors.  requestLocationUpdates() triggers active
 * GPS/Wi-Fi/cell scanning and guarantees a fresh fix every interval.
 */
class LocationBroadcastManager(private val context: Context) {

    companion object {
        /** How often to push a location SMS during an active emergency. */
        private const val INTERVAL_MS = 15_000L
        private const val FASTEST_INTERVAL_MS = 10_000L
        private const val TAG = "LocationBroadcastManager"
    }

    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private val db = SamvitDatabase.getInstance(context)
    private val fusedClient = LocationServices.getFusedLocationProviderClient(context)
    private val fmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())

    private var isRunning = false
    private var isHyper = false

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val loc = result.lastLocation ?: return
            scope.launch { broadcastLocation(loc.latitude, loc.longitude) }
        }
    }

    /**
     * Start periodic location broadcasting.
     *
     * @param hyper  true for Tier 2 (Hyper Emergency) — prefixes SMS with "MAYDAY".
     */
    fun start(hyper: Boolean = false) {
        if (isRunning) return
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION)
            != PackageManager.PERMISSION_GRANTED) return

        isHyper = hyper
        isRunning = true

        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, INTERVAL_MS)
            .setMinUpdateIntervalMillis(FASTEST_INTERVAL_MS)
            .build()

        fusedClient.requestLocationUpdates(request, locationCallback, Looper.getMainLooper())
    }

    /** Stop updates and release the LocationCallback.  Safe to call multiple times. */
    fun stop() {
        if (!isRunning) return
        isRunning = false
        fusedClient.removeLocationUpdates(locationCallback)
    }

    private suspend fun broadcastLocation(lat: Double, lng: Double) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS)
            != PackageManager.PERMISSION_GRANTED) return

        val contacts = db.trustedContactDao().getAllOnce()
        val tier = if (isHyper) "MAYDAY" else "EMERGENCY"
        val mapsUrl = "https://maps.google.com/?q=$lat,$lng"
        val time = fmt.format(Date())
        val message = "[$tier] Samvit live location update at $time: $mapsUrl"
        val smsManager = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.S) {
            context.getSystemService(SmsManager::class.java)
        } else {
            @Suppress("DEPRECATION")
            SmsManager.getDefault()
        }

        contacts.forEach { contact ->
            try {
                smsManager.sendTextMessage(contact.phone, null, message, null, null)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to send location SMS to ${contact.phone}", e)
            }
        }
    }
}
