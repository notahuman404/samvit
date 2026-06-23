package com.samvit.app.ui.main

import androidx.compose.animation.core.*
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.samvit.app.ui.theme.*
import com.samvit.app.voice.OrchestratorState

@Composable
fun MainScreen(
    viewModel: MainViewModel,
    onLongPressOrb: () -> Unit
) {
    val state by viewModel.state.collectAsState()
    val lastUtterance by viewModel.lastUtterance.collectAsState()
    val lastReply by viewModel.lastReply.collectAsState()

    val orbColor = when (state) {
        OrchestratorState.EMERGENCY  -> SamvitMayday
        OrchestratorState.LISTENING  -> SamvitOrb
        OrchestratorState.PROCESSING -> SamvitWarning
        OrchestratorState.SPEAKING   -> SamvitAccent
        else                         -> SamvitOrbPulse
    }

    // Pulse animation
    val infiniteTransition = rememberInfiniteTransition(label = "orb_pulse")
    val pulseScale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = if (state == OrchestratorState.LISTENING) 1.12f else 1.04f,
        animationSpec = infiniteRepeatable(
            tween(900, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "pulse_scale"
    )
    val glowScale by infiniteTransition.animateFloat(
        initialValue = 1f,
        targetValue = if (state == OrchestratorState.LISTENING) 1.35f else 1.15f,
        animationSpec = infiniteRepeatable(
            tween(1200, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glow_scale"
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(SamvitDeep),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(48.dp),
            modifier = Modifier.padding(horizontal = 32.dp)
        ) {
            Spacer(Modifier.height(40.dp))

            // State label
            Text(
                text = when (state) {
                    OrchestratorState.LISTENING  -> "listening"
                    OrchestratorState.PROCESSING -> "thinking"
                    OrchestratorState.SPEAKING   -> "speaking"
                    OrchestratorState.EMERGENCY  -> "emergency active"
                    else                         -> "samvit"
                },
                color = SamvitSubtext,
                fontSize = 13.sp,
                letterSpacing = 3.sp,
                fontWeight = FontWeight.Medium
            )

            // Pulsating orb
            Box(contentAlignment = Alignment.Center) {
                // Glow halo
                Box(
                    modifier = Modifier
                        .size(220.dp)
                        .scale(glowScale)
                        .clip(CircleShape)
                        .background(
                            Brush.radialGradient(
                                colors = listOf(orbColor.copy(alpha = 0.18f), orbColor.copy(alpha = 0f))
                            )
                        )
                )
                // Core orb
                Box(
                    modifier = Modifier
                        .size(140.dp)
                        .scale(pulseScale)
                        .clip(CircleShape)
                        .background(
                            Brush.radialGradient(
                                colors = listOf(orbColor.copy(alpha = 0.9f), orbColor.copy(alpha = 0.4f))
                            )
                        )
                        .pointerInput(Unit) {
                            detectTapGestures(onLongPress = { onLongPressOrb() })
                        }
                )
            }

            // Last utterance — large, high-contrast, for ambient third-party legibility
            if (lastUtterance.isNotBlank()) {
                Text(
                    text = "\u201C${lastUtterance}\u201D",
                    color = SamvitText,
                    fontSize = 22.sp,
                    fontWeight = FontWeight.Light,
                    textAlign = TextAlign.Center,
                    lineHeight = 30.sp,
                    modifier = Modifier.fillMaxWidth()
                )
            }

            // Agent reply
            if (lastReply.isNotBlank()) {
                Text(
                    text = lastReply,
                    color = SamvitAccent,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Normal,
                    textAlign = TextAlign.Center,
                    lineHeight = 22.sp,
                    modifier = Modifier.fillMaxWidth()
                )
            }

            Spacer(Modifier.weight(1f))

            // Hint
            Text(
                text = "long press orb \u2022 observer dashboard",
                color = SamvitSubtext.copy(alpha = 0.5f),
                fontSize = 11.sp,
                letterSpacing = 1.sp,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(32.dp))
        }
    }
}
