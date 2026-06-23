package com.samvit.app.accessibility

import com.samvit.app.commands.ResolvedIntent

/**
 * Singleton bridge between VoiceOrchestrator and SamvitAccessibilityService.
 * The service registers providers at onServiceConnected and clears them on unbind.
 */
object SamvitAccessibilityBridge {
    var screenTextProvider: (() -> String)? = null
    var intentDispatcher: ((ResolvedIntent) -> Unit)? = null

    val isServiceConnected: Boolean get() = screenTextProvider != null

    fun getCurrentScreenText(): String = screenTextProvider?.invoke() ?: ""
    fun dispatchIntent(intent: ResolvedIntent) { intentDispatcher?.invoke(intent) }
}
