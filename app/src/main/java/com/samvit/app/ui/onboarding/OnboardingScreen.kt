package com.samvit.app.ui.onboarding

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.samvit.app.ui.theme.*

@Composable
fun OnboardingScreen(onComplete: () -> Unit) {
    var step by remember { mutableIntStateOf(0) }

    val steps = listOf(
        OnboardingStep(
            emoji = "\uD83D\uDC41\uFE0F",
            title = "Samvit",
            subtitle = "Sanskrit for Conscious Awareness",
            body = "An AI-powered voice assistant for visually impaired individuals — no touch required after setup."
        ),
        OnboardingStep(
            emoji = "\uD83C\uDF99\uFE0F",
            title = "Just speak",
            subtitle = "Zero buttons. Always listening.",
            body = "Say anything — I'll understand. Try:\n\"Open WhatsApp and message Mum\"\n\"Find the nearest pharmacy open now\"\n\"Remind me to take my medication at 6pm\""
        ),
        OnboardingStep(
            emoji = "\uD83D\uDEA8",
            title = "Emergency system",
            subtitle = "Two-tier protection",
            body = "Say \"Emergency\" for Tier 1 — calls your contacts, sends location.\n\nSay \"Mayday Mayday\" for Tier 2 — also contacts emergency services with a 5-second cancel window."
        ),
        OnboardingStep(
            emoji = "\uD83D\uDCCD",
            title = "Trusted contacts",
            subtitle = "Your safety network",
            body = "Say \"I'm heading to the clinic\" to broadcast your journey and location to all your trusted contacts.\n\nAdd contacts in the Observer Dashboard (long press the orb)."
        ),
        OnboardingStep(
            emoji = "\uD83D\uDEE1\uFE0F",
            title = "Accessibility Service",
            subtitle = "One permission needed",
            body = "Samvit needs Accessibility Service access to read your screen and navigate apps on your behalf. Please enable it in Settings when prompted."
        )
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(SamvitDeep),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(40.dp)
        ) {
            val current = steps[step]

            Text(current.emoji, fontSize = 56.sp, textAlign = TextAlign.Center)
            Spacer(Modifier.height(32.dp))
            Text(
                current.title,
                color = SamvitText,
                fontSize = 28.sp,
                fontWeight = FontWeight.Light,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(8.dp))
            Text(
                current.subtitle,
                color = SamvitOrb,
                fontSize = 14.sp,
                letterSpacing = 1.sp,
                textAlign = TextAlign.Center
            )
            Spacer(Modifier.height(24.dp))
            Text(
                current.body,
                color = SamvitSubtext,
                fontSize = 16.sp,
                lineHeight = 24.sp,
                textAlign = TextAlign.Center
            )

            Spacer(Modifier.height(64.dp))

            // Step dots
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                steps.forEachIndexed { i, _ ->
                    Box(
                        modifier = Modifier
                            .size(if (i == step) 10.dp else 6.dp)
                            .background(
                                if (i == step) SamvitOrb else SamvitDivider,
                                shape = androidx.compose.foundation.shape.CircleShape
                            )
                    )
                }
            }

            Spacer(Modifier.height(32.dp))

            Button(
                onClick = {
                    if (step < steps.lastIndex) step++ else onComplete()
                },
                colors = ButtonDefaults.buttonColors(containerColor = SamvitOrb),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    if (step < steps.lastIndex) "Next" else "Let's go",
                    color = SamvitDeep,
                    fontWeight = FontWeight.Medium,
                    fontSize = 16.sp
                )
            }
        }
    }
}

private data class OnboardingStep(
    val emoji: String,
    val title: String,
    val subtitle: String,
    val body: String
)
