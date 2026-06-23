package com.samvit.app.ui.observer

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.samvit.app.data.entities.CommandHistory
import com.samvit.app.data.entities.Reminder
import com.samvit.app.data.entities.TrustedContact
import com.samvit.app.ui.theme.*
import java.text.SimpleDateFormat
import java.util.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ObserverScreen(
    viewModel: ObserverViewModel,
    onBack: () -> Unit
) {
    val commands by viewModel.commands.collectAsState()
    val reminders by viewModel.reminders.collectAsState()
    val contacts  by viewModel.contacts.collectAsState()
    val memory    by viewModel.memory.collectAsState()

    var selectedTab by remember { mutableIntStateOf(0) }
    var showAddContact by remember { mutableStateOf(false) }

    val tabs = listOf("Activity", "Reminders", "Contacts", "Memory")

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        "Observer Dashboard",
                        color = SamvitText,
                        fontWeight = FontWeight.Light,
                        letterSpacing = 1.sp
                    )
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Default.ArrowBack, contentDescription = "Back", tint = SamvitAccent)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SamvitSurface),
                actions = {
                    if (selectedTab == 2) {
                        IconButton(onClick = { showAddContact = true }) {
                            Icon(Icons.Default.PersonAdd, contentDescription = "Add Contact", tint = SamvitAccent)
                        }
                    }
                }
            )
        },
        containerColor = SamvitDeep
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .background(SamvitDeep)
        ) {
            // Tab row
            TabRow(
                selectedTabIndex = selectedTab,
                containerColor = SamvitSurface,
                contentColor = SamvitAccent,
                indicator = { tabPositions ->
                    Box(
                        Modifier
                            .tabIndicatorOffset(tabPositions[selectedTab])
                            .height(2.dp)
                            .background(SamvitOrb)
                    )
                }
            ) {
                tabs.forEachIndexed { index, title ->
                    Tab(
                        selected = selectedTab == index,
                        onClick = { selectedTab = index },
                        text = {
                            Text(
                                title,
                                fontSize = 12.sp,
                                color = if (selectedTab == index) SamvitAccent else SamvitSubtext
                            )
                        }
                    )
                }
            }

            when (selectedTab) {
                0 -> ActivityFeed(commands)
                1 -> ReminderList(reminders, onDelete = viewModel::deleteReminder)
                2 -> ContactList(contacts, onDelete = viewModel::deleteContact)
                3 -> MemoryList(memory)
            }
        }
    }

    if (showAddContact) {
        AddContactDialog(
            onDismiss = { showAddContact = false },
            onAdd = { name, phone, camera ->
                viewModel.addContact(name, phone, camera)
                showAddContact = false
            }
        )
    }
}

@Composable
private fun ActivityFeed(commands: List<CommandHistory>) {
    val fmt = remember { SimpleDateFormat("dd MMM, HH:mm", Locale.getDefault()) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        if (commands.isEmpty()) {
            item { EmptyState("No activity yet") }
        }
        items(commands) { entry ->
            ActivityEntry(entry, fmt)
        }
    }
}

@Composable
private fun ActivityEntry(entry: CommandHistory, fmt: SimpleDateFormat) {
    val glyph = when (entry.category) {
        "EMERGENCY" -> "\uD83D\uDEA8"
        "REMINDER"  -> "\u23F0"
        "BROADCAST" -> "\uD83D\uDCCD"
        "CALL"      -> "\uD83D\uDCDE"
        else        -> "\uD83C\uDF99\uFE0F"
    }
    Card(
        colors = CardDefaults.cardColors(containerColor = SamvitSurface),
        modifier = Modifier.fillMaxWidth()
    ) {
        Row(
            modifier = Modifier.padding(12.dp),
            verticalAlignment = Alignment.Top,
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(glyph, fontSize = 18.sp)
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    entry.utterance,
                    color = SamvitText,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Normal
                )
                Text(
                    entry.resolvedAction,
                    color = SamvitSubtext,
                    fontSize = 11.sp,
                    fontFamily = FontFamily.Monospace
                )
            }
            Text(
                fmt.format(Date(entry.timestamp)),
                color = SamvitSubtext,
                fontSize = 10.sp
            )
        }
    }
}

@Composable
private fun ReminderList(reminders: List<Reminder>, onDelete: (Reminder) -> Unit) {
    val fmt = remember { SimpleDateFormat("dd MMM, HH:mm", Locale.getDefault()) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        if (reminders.isEmpty()) {
            item { EmptyState("No reminders set") }
        }
        items(reminders) { reminder ->
            Card(
                colors = CardDefaults.cardColors(containerColor = SamvitSurface),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Text("\u23F0", fontSize = 18.sp)
                    Column(Modifier.weight(1f)) {
                        Text(reminder.text, color = SamvitText, fontSize = 14.sp)
                        Text(
                            fmt.format(Date(reminder.triggerTimeMs)) +
                                    if (reminder.recurrenceIntervalMs > 0) " (recurring)" else "",
                            color = SamvitSubtext, fontSize = 11.sp
                        )
                    }
                    IconButton(onClick = { onDelete(reminder) }) {
                        Icon(Icons.Default.Delete, contentDescription = "Delete", tint = SamvitEmergency)
                    }
                }
            }
        }
    }
}

@Composable
private fun ContactList(contacts: List<TrustedContact>, onDelete: (TrustedContact) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        if (contacts.isEmpty()) {
            item { EmptyState("No trusted contacts added\nLong-press the orb to open this dashboard and add contacts") }
        }
        items(contacts) { contact ->
            Card(
                colors = CardDefaults.cardColors(containerColor = SamvitSurface),
                modifier = Modifier.fillMaxWidth()
            ) {
                Row(
                    modifier = Modifier.padding(12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Icon(Icons.Default.Person, contentDescription = null, tint = SamvitAccent)
                    Column(Modifier.weight(1f)) {
                        Text(contact.name, color = SamvitText, fontSize = 14.sp, fontWeight = FontWeight.Medium)
                        Text(contact.phone, color = SamvitSubtext, fontSize = 12.sp)
                        if (contact.allowCameraStream) {
                            Text("Camera stream: on", color = SamvitWarning, fontSize = 11.sp)
                        }
                    }
                    IconButton(onClick = { onDelete(contact) }) {
                        Icon(Icons.Default.Delete, contentDescription = "Remove", tint = SamvitEmergency)
                    }
                }
            }
        }
    }
}

@Composable
private fun MemoryList(memory: List<com.samvit.app.data.entities.MemoryEntry>) {
    val fmt = remember { SimpleDateFormat("dd MMM", Locale.getDefault()) }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        if (memory.isEmpty()) {
            item { EmptyState("Memory vault is empty") }
        }
        items(memory) { entry ->
            Card(
                colors = CardDefaults.cardColors(containerColor = SamvitSurface),
                modifier = Modifier.fillMaxWidth()
            ) {
                Column(Modifier.padding(12.dp)) {
                    Row(
                        horizontalArrangement = Arrangement.SpaceBetween,
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text(
                            entry.category,
                            color = SamvitOrb,
                            fontSize = 10.sp,
                            letterSpacing = 1.sp,
                            fontFamily = FontFamily.Monospace
                        )
                        Text(fmt.format(Date(entry.timestamp)), color = SamvitSubtext, fontSize = 10.sp)
                    }
                    Spacer(Modifier.height(4.dp))
                    Text(entry.key, color = SamvitSubtext, fontSize = 11.sp)
                    Text(entry.value, color = SamvitText, fontSize = 13.sp)
                }
            }
        }
    }
}

@Composable
private fun EmptyState(message: String) {
    Box(Modifier.fillMaxWidth().padding(vertical = 64.dp), contentAlignment = Alignment.Center) {
        Text(message, color = SamvitSubtext, fontSize = 14.sp)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AddContactDialog(onDismiss: () -> Unit, onAdd: (String, String, Boolean) -> Unit) {
    var name by remember { mutableStateOf("") }
    var phone by remember { mutableStateOf("") }
    var camera by remember { mutableStateOf(false) }

    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = SamvitSurface,
        title = { Text("Add Trusted Contact", color = SamvitText) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(
                    value = name, onValueChange = { name = it },
                    label = { Text("Name", color = SamvitSubtext) },
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = SamvitText,
                        unfocusedTextColor = SamvitText,
                        focusedBorderColor = SamvitOrb,
                        unfocusedBorderColor = SamvitDivider
                    )
                )
                OutlinedTextField(
                    value = phone, onValueChange = { phone = it },
                    label = { Text("Phone number", color = SamvitSubtext) },
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedTextColor = SamvitText,
                        unfocusedTextColor = SamvitText,
                        focusedBorderColor = SamvitOrb,
                        unfocusedBorderColor = SamvitDivider
                    )
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Switch(
                        checked = camera,
                        onCheckedChange = { camera = it },
                        colors = SwitchDefaults.colors(checkedThumbColor = SamvitOrb)
                    )
                    Spacer(Modifier.width(8.dp))
                    Text("Allow camera stream", color = SamvitSubtext, fontSize = 13.sp)
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { if (name.isNotBlank() && phone.isNotBlank()) onAdd(name, phone, camera) }) {
                Text("Add", color = SamvitOrb)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = SamvitSubtext) }
        }
    )
}

@Composable
private fun TabRowScope.tabIndicatorOffset(tabPosition: TabPosition) = this
