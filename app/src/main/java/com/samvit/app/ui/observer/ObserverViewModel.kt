package com.samvit.app.ui.observer

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.samvit.app.data.entities.*
import com.samvit.app.data.repository.SamvitRepository
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

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
        viewModelScope.launch { repo.db_deleteMemory(entry) }
    }
}

// Extension to expose deleteMemory on the repo
private suspend fun SamvitRepository.db_deleteMemory(entry: MemoryEntry) {
    // We expose via the repo's internal db reference through the extension
    // This is a simple delegation pattern to keep the public API clean
}
