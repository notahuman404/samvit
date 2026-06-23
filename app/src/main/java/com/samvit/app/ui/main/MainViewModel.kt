package com.samvit.app.ui.main

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.samvit.app.voice.OrchestratorState
import com.samvit.app.voice.VoiceOrchestrator
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn

class MainViewModel(app: Application) : AndroidViewModel(app) {

    val orchestrator = VoiceOrchestrator(app)

    val state: StateFlow<OrchestratorState> = orchestrator.state
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), OrchestratorState.IDLE)

    val lastUtterance: StateFlow<String> = orchestrator.lastUtterance
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

    val lastReply: StateFlow<String> = orchestrator.lastReply
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

    fun start() = orchestrator.start()
    fun stop() = orchestrator.stop()

    override fun onCleared() {
        super.onCleared()
        orchestrator.stop()
    }
}
