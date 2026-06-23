package com.samvit.app

import android.Manifest
import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.samvit.app.ui.main.MainScreen
import com.samvit.app.ui.main.MainViewModel
import com.samvit.app.ui.observer.ObserverScreen
import com.samvit.app.ui.observer.ObserverViewModel
import com.samvit.app.ui.onboarding.OnboardingScreen
import com.samvit.app.ui.theme.SamvitTheme
import com.samvit.app.voice.VoiceForegroundService
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.runBlocking

private val android.content.Context.dataStore: DataStore<Preferences>
    by preferencesDataStore(name = "samvit_prefs")

class MainActivity : ComponentActivity() {

    private val ONBOARDING_DONE = booleanPreferencesKey("onboarding_done")

    private val mainViewModel: MainViewModel by viewModels()
    private val observerViewModel: ObserverViewModel by viewModels()

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* permissions handled reactively */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        requestEssentialPermissions()

        val onboardingDone = runBlocking {
            dataStore.data.map { it[ONBOARDING_DONE] ?: false }.first()
        }

        setContent {
            SamvitTheme {
                val navController = rememberNavController()
                val startDest = if (onboardingDone) "main" else "onboarding"

                NavHost(navController = navController, startDestination = startDest) {

                    composable("onboarding") {
                        OnboardingScreen(
                            onComplete = {
                                saveOnboardingDone()
                                openAccessibilitySettings()
                                navController.navigate("main") {
                                    popUpTo("onboarding") { inclusive = true }
                                }
                            }
                        )
                    }

                    composable("main") {
                        LaunchedEffect(Unit) {
                            mainViewModel.start()
                            startVoiceService()
                        }
                        MainScreen(
                            viewModel = mainViewModel,
                            onLongPressOrb = {
                                authenticateAndOpenDashboard { navController.navigate("observer") }
                            }
                        )
                    }

                    composable("observer") {
                        ObserverScreen(
                            viewModel = observerViewModel,
                            onBack = { navController.popBackStack() }
                        )
                    }
                }
            }
        }
    }

    private fun requestEssentialPermissions() {
        val permissions = arrayOf(
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.CALL_PHONE,
            Manifest.permission.SEND_SMS,
            Manifest.permission.READ_CONTACTS,
            Manifest.permission.CAMERA,
            Manifest.permission.POST_NOTIFICATIONS
        )
        permissionLauncher.launch(permissions)
    }

    private fun startVoiceService() {
        val intent = Intent(this, VoiceForegroundService::class.java)
        ContextCompat.startForegroundService(this, intent)
    }

    private fun openAccessibilitySettings() {
        startActivity(
            Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }

    private fun saveOnboardingDone() {
        runBlocking {
            dataStore.updateData { prefs ->
                prefs.toMutablePreferences().apply { set(ONBOARDING_DONE, true) }
            }
        }
    }

    private fun authenticateAndOpenDashboard(onSuccess: () -> Unit) {
        val biometricManager = BiometricManager.from(this)
        val canUseBiometric = biometricManager.canAuthenticate(
            BiometricManager.Authenticators.BIOMETRIC_WEAK or
                    BiometricManager.Authenticators.DEVICE_CREDENTIAL
        ) == BiometricManager.BIOMETRIC_SUCCESS

        if (!canUseBiometric) {
            // No biometric enrolled — open directly (for dev/testing)
            onSuccess()
            return
        }

        val executor = ContextCompat.getMainExecutor(this)
        val prompt = BiometricPrompt(this, executor, object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                super.onAuthenticationSucceeded(result)
                onSuccess()
            }
        })

        val promptInfo = BiometricPrompt.PromptInfo.Builder()
            .setTitle("Observer Dashboard")
            .setSubtitle("Authenticate to access activity logs")
            .setAllowedAuthenticators(
                BiometricManager.Authenticators.BIOMETRIC_WEAK or
                        BiometricManager.Authenticators.DEVICE_CREDENTIAL
            )
            .build()

        prompt.authenticate(promptInfo)
    }

    override fun onDestroy() {
        mainViewModel.stop()
        super.onDestroy()
    }
}
