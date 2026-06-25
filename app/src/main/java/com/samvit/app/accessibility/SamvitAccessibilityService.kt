package com.samvit.app.accessibility

import android.Manifest
import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Path
import android.net.Uri
import android.os.Bundle
import android.provider.ContactsContract
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.samvit.app.commands.ResolvedIntent

class SamvitAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        SamvitAccessibilityBridge.screenTextProvider = { extractScreenText() }
        SamvitAccessibilityBridge.intentDispatcher = { intent -> dispatchIntent(intent) }
        SamvitAccessibilityBridge.agentActionExecutor = { action, target, value, x, y ->
            executeAgentAction(action, target, value, x, y)
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onUnbind(intent: Intent?): Boolean {
        SamvitAccessibilityBridge.screenTextProvider = null
        SamvitAccessibilityBridge.intentDispatcher = null
        SamvitAccessibilityBridge.agentActionExecutor = null
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

    // ── Intent dispatch (on-device Gemini path) ────────────────────────────────
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
            "CALL_CONTACT" -> {
                val who = intent.params["number"] ?: intent.params["phone"]
                    ?: intent.params["contact"] ?: return
                callContact(who)
            }
        }
    }

    /**
     * Executes one atomic action emitted by the backend agent (backend/agent.py
     * ActionType vocabulary).  Returns true if the action was dispatched/performed
     * successfully so VoiceOrchestrator can report an accurate StepResult.
     */
    private fun executeAgentAction(
        action: String,
        target: String,
        value: String,
        x: Int,
        y: Int
    ): Boolean = when (action.lowercase()) {
        "tap"         -> performTap(x.toFloat(), y.toFloat())
        "long_press"  -> performLongPress(x.toFloat(), y.toFloat())
        "type_text"   -> typeText(value)
        "scroll_down" -> performVerticalSwipe(scrollDown = true)
        "scroll_up"   -> performVerticalSwipe(scrollDown = false)
        "swipe_left"  -> performHorizontalSwipe(swipeLeft = true)
        "swipe_right" -> performHorizontalSwipe(swipeLeft = false)
        "press_back"  -> performGlobalAction(GLOBAL_ACTION_BACK)
        "press_home"  -> performGlobalAction(GLOBAL_ACTION_HOME)
        "open_app"    -> openApp(target.ifBlank { value })
        // Non-device actions handled by the orchestrator/backend; treat as no-op success.
        "wait", "done", "fail", "confirm" -> true
        else -> false
    }

    private fun openApp(name: String): Boolean {
        if (name.isBlank()) return false
        val pm = packageManager

        // Prefer launchable apps so we never resolve a package that has no UI.
        val launchers = pm.queryIntentActivities(
            Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER), 0
        )
        val pkg = launchers.firstOrNull {
            it.loadLabel(pm).toString().contains(name, ignoreCase = true)
        }?.activityInfo?.packageName
            ?: launchers.firstOrNull {
                it.activityInfo.packageName.contains(name, ignoreCase = true)
            }?.activityInfo?.packageName
            ?: pm.getInstalledApplications(0).firstOrNull {
                pm.getApplicationLabel(it).toString().contains(name, ignoreCase = true)
            }?.packageName
            ?: return false

        val launchIntent = pm.getLaunchIntentForPackage(pkg)
            ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) ?: return false
        startActivity(launchIntent)
        return true
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

    private fun callContact(nameOrNumber: String): Boolean {
        val number = if (nameOrNumber.any { it.isDigit() } && nameOrNumber.none { it.isLetter() }) {
            nameOrNumber
        } else {
            lookupContactNumber(nameOrNumber) ?: return false
        }
        if (checkSelfPermission(Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            return false
        }
        val intent = Intent(Intent.ACTION_CALL, Uri.parse("tel:$number"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        startActivity(intent)
        return true
    }

    private fun lookupContactNumber(name: String): String? {
        if (checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) {
            return null
        }
        val projection = arrayOf(ContactsContract.CommonDataKinds.Phone.NUMBER)
        val selection = "${ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME} LIKE ?"
        contentResolver.query(
            ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
            projection, selection, arrayOf("%$name%"), null
        )?.use { c ->
            if (c.moveToFirst()) return c.getString(0)
        }
        return null
    }

    // ── Gesture primitives ──────────────────────────────────────────────────────
    fun performTap(x: Float, y: Float): Boolean {
        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 60)
        return dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), null, null)
    }

    private fun performLongPress(x: Float, y: Float): Boolean {
        val path = Path().apply { moveTo(x, y) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 600)
        return dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), null, null)
    }

    private fun performVerticalSwipe(scrollDown: Boolean): Boolean {
        val m = resources.displayMetrics
        val cx = m.widthPixels / 2f
        val startY = if (scrollDown) m.heightPixels * 0.70f else m.heightPixels * 0.30f
        val endY = if (scrollDown) m.heightPixels * 0.30f else m.heightPixels * 0.70f
        val path = Path().apply { moveTo(cx, startY); lineTo(cx, endY) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 300)
        return dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), null, null)
    }

    private fun performHorizontalSwipe(swipeLeft: Boolean): Boolean {
        val m = resources.displayMetrics
        val cy = m.heightPixels / 2f
        val startX = if (swipeLeft) m.widthPixels * 0.80f else m.widthPixels * 0.20f
        val endX = if (swipeLeft) m.widthPixels * 0.20f else m.widthPixels * 0.80f
        val path = Path().apply { moveTo(startX, cy); lineTo(endX, cy) }
        val stroke = GestureDescription.StrokeDescription(path, 0, 300)
        return dispatchGesture(GestureDescription.Builder().addStroke(stroke).build(), null, null)
    }

    private fun typeText(text: String): Boolean {
        val root = rootInActiveWindow ?: return false
        val target = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: findFirstEditable(root) ?: return false
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        return target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    private fun findFirstEditable(node: AccessibilityNodeInfo): AccessibilityNodeInfo? {
        if (node.isEditable) return node
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val found = findFirstEditable(child)
            if (found != null) return found
        }
        return null
    }
}
