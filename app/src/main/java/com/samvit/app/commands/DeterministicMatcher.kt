package com.samvit.app.commands

/**
 * Class 1 commands — bypass AI entirely.
 * Pattern-matched and executed instantaneously.
 * These are immutable and cannot be reinterpreted by Gemini.
 */
enum class DeterministicCommand {
    EMERGENCY, MAYDAY, CANCEL, STOP, DISMISS, HEADING_TO, READ_SCREEN, NONE
}

data class MatchResult(val command: DeterministicCommand, val param: String = "")

object DeterministicMatcher {

    private val EMERGENCY_PHRASES   = listOf("emergency")
    private val MAYDAY_PHRASES      = listOf("mayday mayday", "mayday, mayday")
    private val CANCEL_PHRASES      = listOf("cancel")
    private val STOP_PHRASES        = listOf("stop", "halt", "abort")
    private val DISMISS_PHRASES     = listOf("done", "dismiss", "okay dismiss", "ok dismiss")
    private val READ_SCREEN_PHRASES = listOf(
        "read me whatever's on screen", "read screen",
        "what's on screen", "read the screen", "whats on screen"
    )
    private val HEADING_PREFIXES = listOf("i'm heading to", "im heading to", "heading to", "i am heading to")

    fun match(utterance: String): MatchResult {
        val u = utterance.lowercase().trim()

        if (MAYDAY_PHRASES.any { u.contains(it) })                         return MatchResult(DeterministicCommand.MAYDAY)
        if (EMERGENCY_PHRASES.any { u == it || u.startsWith("$it ") })     return MatchResult(DeterministicCommand.EMERGENCY)
        if (CANCEL_PHRASES.any { u == it })                                 return MatchResult(DeterministicCommand.CANCEL)
        if (STOP_PHRASES.any { u == it || u.startsWith("$it ") })          return MatchResult(DeterministicCommand.STOP)
        if (DISMISS_PHRASES.any { u == it })                                return MatchResult(DeterministicCommand.DISMISS)
        if (READ_SCREEN_PHRASES.any { u.contains(it) })                    return MatchResult(DeterministicCommand.READ_SCREEN)

        for (prefix in HEADING_PREFIXES) {
            if (u.startsWith(prefix)) {
                val destination = u.removePrefix(prefix).trim()
                if (destination.isNotBlank()) return MatchResult(DeterministicCommand.HEADING_TO, destination)
            }
        }

        return MatchResult(DeterministicCommand.NONE)
    }
}
