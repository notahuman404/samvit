package com.samvit.app.data.repository

import android.content.Context
import com.samvit.app.data.database.SamvitDatabase
import com.samvit.app.data.entities.*
import kotlinx.coroutines.flow.Flow

class SamvitRepository(context: Context) {
    private val db = SamvitDatabase.getInstance(context)

    // ── Commands ──────────────────────────────────────────────────────────────
    /** Insert a command record and return its row ID so the caller can update responseText later. */
    suspend fun logCommand(utterance: String, action: String, category: String, sessionId: String): Long =
        db.commandHistoryDao().insert(
            CommandHistory(utterance = utterance, resolvedAction = action, category = category, sessionId = sessionId)
        )

    /** Persist the agent's TTS reply against an already-inserted command row (gap 5). */
    suspend fun updateCommandResponse(id: Long, response: String) =
        db.commandHistoryDao().updateResponseText(id, response)

    fun getCommandHistory(): Flow<List<CommandHistory>> = db.commandHistoryDao().getAll()

    // ── Audit log (gap 3 — dashboard access) ─────────────────────────────────
    /** Insert a DASHBOARD_ACCESS entry whenever the observer screen is authenticated and opened. */
    suspend fun logDashboardAccess(sessionId: String) =
        db.commandHistoryDao().insert(
            CommandHistory(
                utterance = "Dashboard opened",
                resolvedAction = "DASHBOARD_ACCESS",
                category = "DASHBOARD_ACCESS",
                sessionId = sessionId
            )
        )

    fun getAuditLog(): Flow<List<CommandHistory>> = db.commandHistoryDao().getAuditLog()

    suspend fun getLatestDashboardAccess(): CommandHistory? =
        db.commandHistoryDao().getLatestDashboardAccess()

    // ── Reminders ─────────────────────────────────────────────────────────────
    suspend fun addReminder(r: Reminder): Long = db.reminderDao().insert(r)
    suspend fun updateReminder(r: Reminder) = db.reminderDao().update(r)
    suspend fun deleteReminder(r: Reminder) = db.reminderDao().delete(r)
    fun getActiveReminders(): Flow<List<Reminder>> = db.reminderDao().getActive()
    fun getAllReminders(): Flow<List<Reminder>> = db.reminderDao().getAll()
    suspend fun getReminderById(id: Long): Reminder? = db.reminderDao().getById(id)

    // ── Trusted contacts ──────────────────────────────────────────────────────
    suspend fun addContact(c: TrustedContact): Long = db.trustedContactDao().insert(c)
    suspend fun updateContact(c: TrustedContact) = db.trustedContactDao().update(c)
    suspend fun deleteContact(c: TrustedContact) = db.trustedContactDao().delete(c)
    fun getContacts(): Flow<List<TrustedContact>> = db.trustedContactDao().getAll()
    suspend fun getContactsOnce(): List<TrustedContact> = db.trustedContactDao().getAllOnce()

    // ── Memory ────────────────────────────────────────────────────────────────
    suspend fun memorise(key: String, value: String, category: String) =
        db.memoryDao().upsert(MemoryEntry(key = key, value = value, category = category))

    suspend fun deleteMemory(entry: MemoryEntry) = db.memoryDao().delete(entry)

    fun getMemory(): Flow<List<MemoryEntry>> = db.memoryDao().getAll()
    suspend fun searchMemory(query: String): List<MemoryEntry> = db.memoryDao().search(query)
}
