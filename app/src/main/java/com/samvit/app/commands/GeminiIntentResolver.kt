package com.samvit.app.commands

import android.content.Context
import com.google.ai.client.generativeai.GenerativeModel
import com.google.ai.client.generativeai.type.content
import com.samvit.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

data class ResolvedIntent(
    val action: String,
    val params: Map<String, String> = emptyMap(),
    val narration: String = "",
    val confirmation: String = ""
)

class GeminiIntentResolver(private val context: Context) {

    private val model by lazy {
        GenerativeModel(
            modelName = "gemini-1.5-flash",
            apiKey = BuildConfig.GEMINI_API_KEY
        )
    }

    private val systemPrompt = """
You are Samvit's intent resolver. The user is visually impaired and using voice commands only.
Parse the user utterance into a structured action JSON with these exact fields:
- action: one of [OPEN_APP, SEND_MESSAGE, CALL_CONTACT, FIND_SERVICE, SET_REMINDER, RECALL_MEMORY, READ_SCREEN, DEVICE_SETTING, WEB_SEARCH, UNKNOWN]
- params: key-value map (app, contact, message, service, time, query, setting, value)
- narration: what Samvit says aloud before executing (start with "I'll..." — keep it under 15 words)
- confirmation: short yes/no question ONLY if genuinely ambiguous, otherwise empty string ""

Rules:
1. Respond ONLY with valid JSON. No markdown fences. No explanation.
2. Be concise in narration — the user hears everything.
3. Only ask for confirmation when intent is truly unclear.
4. For destructive actions (delete, clear), always set a confirmation question.
""".trimIndent()

    suspend fun resolve(utterance: String, memoryContext: String = ""): ResolvedIntent =
        withContext(Dispatchers.IO) {
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

    private fun parseJson(json: String): ResolvedIntent {
        return try {
            val clean = json
                .removePrefix("```json").removePrefix("```")
                .removeSuffix("```").trim()

            val action = Regex(""""action"\s*:\s*"([^"]+)"""").find(clean)?.groupValues?.get(1) ?: "UNKNOWN"
            val narration = Regex(""""narration"\s*:\s*"([^"]+)"""").find(clean)?.groupValues?.get(1) ?: ""
            val confirmation = Regex(""""confirmation"\s*:\s*"([^"]*)"""").find(clean)?.groupValues?.get(1) ?: ""

            val params = mutableMapOf<String, String>()
            Regex(""""(app|contact|message|service|time|query|setting|value|destination)"\s*:\s*"([^"]+)"""")
                .findAll(clean)
                .forEach { params[it.groupValues[1]] = it.groupValues[2] }

            ResolvedIntent(action, params, narration, confirmation)
        } catch (e: Exception) {
            unknownIntent()
        }
    }

    private fun unknownIntent() = ResolvedIntent(
        action = "UNKNOWN",
        narration = "I didn't quite catch that. Could you say that again?"
    )
}
