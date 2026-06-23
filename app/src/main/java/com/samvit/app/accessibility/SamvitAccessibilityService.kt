package com.samvit.app.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.graphics.Path
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.samvit.app.commands.ResolvedIntent

class SamvitAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        SamvitAccessibilityBridge.screenTextProvider = { extractScreenText() }
        SamvitAccessibilityBridge.intentDispatcher = { intent -> dispatchIntent(intent) }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onUnbind(intent: Intent?): Boolean {
        SamvitAccessibilityBridge.screenTextProvider = null
        SamvitAccessibilityBridge.intentDispatcher = null
        return super.onUnbind(intent)
    }

    // ── Screen reading ────────────────────────────────────────────────────────
    private fun extractScreenText(): String {
        val root = rootInActiveWindow ?: return ""
        val sb = StringBuilder()
        extractNodeText(root, sb, depth = 0)
        root.recycle()
        return sb.toString().trim().take(2000)
    }

    private fun extractNodeText(node: AccessibilityNodeInfo, sb: StringBuilder, depth: Int) {
        if (depth > 12 || sb.length > 2000) return
        listOf(
            node.text?.toString(),
            node.contentDescription?.toString(),
            node.hintText?.toString()
        ).forEach { s ->
            if (!s.isNullOrBlank()) sb.append(s).append(". ")
        }
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            extractNodeText(child, sb, depth + 1)
            child.recycle()
        }
    }

    // ── Intent dispatch ────────────────────────────────────────────────────────
    private fun dispatchIntent(intent: ResolvedIntent) {
        when (intent.action) {
            "OPEN_APP" -> {
                val appName = intent.params["app"] ?: return
                openApp(appName)
            }
            "DEVICE_SETTING" -> {
                val setting = intent.params["setting"] ?: return
                navigateSetting(setting)
            }
        }
    }

    private fun openApp(name: String) {
        val pm = packageManager
        val match = pm.getInstalledApplications(0).firstOrNull {
            pm.getApplicationLabel(it).toString().contains(name, ignoreCase = true)
        } ?: return
        val launchIntent = pm.getLaunchIntentForPackage(match.packageName)
            ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) ?: return
        startActivity(launchIntent)
    }

    private fun navigateSetting(setting: String) {
        val intent = when {
            setting.contains("bluetooth", ignoreCase = true) ->
                Intent(android.provider.Settings.ACTION_BLUETOOTH_SETTINGS)
            setting.contains("wifi", ignoreCase = true) ->
                Intent(android.provider.Settings.ACTION_WIFI_SETTINGS)
            setting.contains("location", ignoreCase = true) ->
                Intent(android.provider.Settings.ACTION_LOCATION_SOURCE_SETTINGS)
            setting.contains("accessibility", ignoreCase = true) ->
                Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)
            else -> Intent(android.provider.Settings.ACTION_SETTINGS)
        }.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
    }

    fun performTap(x: Float, y: Float) {
        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 1)
        dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), null, null)
    }
}
