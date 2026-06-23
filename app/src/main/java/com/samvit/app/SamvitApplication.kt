package com.samvit.app

import android.app.Application
import androidx.work.Configuration

class SamvitApplication : Application(), Configuration.Provider {

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setMinimumLoggingLevel(android.util.Log.INFO)
            .build()

    override fun onCreate() {
        super.onCreate()
        // Database is lazily initialised on first access
    }
}
