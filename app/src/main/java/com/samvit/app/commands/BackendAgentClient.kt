package com.samvit.app.commands

import android.util.Log
import com.samvit.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

// ── Response models (mirror backend/main.py Pydantic schemas) ─────────────

data class AgentPlanResponse(
    val goal: String,
    val steps: List<String>,
    val totalSteps: Int,
    val narration: String,
    val sessionId: String
)

/** What the Android side reports back after completing one accessibility action. */
data class StepResult(
    val success: Boolean,
    val screenDescription: String = "",
    val screenElementsJson: String = "[]",
    val screenshotBase64: String = "",
    val error: String = ""
)

data class AgentActionResponse(
    val action: String,
    val target: String,
    val value: String,
    val narration: String,
    val x: Int,
    val y: Int,
    val confidence: Float,
    val planStatus: String,
    val currentStep: Int,
    val totalSteps: Int,
    val requiresConfirmation: Boolean,
    val confirmationMessage: String
)

/**
 * HTTP client for the FastAPI backend agent (backend/main.py).
 *
 * Both calls have a hard 10-second timeout so the app never hangs silently.
 * Every method returns null on any error so callers can fall back to on-device
 * Gemini and surface a spoken warning to the user.
 *
 * Thread-safety: OkHttpClient is thread-safe; all suspend functions dispatch
 * to [Dispatchers.IO].
 */
object BackendAgentClient {

    private const val TAG = "BackendAgentClient"

    /** Shared HTTP client — OkHttpClient is thread-safe and should be a singleton. */
    private val http by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(10, TimeUnit.SECONDS)
            .build()
    }

    private val baseUrl: String get() = BuildConfig.BACKEND_URL.trimEnd('/')

    /**
     * POST /agent/plan — create a new multi-step plan for [goal].
     *
     * @return the plan, or null if BACKEND_URL is blank / the call fails / times out.
     */
    suspend fun startPlan(goal: String, sessionId: String): AgentPlanResponse? =
        withContext(Dispatchers.IO) {
            if (baseUrl.isBlank()) return@withContext null
            try {
                val body = JSONObject().put("goal", goal).toString()
                    .toRequestBody("application/json".toMediaType())
                val response = http.newCall(
                    Request.Builder()
                        .url("$baseUrl/agent/plan")
                        .post(body)
                        .addHeader("X-Session-ID", sessionId)
                        .build()
                ).execute()

                if (!response.isSuccessful) {
                    Log.w(TAG, "startPlan → HTTP ${response.code}")
                    return@withContext null
                }
                val j = JSONObject(response.body?.string() ?: return@withContext null)
                val stepsArr = j.optJSONArray("steps") ?: return@withContext null
                AgentPlanResponse(
                    goal       = j.optString("goal", goal),
                    steps      = List(stepsArr.length()) { stepsArr.getString(it) },
                    totalSteps = j.optInt("totalSteps", stepsArr.length()),
                    narration  = j.optString("narration", ""),
                    sessionId  = j.optString("sessionId", sessionId)
                )
            } catch (e: Exception) {
                Log.w(TAG, "startPlan failed: ${e.message}")
                null
            }
        }

    /**
     * POST /agent/next-action — advance the active plan by reporting the result
     * of the last step and receiving the next action to perform.
     *
     * @return the next action, or null on any error.
     */
    suspend fun nextAction(result: StepResult, sessionId: String): AgentActionResponse? =
        withContext(Dispatchers.IO) {
            if (baseUrl.isBlank()) return@withContext null
            try {
                val body = JSONObject()
                    .put("success",            result.success)
                    .put("screenDescription",  result.screenDescription)
                    .put("screenElementsJson", result.screenElementsJson)
                    .put("screenshotBase64",   result.screenshotBase64)
                    .put("error",              result.error)
                    .toString()
                    .toRequestBody("application/json".toMediaType())

                val response = http.newCall(
                    Request.Builder()
                        .url("$baseUrl/agent/next-action")
                        .post(body)
                        .addHeader("X-Session-ID", sessionId)
                        .build()
                ).execute()

                if (!response.isSuccessful) {
                    Log.w(TAG, "nextAction → HTTP ${response.code}")
                    return@withContext null
                }
                val j = JSONObject(response.body?.string() ?: return@withContext null)
                AgentActionResponse(
                    action               = j.optString("action"),
                    target               = j.optString("target"),
                    value                = j.optString("value"),
                    narration            = j.optString("narration"),
                    x                   = j.optInt("x"),
                    y                   = j.optInt("y"),
                    confidence          = j.optDouble("confidence", 0.9).toFloat(),
                    planStatus           = j.optString("planStatus", "running"),
                    currentStep          = j.optInt("currentStep"),
                    totalSteps           = j.optInt("totalSteps"),
                    requiresConfirmation = j.optBoolean("requiresConfirmation"),
                    confirmationMessage  = j.optString("confirmationMessage")
                )
            } catch (e: Exception) {
                Log.w(TAG, "nextAction failed: ${e.message}")
                null
            }
        }
}
