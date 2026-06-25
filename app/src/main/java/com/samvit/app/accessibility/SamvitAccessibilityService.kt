package com.samvit.app.accessibility

import android.Manifest
import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Path
import android.graphics.Rect
import android.net.Uri
import android.os.Bundle
import android.provider.ContactsContract
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.samvit.app.commands.ResolvedIntent
import org.json.JSONArray
import org.json.JSONObject

class SamvitAccessibilityService : AccessibilityService() {

    override fun onServiceConnected() {
        super.onServiceConnected()
        SamvitAccessibilityBridge.screenTextProvider = { extractScreenText() }
        SamvitAccessibilityBridge.elementsProvider = { getInteractiveElementsJson() }
        SamvitAccessibilityBridge.intentDispatcher = { intent -> dispatchIntent(intent) }
        SamvitAccessibilityBridge.agentActionExecutor = { action, target, value, x, y ->
            executeAgentAction(action, target, value, x, y)
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    override fun onUnbind(intent: Intent?): Boolean {
        SamvitAccessibilityBridge.screenTextProvider = null
        SamvitAccessibilityBridge.elementsProvider = null
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
        "tap"         -> clickByTarget(target, longPress = false, fallbackX = x, fallbackY = y)
        "long_press"  -> clickByTarget(target, longPress = true, fallbackX = x, fallbackY = y)
        "type_text"   -> typeText(value, target)
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

    // ── Node extraction (architecture A2) ───────────────────────────────────────
    /**
     * Dumps the interactive nodes on the current screen as a JSON array the
     * backend agent can ground its action selection on.  Schema mirrors what
     * backend/agent.py reads: label + left/top/right/bottom (+ resource_id,
     * class, clickable).  Only visible, labelled nodes are emitted, deduped by
     * bounds, capped so the payload stays small.
     */
    private fun getInteractiveElementsJson(): String {
        val root = rootInActiveWindow ?: return "[]"
        val arr = JSONArray()
        val seen = HashSet<String>()
        collectNodes(root, arr, seen, depth = 0)
        return arr.toString()
    }

    private fun collectNodes(
        node: AccessibilityNodeInfo,
        arr: JSONArray,
        seen: MutableSet<String>,
        depth: Int
    ) {
        if (depth > 14 || arr.length() >= 60) return

        val label = labelOf(node)
        val rect = Rect().also { node.getBoundsInScreen(it) }
        val visible = node.isVisibleToUser && rect.width() > 0 && rect.height() > 0
        val interactive = node.isClickable || node.isEditable || node.isLongClickable
        // Per A2: emit clickable/editable nodes, plus text-bearing nodes (their
        // label is what the user refers to, even when the click target is a parent).
        if (visible && label.isNotBlank() && (interactive || label.length <= 80)) {
            val key = "${rect.left},${rect.top},${rect.right},${rect.bottom}"
            if (seen.add(key)) {
                arr.put(JSONObject().apply {
                    put("label", label)
                    put("left", rect.left)
                    put("top", rect.top)
                    put("right", rect.right)
                    put("bottom", rect.bottom)
                    put("resource_id", node.viewIdResourceName ?: "")
                    put("class", node.className?.toString() ?: "")
                    put("clickable", interactive)
                })
            }
        }

        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            collectNodes(child, arr, seen, depth + 1)
        }
    }

    private fun labelOf(node: AccessibilityNodeInfo): String {
        node.text?.toString()?.trim()?.let { if (it.isNotBlank()) return it }
        node.contentDescription?.toString()?.trim()?.let { if (it.isNotBlank()) return it }
        node.hintText?.toString()?.trim()?.let { if (it.isNotBlank()) return it }
        val resId = node.viewIdResourceName
        if (!resId.isNullOrBlank()) {
            return resId.substringAfterLast('/').replace('_', ' ').trim()
        }
        return ""
    }

    // ── Node-grounded execution (architecture A6) ───────────────────────────────
    /**
     * Taps the element the backend named ([target]) by resolving it back to a
     * real node and performing ACTION_CLICK on it (or its clickable ancestor),
     * falling back to a gesture at the node's true bounds, and only then to the
     * raw backend coordinates.  This is what makes taps land on the right widget
     * instead of trusting blind coordinates.
     */
    private fun clickByTarget(target: String, longPress: Boolean, fallbackX: Int, fallbackY: Int): Boolean {
        val root = rootInActiveWindow
        if (target.isNotBlank() && root != null) {
            val match = findBestNode(root, target)
            if (match != null) {
                var clickable: AccessibilityNodeInfo? = match
                while (clickable != null && !(if (longPress) clickable.isLongClickable else clickable.isClickable)) {
                    clickable = clickable.parent
                }
                val nodeAction = if (longPress) AccessibilityNodeInfo.ACTION_LONG_CLICK
                                 else AccessibilityNodeInfo.ACTION_CLICK
                if (clickable != null && clickable.performAction(nodeAction)) return true

                val rect = Rect().also { match.getBoundsInScreen(it) }
                if (rect.width() > 0 && rect.height() > 0) {
                    return if (longPress) performLongPress(rect.exactCenterX(), rect.exactCenterY())
                           else performTap(rect.exactCenterX(), rect.exactCenterY())
                }
            }
        }
        return if (longPress) performLongPress(fallbackX.toFloat(), fallbackY.toFloat())
               else performTap(fallbackX.toFloat(), fallbackY.toFloat())
    }

    /** Finds the visible node whose label best matches [target] by token overlap. */
    private fun findBestNode(root: AccessibilityNodeInfo, target: String): AccessibilityNodeInfo? {
        val wanted = tokenize(target)
        if (wanted.isEmpty()) return null
        var best: AccessibilityNodeInfo? = null
        var bestScore = 0

        fun walk(node: AccessibilityNodeInfo, depth: Int) {
            if (depth > 14) return
            if (node.isVisibleToUser) {
                val label = labelOf(node)
                if (label.isNotBlank()) {
                    val labelTokens = tokenize(label)
                    if (labelTokens.isNotEmpty()) {
                        var score = wanted.count { it in labelTokens }
                        if (label.equals(target, ignoreCase = true)) score += 3
                        if (node.isClickable || node.isEditable) score += 1
                        if (score > bestScore) { bestScore = score; best = node }
                    }
                }
            }
            for (i in 0 until node.childCount) {
                val child = node.getChild(i) ?: continue
                walk(child, depth + 1)
            }
        }
        walk(root, 0)
        return if (bestScore > 0) best else null
    }

    private fun tokenize(s: String): Set<String> =
        s.lowercase().split(Regex("[^a-z0-9]+")).filter { it.length > 2 }.toSet()

    /**
     * Types [text] into the named [target] field if given, otherwise the focused
     * or first editable field.  Resolving the target node first avoids typing
     * into the wrong box when several inputs are on screen.
     */
    private fun typeText(text: String, target: String): Boolean {
        val root = rootInActiveWindow ?: return false
        val field = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: (if (target.isNotBlank()) findBestNode(root, target)?.takeIf { it.isEditable } else null)
            ?: findFirstEditable(root)
            ?: return false
        field.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        return field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }
}
