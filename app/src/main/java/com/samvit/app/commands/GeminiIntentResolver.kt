package com.samvit.app.commands

import android.content.Context
import com.google.ai.client.generativeai.GenerativeModel
import com.google.ai.client.generativeai.type.content
import com.samvit.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * @param action  One of the known action strings or "UNKNOWN".
 * @param params  Key/value parameters extracted from the utterance.
 * @param narration  What Samvit says before executing (heard by the user).
 * @param confirmation  Non-empty means Samvit should ask the user before acting.
 * @param confidence  0.0–1.0 from Gemini.  Values below CONFIDENCE_THRESHOLD
 *                    will trigger the confirmation flow even when the confirmation
 *                    string is blank (gap 4 — ambiguity resolution).
 */
data class ResolvedIntent(
    val action: String,
    val params: Map<String, String> = emptyMap(),
    val narration: String = "",
    val confirmation: String = "",
    val confidence: Float = 1.0f
)

class GeminiIntentResolver(private val context: Context) {

    companion object {
        /**
         * Intents with confidence below this threshold are always routed through the
         * user-confirmation flow, regardless of whether Gemini returned a confirmation
         * string.  This prevents low-confidence guesses from executing silently (gap 4).
         */
        const val CONFIDENCE_THRESHOLD = 0.85f
    }

    private val model by lazy {
        GenerativeModel(
            modelName = "gemini-1.5-flash",
            apiKey = BuildConfig.GEMINI_API_KEY
        )
    }

    // Lazily constructed — only created when USE_BACKEND_AGENT is true (gap 9).
    private val httpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    private val systemPrompt = """
You are Samvit's intent resolver. The user is visually impaired and using voice commands only.
Parse the user utterance into a structured action JSON with these exact fields:
- action: one of [OPEN_APP, SEND_MESSAGE, CALL_CONTACT, FIND_SERVICE, SET_REMINDER, RECALL_MEMORY, RECALL_AUDIT, READ_SCREEN, DEVICE_SETTING, WEB_SEARCH, UNKNOWN]
- params: key-value map (app, contact, message, service, time, query, setting, value, destination)
- narration: what Samvit says aloud before executing (start with "I'll..." — keep it under 15 words)
- confirmation: short yes/no question reflecting your interpretation ONLY if:
    (a) the intent is genuinely ambiguous, OR
    (b) your confidence is below 0.85.
    If your confidence is high AND the intent is clear, set confirmation to an empty string "".
    Example for ambiguous case: "I think you want me to message Khalid on WhatsApp — is that right?"
- confidence: a float from 0.0 to 1.0 representing how certain you are about the resolved intent.
    Use 0.9+ for clear, unambiguous commands.
    Use below 0.85 when the utterance could plausibly mean multiple things.

Rules:
1. Respond ONLY with valid JSON. No markdown fences. No explanation.
2. Be concise in narration — the user hears everything.
3. For destructive actions (delete, clear), always set a confirmation question.
4. Use RECALL_AUDIT for utterances like "when was the dashboard last accessed" or "who opened the dashboard".
""".trimIndent()

    suspend fun resolve(
        utterance: String,
        memoryContext: String = "",
        sessionId: String = ""
    ): ResolvedIntent = withContext(Dispatchers.IO) {
        // Gap 9 — route to the backend agent when configured to do so.
        if (BuildConfig.USE_BACKEND_AGENT && BuildConfig.BACKEND_URL.isNotBlank()) {
            resolveViaBackend(utterance, sessionId)?.let { return@withContext it }
            // Fall through to on-device Gemini if backend is unreachable.
        }

        try {
            val prompt = buildString {
                append(systemPrompt)
                if (memoryContext.isNotBlank()) {
                    append("\nRelevant memory context:\n")
                    append(memoryContext)
                }
                append("\nUser said: \"$utterance\"")
            }
            val response = model.generateContent(content { text(prompt) })
            val json = response.text?.trim() ?: return@withContext unknownIntent()
            parseJson(json)
        } catch (e: Exception) {
            unknownIntent()
        }
    }

    /**
     * Gap 9 — POST to /agent/plan on the FastAPI backend and return the first step
     * translated into a ResolvedIntent.  Returns null on any network/parse error so
     * the caller can fall back to on-device Gemini.
     */
    private fun resolveViaBackend(utterance: String, sessionId: String): ResolvedIntent? {
        return try {
            val body = JSONObject().put("goal", utterance).toString()
                .toRequestBody("application/json".toMediaType())
            val request = Request.Builder()
                .url("${BuildConfig.BACKEND_URL}/agent/plan")
                .post(body)
                .addHeader("X-Session-ID", sessionId)  // ties to the session-keyed agent (commit 3)
                .build()
            val response = httpClient.newCall(request).execute()
            if (!response.isSuccessful) return null
            val json = JSONObject(response.body?.string() ?: return null)
            val steps = json.optJSONArray("steps")
            val narration = json.optString("narration", "")
            ResolvedIntent(
                action = "BACKEND_PLAN",
                params = mapOf(
                    "goal" to utterance,
                    "sessionId" to json.optString("sessionId", sessionId),
                    "firstStep" to (steps?.optString(0) ?: "")
                ),
                narration = narration,
                confidence = 0.95f   // backend plans are considered high-confidence
            )
        } catch (e: Exception) {
            null
        }
    }

    private fun parseJson(json: String): ResolvedIntent {
        return try {
            val clean = json
                .removePrefix("```json").removePrefix("```")
                .removeSuffix("```").trim()

            val action = Regex(""""action"\s*:\s*"([^"]+)"""").find(clean)?.groupValues?.get(1) ?: "UNKNOWN"
            val narration = Regex(""""narration"\s*:\s*"([^"]+)"""").find(clean)?.groupValues?.get(1) ?: ""
            val confirmation = Regex(""""confirmation"\s*:\s*"([^"]*)"""").find(clean)?.groupValues?.get(1) ?: ""
            val confidence = Regex(""""confidence"\s*:\s*([\d.]+)""").find(clean)?.groupValues?.get(1)?.toFloatOrNull() ?: 0.9f

            val params = mutableMapOf<String, String>()
            Regex(""""(app|contact|message|service|time|query|setting|value|destination)"\s*:\s*"([^"]+)"""")
                .findAll(clean)
                .forEach { params[it.groupValues[1]] = it.groupValues[2] }

            // Gap 4 — if confidence is below threshold, synthesise a confirmation question
            // even if Gemini didn't return one, so low-confidence intents never execute silently.
            val effectiveConfirmation = if (confidence < CONFIDENCE_THRESHOLD && confirmation.isBlank()) {
                "I think you want me to ${action.lowercase().replace("_", " ")} — is that right?"
            } else {
                confirmation
            }

            ResolvedIntent(action, params, narration, effectiveConfirmation, confidence)
        } catch (e: Exception) {
            unknownIntent()
        }
    }

    private fun unknownIntent() = ResolvedIntent(
        action = "UNKNOWN",
        narration = "I didn't quite catch that. Could you say that again?",
        confidence = 0.0f
    )
}
