plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.samvit.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.samvit.app"
        minSdk = 29
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Set GEMINI_API_KEY in local.properties: GEMINI_API_KEY=your_key_here
        val geminiKey = project.findProperty("GEMINI_API_KEY")?.toString() ?: ""
        buildConfigField("String", "GEMINI_API_KEY", "\"$geminiKey\"")

        // Gap 9 — backend URL. Set BACKEND_URL in local.properties.
        // Emulator default: BACKEND_URL=http://10.0.2.2:8000
        val backendUrl = project.findProperty("BACKEND_URL")?.toString() ?: ""
        buildConfigField("String", "BACKEND_URL", "\"$backendUrl\"")

        // Gap 9 — route complex intents through the FastAPI backend agent instead of
        // calling Gemini directly on-device. Set USE_BACKEND_AGENT=true in local.properties.
        val useBackend = project.findProperty("USE_BACKEND_AGENT")?.toString()?.toBoolean() ?: false
        buildConfigField("boolean", "USE_BACKEND_AGENT", "$useBackend")

        // Gap 7 — Porcupine wake-word access key from local.properties.
        // Obtain a free key at https://console.picovoice.ai/
        val porcupineKey = project.findProperty("PORCUPINE_ACCESS_KEY")?.toString() ?: ""
        buildConfigField("String", "PORCUPINE_ACCESS_KEY", "\"$porcupineKey\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.gms.location)
    implementation(libs.generative.ai)
    implementation(libs.androidx.biometric)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.accompanist.permissions)

    // Gap 2 — encryption at rest
    // SQLCipher 4.5.4: transparent AES-256 encryption for the Room database.
    implementation(libs.android.database.sqlcipher)
    // sqlite-ktx 2.4.0: SupportFactory adapter needed to wire SQLCipher into Room.
    implementation(libs.androidx.sqlite.ktx)
    // security-crypto 1.1.0-alpha06: EncryptedSharedPreferences for the DB passphrase.
    implementation(libs.androidx.security.crypto)

    // Gap 7 — always-on wake-word engine
    // Porcupine 3.0.1: runs continuously on a background thread with no silence timeout.
    // Requires PORCUPINE_ACCESS_KEY in local.properties + a .ppn keyword model in assets/.
    implementation(libs.picovoice.porcupine)

    // Gap 8 — CameraX for AI camera forensics in Hyper Emergency
    // camera-camera2 1.3.4: CameraX backend over Camera2 API.
    implementation(libs.androidx.camera.camera2)
    // camera-lifecycle 1.3.4: ties CameraX to lifecycle/coroutine scope.
    implementation(libs.androidx.camera.lifecycle)

    debugImplementation(libs.androidx.ui.tooling)
}
