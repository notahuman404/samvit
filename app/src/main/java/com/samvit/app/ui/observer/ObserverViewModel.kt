package com.samvit.app.ui.observer

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.samvit.app.data.entities.*
import com.samvit.app.data.repository.SamvitRepository
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import java.util.UUID

class ObserverViewModel(app: Application) : AndroidViewModel(app) {
    private val repo = SamvitRepository(app)

    val commands = repo.getCommandHistory()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val reminders = repo.getAllReminders()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val contacts = repo.getContacts()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    val memory = repo.getMemory()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    /** Gap 3 — all DASHBOARD_ACCESS entries for the audit sub-tab. */
    val auditLog = repo.getAuditLog()
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    /**
     * Gap 3 — insert an audit record every time the observer screen is successfully
     * authenticated and opened.  Call this from ObserverScreen once biometric auth passes.
     */
    fun logDashboardAccess() {
        viewModelScope.launch {
            repo.logDashboardAccess(sessionId = UUID.randomUUID().toString())
        }
    }

    fun addContact(name: String, phone: String, allowCamera: Boolean) {
        viewModelScope.launch {
            repo.addContact(TrustedContact(name = name, phone = phone, allowCameraStream = allowCamera))
        }
    }

    fun deleteContact(contact: TrustedContact) {
        viewModelScope.launch { repo.deleteContact(contact) }
    }

    fun deleteReminder(reminder: Reminder) {
        viewModelScope.launch { repo.deleteReminder(reminder) }
    }

    fun deleteMemory(entry: MemoryEntry) {
        viewModelScope.launch { repo.deleteMemory(entry) }
    }
}
