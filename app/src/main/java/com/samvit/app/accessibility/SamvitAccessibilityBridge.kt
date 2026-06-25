package com.samvit.app.accessibility

import com.samvit.app.commands.ResolvedIntent

/**
 * Singleton bridge between VoiceOrchestrator and SamvitAccessibilityService.
 * The service registers providers at onServiceConnected and clears them on unbind.
 */
object SamvitAccessibilityBridge {
    var screenTextProvider: (() -> String)? = null
    var elementsProvider: (() -> String)? = null
    var intentDispatcher: ((ResolvedIntent) -> Unit)? = null

    /** Executes a single backend-agent action on the device and returns success. */
    var agentActionExecutor: ((action: String, target: String, value: String, x: Int, y: Int) -> Boolean)? = null

    val isServiceConnected: Boolean get() = screenTextProvider != null

    fun getCurrentScreenText(): String = screenTextProvider?.invoke() ?: ""

    /** JSON array of interactive on-screen nodes for backend element grounding. */
    fun getInteractiveElementsJson(): String = elementsProvider?.invoke() ?: "[]"

    fun dispatchIntent(intent: ResolvedIntent) { intentDispatcher?.invoke(intent) }

    fun executeAgentAction(action: String, target: String, value: String, x: Int, y: Int): Boolean =
        agentActionExecutor?.invoke(action, target, value, x, y) ?: false
}
