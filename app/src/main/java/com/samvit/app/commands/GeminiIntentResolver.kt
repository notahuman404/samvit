package com.samvit.app.commands

import android.content.Context
import android.util.Log
import com.google.ai.client.generativeai.GenerativeModel
import com.google.ai.client.generativeai.type.content
import com.samvit.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

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
        private const val TAG = "GeminiIntentResolver"

        /**
         * Intents with confidence below this threshold are always routed through the
         * user-confirmation flow, regardless of whether Gemini returned a confirmation
         * string.  Prevents low-confidence guesses from executing silently (gap 4).
         */
        const val CONFIDENCE_THRESHOLD = 0.85f
    }

    private val model by lazy {
        GenerativeModel(
            modelName = "gemini-1.5-flash",
            apiKey = BuildConfig.GEMINI_API_KEY
        )
    }

    private val systemPrompt = """
You are Samvit's intent resolver. The user is visually impaired and using voice commands only.
Parse the user utterance into a structured action JSON with these exact fields:
- action: one of [OPEN_APP, SEND_MESSAGE, CALL_CONTACT, FIND_SERVICE, SET_REMINDER, RECALL_MEMORY, RECALL_AUDIT, RECALL_CALL_SUMMARY, READ_SCREEN, DEVICE_SETTING, WEB_SEARCH, UNKNOWN]
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
5. Use RECALL_CALL_SUMMARY for utterances like "what did the clinic say", "call summary", "what was discussed", "remind me of the call".
""".trimIndent()

    suspend fun resolve(
        utterance: String,
        memoryContext: String = "",
        sessionId: String = ""
    ): ResolvedIntent = withContext(Dispatchers.IO) {
        // Fix 3 — route to backend agent when configured; fall back to on-device Gemini on any error.
        if (BuildConfig.USE_BACKEND_AGENT && BuildConfig.BACKEND_URL.isNotBlank()) {
            resolveViaBackend(utterance, sessionId)?.let { return@withContext it }
            Log.w(TAG, "Backend unavailable — falling back to on-device Gemini")
        }

        resolveViaGemini(utterance, memoryContext)
    }

    // ── Backend routing (fix 3) ───────────────────────────────────────────────

    /**
     * Call BackendAgentClient.startPlan() and convert the plan into a ResolvedIntent
     * that VoiceOrchestrator can drive step-by-step.  Returns null on any error so
     * the caller falls through to on-device Gemini.
     *
     * A spoken fallback ("I couldn't reach the backend…") is NOT emitted here —
     * VoiceOrchestrator handles that after the null return.
     */
    private suspend fun resolveViaBackend(utterance: String, sessionId: String): ResolvedIntent? {
        val plan = BackendAgentClient.startPlan(utterance, sessionId) ?: return null
        return ResolvedIntent(
            action    = "BACKEND_PLAN",
            params    = mapOf(
                "goal"      to utterance,
                "sessionId" to plan.sessionId,
                "firstStep" to plan.steps.firstOrNull().orEmpty()
            ),
            narration  = plan.narration,
            confidence = 0.95f
        )
    }

    // ── On-device Gemini (primary and fallback) ───────────────────────────────

    private suspend fun resolveViaGemini(
        utterance: String,
        memoryContext: String
    ): ResolvedIntent = withContext(Dispatchers.IO) {
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
     * Fix 2 — format the user's raw call-dictation notes into 2-4 spoken bullet
     * points using Gemini.  Called by VoiceOrchestrator.processCallSummary().
     *
     * Returns the formatted summary string, or the raw [transcript] on failure so
     * the user always hears something.
     */
    suspend fun formatCallSummary(transcript: String): String = withContext(Dispatchers.IO) {
        try {
            val prompt = buildString {
                append("The user just finished a phone call and dictated these notes: ")
                append(transcript)
                append("\nReformat this into 2-4 concise spoken bullet points summarising the key ")
                append("outcomes and any action items. Use plain language suitable for TTS. ")
                append("Start each point with a number, e.g. 'One: ...'. ")
                append("Return ONLY the formatted text with no extra commentary.")
            }
            val response = model.generateContent(content { text(prompt) })
            response.text?.trim()?.ifBlank { transcript } ?: transcript
        } catch (e: Exception) {
            Log.w(TAG, "formatCallSummary failed: ${e.message}")
            transcript
        }
    }

    // ── JSON parsing ─────────────────────────────────────────────────────────

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

            // Gap 4 — synthesise a confirmation question for low-confidence intents
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
        action    = "UNKNOWN",
        narration = "I didn't quite catch that. Could you say that again?",
        confidence = 0.0f
    )
}
