package com.samvit.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable

private val SamvitColorScheme = darkColorScheme(
    primary          = SamvitOrb,
    onPrimary        = SamvitDeep,
    primaryContainer = SamvitOrbPulse,
    background       = SamvitDeep,
    surface          = SamvitSurface,
    onBackground     = SamvitText,
    onSurface        = SamvitText,
    secondary        = SamvitAccent,
    onSecondary      = SamvitDeep,
    error            = SamvitEmergency,
    outline          = SamvitDivider,
)

@Composable
fun SamvitTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = SamvitColorScheme,
        typography  = SamvitTypography,
        content     = content
    )
}
