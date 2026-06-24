package com.samvit.app.demo

/**
 * Scripted demo sequences for filming without a live backend or Gemini key.
 *
 * Enable with DEMO_MODE=true in local.properties.
 *
 * Trigger phrases are matched loosely so you can say the commands naturally
 * on camera without hitting exact wording.
 */
object DemoScriptPlayer {

    /**
     * A scripted demo sequence.
     *
     * @param action      Action tag written to CommandHistory (for log legibility).
     * @param narration   Spoken immediately when the command is recognised.
     * @param steps       Subsequent lines spoken one-by-one after TTS finishes.
     *                    If the user says "Stop" between steps, execution halts.
     * @param stepDelayMs Extra pause (ms) inserted BEFORE each step in addition to
     *                    waiting for TTS to finish — adds realistic "thinking" time.
     */
    data class DemoScript(
        val action: String,
        val narration: String,
        val steps: List<String>,
        val stepDelayMs: Long = 800L
    )

    // ── Script 1: Hospital / service search ──────────────────────────────────
    // Demo script §2 (0:30–0:55): "Find me a hospital near Gandhi Path, Jaipur"
    private val HOSPITAL_SEARCH = DemoScript(
        action    = "DEMO_FIND_SERVICE",
        narration = "I'll search for hospitals near Gandhi Path, Jaipur.",
        steps     = listOf(
            "Searching now. Please wait.",
            "I found three hospitals nearby. " +
            "The closest is Santokba Durlabhji Memorial Hospital, one point two kilometres away " +
            "on Bhawani Singh Road. " +
            "Second is Mahatma Gandhi Hospital, two point four kilometres away on J L N Marg. " +
            "Third is S M S Hospital, two point eight kilometres away. " +
            "Would you like me to get directions to any of these?"
        ),
        stepDelayMs = 1200L
    )

    // ── Script 2: Multi-step browse (Section 4 "narrating actions aloud") ────
    // Demo script §4 (2:00–2:15): agent narrates each step; user says "Stop"
    private val MULTI_STEP_BROWSE = DemoScript(
        action    = "DEMO_MULTI_STEP",
        narration = "I'll handle that for you. Starting now.",
        steps     = listOf(
            "Opening Chrome.",
            "Typing your search query.",
            "Loading search results.",
            "Reading the top result.",
            "Done. Would you like me to do anything else?"
        ),
        stepDelayMs = 1800L
    )

    // ── Script 3: Call a clinic ───────────────────────────────────────────────
    // Demo script §3 lead-in (before the black-screen audio section)
    private val CALL_CLINIC = DemoScript(
        action    = "DEMO_CALL_CLINIC",
        narration = "I'll find the nearest clinic and call them for you.",
        steps     = listOf(
            "Searching for clinics near your location.",
            "Found City Clinic, zero point eight kilometres away. Dialling now.",
            "Calling City Clinic."
        ),
        stepDelayMs = 1400L
    )

    // ── Script 4: Generic web search with spoken result ───────────────────────
    private val WEB_SEARCH = DemoScript(
        action    = "DEMO_WEB_SEARCH",
        narration = "I'll search the web for that.",
        steps     = listOf(
            "Searching now.",
            "Here is what I found. Jaipur, also known as the Pink City, is the capital of " +
            "Rajasthan. It has a population of approximately 3 million people and is known " +
            "for its historic forts, palaces, and bazaars.",
            "Would you like me to read more, or can I help with something else?"
        ),
        stepDelayMs = 1200L
    )

    /**
     * Match [utterance] to a scripted demo sequence.
     * Returns null if no demo script matches — the caller falls through to
     * normal Gemini resolution.
     */
    fun match(utterance: String): DemoScript? {
        val u = utterance.lowercase().trim()

        val wantsFind   = u.contains("find") || u.contains("search") || u.contains("locate") || u.contains("near")
        val wantsCall   = u.contains("call")
        val isHospital  = u.contains("hospital") || u.contains("doctor")
        val isClinic    = u.contains("clinic")
        val isBrowse    = u.contains("chrome") || u.contains("browse") ||
                          u.contains("look up") || u.contains("open") ||
                          (u.contains("search") && !isHospital && !isClinic)

        return when {
            wantsFind && (isHospital || (isClinic && !wantsCall)) -> HOSPITAL_SEARCH
            wantsCall && (isClinic || isHospital)                 -> CALL_CLINIC
            isBrowse                                              -> MULTI_STEP_BROWSE
            u.contains("what is") || u.contains("tell me about") ||
                u.contains("who is") || u.contains("explain")    -> WEB_SEARCH
            else                                                  -> null
        }
    }
}
