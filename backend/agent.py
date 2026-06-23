"""
agent.py — Agentic flow engine for VisionPilot.

Takes a high-level user goal (voice or text), decomposes it into
executable steps, runs them sequentially against the phone's screen
context, and narrates every action back to the user via TTS.

Features:
  - Multi-step goal planning via Gemini or heuristic fallback
  - Screenshot vision (Gemini multimodal) when accessibility labels are weak
  - OCR via Gemini vision (no extra model — same multimodal call)
  - Persistent memory across sessions (remembers logins, past actions, prefs)
  - User confirmation for risky actions (passwords, posting, payments)
  - Voice-controllable narration at every step
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("agent")


# ─── Action vocabulary the agent can emit ────────────────────────────

class ActionType(str, Enum):
    TAP = "tap"
    LONG_PRESS = "long_press"
    TYPE_TEXT = "type_text"
    SCROLL_DOWN = "scroll_down"
    SCROLL_UP = "scroll_up"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    PRESS_BACK = "press_back"
    PRESS_HOME = "press_home"
    OPEN_APP = "open_app"
    WAIT = "wait"
    DONE = "done"
    FAIL = "fail"
    CONFIRM = "confirm"  # Pauses and asks user for permission


@dataclass
class AgentAction:
    """A single atomic action the agent wants the phone to perform."""
    action: ActionType
    target: str = ""
    value: str = ""
    narration: str = ""
    x: int = 0
    y: int = 0
    confidence: float = 1.0
    requires_confirmation: bool = False  # True = pause & ask user
    confirmation_message: str = ""       # What to ask


@dataclass
class StepResult:
    """What the phone reports back after executing an action."""
    success: bool
    screen_description: str = ""
    elements_json: str = "[]"
    error: str = ""
    screenshot_base64: str = ""  # Optional screenshot for vision


@dataclass
class AgentPlan:
    """High-level plan the agent creates from a user goal."""
    goal: str
    steps: list[str] = field(default_factory=list)
    current_step: int = 0
    status: str = "planning"  # planning | executing | awaiting_confirmation | completed | failed


# ─── Memory system ───────────────────────────────────────────────────

MEMORY_FILE = Path(os.environ.get("AGENT_MEMORY_PATH", "agent_memory.json"))


class AgentMemory:
    """
    Persistent memory that survives across sessions.
    Stores: credentials (encrypted ref only), past goals, app states,
    user preferences, learned patterns.
    """

    def __init__(self, path: Path = MEMORY_FILE):
        self._path = path
        self._data: dict[str, Any] = {
            "credentials": {},     # app_name -> {"username": ..., "has_password": True}
            "past_goals": [],      # list of {"goal": ..., "outcome": ..., "timestamp": ...}
            "app_states": {},      # app_name -> {"logged_in": bool, "last_used": timestamp}
            "user_preferences": {},  # key -> value
            "learned_patterns": [],  # {"trigger": ..., "action": ..., "confidence": ...}
        }
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
                log.info("Loaded agent memory from %s", self._path)
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Could not load memory: %s", e)

    def save(self):
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2))
        except OSError as e:
            log.warning("Could not save memory: %s", e)

    def remember_credential(self, app: str, username: str):
        """Store that we know a login for this app (NOT the password itself)."""
        self._data["credentials"][app.lower()] = {
            "username": username,
            "has_password": True,
            "last_login": time.time(),
        }
        self.save()

    def get_credential(self, app: str) -> Optional[dict]:
        return self._data["credentials"].get(app.lower())

    def is_logged_in(self, app: str) -> bool:
        state = self._data["app_states"].get(app.lower(), {})
        return state.get("logged_in", False)

    def set_logged_in(self, app: str, logged_in: bool):
        app_key = app.lower()
        if app_key not in self._data["app_states"]:
            self._data["app_states"][app_key] = {}
        self._data["app_states"][app_key]["logged_in"] = logged_in
        self._data["app_states"][app_key]["last_used"] = time.time()
        self.save()

    def log_goal(self, goal: str, outcome: str):
        self._data["past_goals"].append({
            "goal": goal,
            "outcome": outcome,
            "timestamp": time.time(),
        })
        # Keep only last 50 goals
        self._data["past_goals"] = self._data["past_goals"][-50:]
        self.save()

    def get_recent_goals(self, n: int = 5) -> list[dict]:
        return self._data["past_goals"][-n:]

    def set_preference(self, key: str, value: Any):
        self._data["user_preferences"][key] = value
        self.save()

    def get_preference(self, key: str, default=None):
        return self._data["user_preferences"].get(key, default)

    def learn_pattern(self, trigger: str, action: str, confidence: float = 0.8):
        self._data["learned_patterns"].append({
            "trigger": trigger,
            "action": action,
            "confidence": confidence,
        })
        self._data["learned_patterns"] = self._data["learned_patterns"][-100:]
        self.save()

    def find_pattern(self, trigger: str) -> Optional[dict]:
        trigger_lower = trigger.lower()
        for p in reversed(self._data["learned_patterns"]):
            if p["trigger"].lower() in trigger_lower or trigger_lower in p["trigger"].lower():
                return p
        return None

    def get_context_summary(self) -> str:
        """Return a summary for LLM context injection."""
        parts = []
        if self._data["credentials"]:
            apps = list(self._data["credentials"].keys())
            parts.append(f"Known logins: {', '.join(apps)}")
        logged_in = [app for app, s in self._data["app_states"].items() if s.get("logged_in")]
        if logged_in:
            parts.append(f"Currently logged into: {', '.join(logged_in)}")
        recent = self.get_recent_goals(3)
        if recent:
            goals_str = "; ".join(g["goal"][:40] for g in recent)
            parts.append(f"Recent goals: {goals_str}")
        return " | ".join(parts) if parts else "No prior memory."


# ─── Risky action detection ──────────────────────────────────────────

RISKY_KEYWORDS = [
    "password", "sign in", "log in", "login", "submit", "post", "comment",
    "send message", "purchase", "buy", "pay", "confirm order", "delete",
    "unsubscribe", "deactivate", "remove account",
]


def is_risky_action(step: str, action_value: str = "") -> bool:
    """Check if an action should require user confirmation."""
    combined = f"{step} {action_value}".lower()
    return any(kw in combined for kw in RISKY_KEYWORDS)


def get_confirmation_message(step: str) -> str:
    """Generate a user-friendly confirmation message."""
    step_lower = step.lower()
    if "password" in step_lower or "sign in" in step_lower or "log in" in step_lower:
        return "I'm about to enter login credentials. Should I proceed?"
    elif "post" in step_lower or "comment" in step_lower or "send" in step_lower:
        return "I'm about to post or send something publicly. Should I proceed?"
    elif "purchase" in step_lower or "buy" in step_lower or "pay" in step_lower:
        return "I'm about to make a purchase or payment. Should I proceed?"
    elif "delete" in step_lower or "remove" in step_lower:
        return "I'm about to delete something. This may be irreversible. Should I proceed?"
    return f"I'm about to: {step}. Should I proceed?"


# ─── Gemini-backed planning and reasoning ────────────────────────────

PLAN_SYSTEM_PROMPT = """\
You are the AI brain of VisionPilot, a smartphone assistant for visually \
impaired users. You control an Android phone through screen actions.

Given a user's goal, produce a JSON plan with concrete steps.
Each step should be a short imperative sentence describing one screen action.

Rules:
- Be specific: "Tap the search bar at the top" not "search"
- Include navigation: "Open Chrome browser" before "Type in the URL bar"
- Account for common popups: "Dismiss cookie banner if present"
- Keep steps atomic: one tap/type/scroll per step
- Maximum 20 steps
- Mark steps that involve passwords/posting/payments with [CONFIRM] prefix

Memory context: {memory_context}

Output format (strict JSON, no markdown):
{"goal": "...", "steps": ["step 1", "[CONFIRM] step 2", ...]}
"""

STEP_SYSTEM_PROMPT = """\
You are VisionPilot's action engine. You receive:
1. The current goal and which step you're on
2. The current screen state (UI elements with labels and positions)
3. The step instruction to execute
4. Memory context about the user

Decide the SINGLE best action to perform. Pick from:
  tap, long_press, type_text, scroll_down, scroll_up, swipe_left,
  swipe_right, press_back, press_home, open_app, wait, done, fail, confirm

Use "confirm" if the step involves sensitive actions (passwords, posting, payments).

Output strict JSON (no markdown):
{
  "action": "tap|type_text|...",
  "target": "element label or description to interact with",
  "value": "text to type or app name (if applicable, else empty string)",
  "narration": "short sentence telling the user what you're doing",
  "x": 0, "y": 0,
  "confidence": 0.95,
  "requires_confirmation": false
}

If the goal is complete, use action "done".
If something is wrong and you can't proceed, use action "fail" and explain in narration.
"""

VISION_PROMPT = """\
You are VisionPilot's screen reader. Analyze this screenshot of an Android phone.

The accessibility tree reports these elements (may be incomplete or poorly labeled):
{elements_json}

Current step the agent is trying to do: {step_instruction}

Tasks:
1. Identify ALL interactive elements visible on screen (buttons, links, text fields, icons)
2. For any unlabeled or poorly labeled elements, use visual OCR to determine their text/purpose
3. Provide coordinates (bounds) for each element
4. Note any popups, dialogs, or overlays that may be blocking interaction

Output strict JSON (no markdown):
{
  "screen_summary": "brief description of what's on screen",
  "elements": [
    {"type": "Button|Input|Link|Icon|Text", "label": "visible text or inferred purpose",
     "left": int, "top": int, "right": int, "bottom": int, "confidence": float}
  ],
  "ocr_text": ["any text found via OCR not in accessibility tree"],
  "blocking_overlay": false
}
"""


class VisionAgent:
    """
    Agentic controller that turns voice commands into multi-step
    phone automation sequences.

    Features:
      - Gemini-powered planning with heuristic fallback
      - Screenshot vision for when accessibility labels are weak
      - Persistent memory across sessions
      - User confirmation for risky actions
    """

    def __init__(self, gemini_model=None, api_key: str = "", memory_path: str = ""):
        self._model = None
        self._genai = None
        self._setup_gemini(gemini_model, api_key)
        self.memory = AgentMemory(Path(memory_path) if memory_path else MEMORY_FILE)
        self.current_plan: Optional[AgentPlan] = None
        self.action_history: list[AgentAction] = []
        self.max_retries_per_step = 3
        self.max_total_actions = 30
        self._retry_count = 0
        self._pending_confirmation: Optional[AgentAction] = None
        self._vision_used_count = 0  # Track vision calls to stay efficient

    def _setup_gemini(self, model, api_key: str):
        try:
            import google.generativeai as genai
            self._genai = genai
            if api_key:
                genai.configure(api_key=api_key)
            self._model = model or genai.GenerativeModel(
                "gemini-2.0-flash",
                generation_config={"temperature": 0.2, "max_output_tokens": 1024},
            )
        except ImportError:
            log.warning("google-generativeai not installed — agent will use fallback planning")

    # ── Vision (screenshot analysis + OCR) ───────────────────────

    def analyze_screenshot(self, screenshot_b64: str, elements_json: str = "[]",
                           step_instruction: str = "") -> dict:
        """
        Use Gemini multimodal to analyze a screenshot when accessibility
        labels are insufficient. Also performs OCR on visible text.

        Only called when needed (elements are empty/unlabeled).
        """
        if not self._model or not screenshot_b64:
            return {"screen_summary": "", "elements": [], "ocr_text": [], "blocking_overlay": False}

        try:
            image_data = base64.b64decode(screenshot_b64)
            prompt = VISION_PROMPT.format(
                elements_json=elements_json,
                step_instruction=step_instruction,
            )
            contents = [
                {"mime_type": "image/png", "data": image_data},
                prompt,
            ]
            resp = self._model.generate_content(contents)
            raw = resp.text.strip().replace("```json", "").replace("```", "")
            result = json.loads(raw)
            self._vision_used_count += 1
            log.info("Vision analysis complete (call #%d): %s",
                     self._vision_used_count, result.get("screen_summary", ""))
            return result
        except Exception as e:
            log.error("Vision analysis failed: %s", e)
            return {"screen_summary": "", "elements": [], "ocr_text": [], "blocking_overlay": False}

    def _needs_vision(self, elements_json: str) -> bool:
        """Decide if we should use screenshot vision (expensive) or not."""
        try:
            elements = json.loads(elements_json) if elements_json else []
        except (json.JSONDecodeError, TypeError):
            return True  # Can't parse → need vision

        if not elements:
            return True  # No elements → need vision

        # Check if elements have meaningful labels
        labeled = sum(1 for el in elements if el.get("label", "").strip())
        if labeled < len(elements) * 0.3:
            return True  # Less than 30% labeled → need vision

        return False

    # ── Confirmation handling ────────────────────────────────────

    def confirm_action(self, approved: bool) -> AgentAction:
        """User responds to a confirmation prompt."""
        if not self._pending_confirmation:
            return AgentAction(action=ActionType.WAIT, narration="Nothing to confirm.")

        if approved:
            action = self._pending_confirmation
            action.requires_confirmation = False
            self._pending_confirmation = None
            if self.current_plan:
                self.current_plan.status = "executing"
            return action
        else:
            self._pending_confirmation = None
            if self.current_plan:
                self.current_plan.current_step += 1  # Skip this step
                self.current_plan.status = "executing"
            return AgentAction(
                action=ActionType.WAIT,
                narration="Understood. Skipping that step.",
            )

    # ── Planning ─────────────────────────────────────────────────

    def plan(self, user_goal: str) -> AgentPlan:
        """Decompose a user goal into ordered steps."""
        log.info("Planning goal: %s", user_goal)

        if self._model:
            try:
                memory_ctx = self.memory.get_context_summary()
                prompt = PLAN_SYSTEM_PROMPT.format(memory_context=memory_ctx)
                resp = self._model.generate_content(
                    [prompt, f"User goal: {user_goal}"]
                )
                raw = resp.text.strip().replace("```json", "").replace("```", "")
                data = json.loads(raw)
                plan = AgentPlan(
                    goal=data.get("goal", user_goal),
                    steps=data.get("steps", []),
                    status="executing",
                )
                self.current_plan = plan
                log.info("Plan created with %d steps", len(plan.steps))
                return plan
            except Exception as e:
                log.error("Gemini planning failed: %s — using fallback", e)

        plan = self._fallback_plan(user_goal)
        self.current_plan = plan
        return plan

    def _fallback_plan(self, goal: str) -> AgentPlan:
        """Rule-based fallback when LLM is unavailable."""
        goal_lower = goal.lower()
        steps: list[str] = []

        # Check memory for learned patterns
        pattern = self.memory.find_pattern(goal_lower)
        if pattern:
            steps = [pattern["action"]]

        elif "open" in goal_lower:
            app = goal_lower.split("open")[-1].strip()
            steps = [f"Open the {app} app", f"Wait for {app} to load"]

        elif "search" in goal_lower and ("google" in goal_lower or "reddit" in goal_lower):
            query = goal_lower.split("for")[-1].strip() if "for" in goal_lower else "query"
            steps = [
                "Open Chrome browser",
                "Tap the search/URL bar at the top",
                f"Type: {query}",
                "Tap the search/go button on keyboard",
                "Wait for search results to load",
            ]
            if "reddit" in goal_lower:
                steps.append("Look for Reddit result and tap it")
                steps.append("Wait for Reddit page to load")

        elif "sign in" in goal_lower or "log in" in goal_lower or "login" in goal_lower:
            steps = [
                "Look for Sign In or Log In button and tap it",
                "[CONFIRM] Enter username/email in the input field",
                "[CONFIRM] Enter password in the password field",
                "[CONFIRM] Tap Sign In / Log In / Submit button",
                "Wait for login to complete",
            ]

        elif "comment" in goal_lower or "post" in goal_lower:
            steps = [
                "Find the comment box or reply button",
                "Tap the comment/reply input field",
                f"Type the comment text",
                "[CONFIRM] Tap Post / Submit / Send button",
                "Wait for confirmation",
            ]

        elif "call" in goal_lower:
            contact = goal_lower.split("call")[-1].strip()
            steps = [
                "Open the Phone app",
                f"Search for contact: {contact}",
                f"Tap on {contact} in the results",
                "Tap the call button",
            ]

        elif "send" in goal_lower and ("message" in goal_lower or "whatsapp" in goal_lower):
            steps = [
                "Open WhatsApp",
                "Tap on the target chat",
                "Tap the message input field",
                "Type the message",
                "[CONFIRM] Tap the send button",
            ]

        else:
            steps = [
                "Analyze current screen",
                f"Attempt to fulfill: {goal}",
            ]

        return AgentPlan(goal=goal, steps=steps, status="executing")

    # ── Step execution ───────────────────────────────────────────

    def decide_action(self, screen_elements_json: str, screenshot_description: str = "",
                      screenshot_b64: str = "") -> AgentAction:
        """
        Given the current screen state and step, decide the next action.
        Uses screenshot vision when accessibility labels are insufficient.
        """
        if not self.current_plan or self.current_plan.status not in ("executing",):
            return AgentAction(action=ActionType.DONE, narration="No active plan.")

        plan = self.current_plan
        if plan.current_step >= len(plan.steps):
            plan.status = "completed"
            self.memory.log_goal(plan.goal, "completed")
            return AgentAction(action=ActionType.DONE, narration=f"Goal completed: {plan.goal}")

        if len(self.action_history) >= self.max_total_actions:
            plan.status = "failed"
            self.memory.log_goal(plan.goal, "failed_safety_limit")
            return AgentAction(action=ActionType.FAIL, narration="Safety limit reached. Stopping.")

        step_instruction = plan.steps[plan.current_step]

        # Check if this step requires confirmation
        needs_confirm = step_instruction.startswith("[CONFIRM]")
        if needs_confirm:
            step_instruction = step_instruction.replace("[CONFIRM]", "").strip()

        if not needs_confirm and is_risky_action(step_instruction):
            needs_confirm = True

        log.info("Step %d/%d: %s (confirm=%s)",
                 plan.current_step + 1, len(plan.steps), step_instruction, needs_confirm)

        # Decide if we need screenshot vision
        enriched_elements = screen_elements_json
        enriched_description = screenshot_description

        if self._needs_vision(screen_elements_json) and screenshot_b64:
            vision_result = self.analyze_screenshot(
                screenshot_b64, screen_elements_json, step_instruction
            )
            if vision_result["elements"]:
                enriched_elements = json.dumps(vision_result["elements"])
            if vision_result["screen_summary"]:
                enriched_description = vision_result["screen_summary"]
            # Append OCR text to description
            if vision_result.get("ocr_text"):
                enriched_description += " | OCR: " + ", ".join(vision_result["ocr_text"])

        # Get action from LLM or fallback
        action = self._get_action(step_instruction, enriched_elements, enriched_description)

        # Apply confirmation if needed
        if needs_confirm:
            action.requires_confirmation = True
            action.confirmation_message = get_confirmation_message(step_instruction)
            self._pending_confirmation = action
            plan.status = "awaiting_confirmation"
            action_copy = AgentAction(
                action=ActionType.CONFIRM,
                narration=action.confirmation_message,
                requires_confirmation=True,
                confirmation_message=action.confirmation_message,
            )
            return action_copy

        self.action_history.append(action)
        return action

    def _get_action(self, step_instruction: str, elements_json: str,
                    screen_description: str) -> AgentAction:
        """Get action from Gemini or fallback."""
        if self._model:
            try:
                plan = self.current_plan
                memory_ctx = self.memory.get_context_summary()
                context = (
                    f"Goal: {plan.goal}\n"
                    f"Step {plan.current_step + 1}/{len(plan.steps)}: {step_instruction}\n"
                    f"Screen: {screen_description}\n"
                    f"Memory: {memory_ctx}\n"
                    f"UI elements:\n{elements_json}"
                )
                resp = self._model.generate_content(
                    [STEP_SYSTEM_PROMPT, context]
                )
                raw = resp.text.strip().replace("```json", "").replace("```", "")
                data = json.loads(raw)
                return AgentAction(
                    action=ActionType(data.get("action", "wait")),
                    target=data.get("target", ""),
                    value=data.get("value", ""),
                    narration=data.get("narration", step_instruction),
                    x=data.get("x", 0),
                    y=data.get("y", 0),
                    confidence=data.get("confidence", 0.8),
                    requires_confirmation=data.get("requires_confirmation", False),
                )
            except Exception as e:
                log.error("Gemini step reasoning failed: %s — using fallback", e)

        return self._fallback_action(step_instruction, elements_json)

    def _fallback_action(self, step: str, elements_json: str) -> AgentAction:
        """Heuristic action when LLM is unavailable."""
        step_lower = step.lower()

        if step_lower.startswith("open"):
            app = step.split("Open")[-1].split("the")[-1].strip().rstrip(" app")
            return AgentAction(
                action=ActionType.OPEN_APP,
                value=app,
                narration=f"Opening {app}",
            )
        elif step_lower.startswith("type") or step_lower.startswith("enter"):
            text = step.split(":", 1)[-1].strip() if ":" in step else step.split("Type")[-1].strip()
            return AgentAction(
                action=ActionType.TYPE_TEXT,
                value=text,
                narration=f"Typing: {text}",
            )
        elif "tap" in step_lower or "click" in step_lower or "press" in step_lower:
            target = step
            try:
                elements = json.loads(elements_json) if elements_json else []
                for el in elements:
                    label = el.get("label", "").lower()
                    if any(word in label for word in step_lower.split() if len(word) > 3):
                        return AgentAction(
                            action=ActionType.TAP,
                            target=el.get("label", target),
                            x=(el.get("left", 0) + el.get("right", 0)) // 2,
                            y=(el.get("top", 0) + el.get("bottom", 0)) // 2,
                            narration=f"Tapping on {el.get('label', target)}",
                        )
            except (json.JSONDecodeError, TypeError):
                pass
            return AgentAction(
                action=ActionType.TAP,
                target=target,
                narration=f"Tapping: {target}",
            )
        elif "scroll" in step_lower:
            direction = ActionType.SCROLL_DOWN if "down" in step_lower else ActionType.SCROLL_UP
            return AgentAction(action=direction, narration="Scrolling the screen")
        elif "wait" in step_lower:
            return AgentAction(action=ActionType.WAIT, narration="Waiting for the screen to update")
        elif "back" in step_lower:
            return AgentAction(action=ActionType.PRESS_BACK, narration="Going back")
        elif "search" in step_lower or "find" in step_lower or "look for" in step_lower:
            query = step.split(":")[-1].strip() if ":" in step else step.split("for")[-1].strip()
            return AgentAction(
                action=ActionType.SCROLL_DOWN,
                narration=f"Looking for: {query}",
            )
        else:
            return AgentAction(
                action=ActionType.WAIT,
                narration=f"Analyzing: {step}",
            )

    def advance_step(self, result: StepResult) -> AgentAction:
        """
        Called after the phone executes an action. Evaluates the result,
        advances the plan, and returns the next action.
        """
        if not self.current_plan:
            return AgentAction(action=ActionType.DONE, narration="No plan active.")

        plan = self.current_plan

        # If awaiting confirmation, don't advance
        if plan.status == "awaiting_confirmation":
            return AgentAction(
                action=ActionType.CONFIRM,
                narration=self._pending_confirmation.confirmation_message if self._pending_confirmation else "Awaiting your confirmation.",
                requires_confirmation=True,
            )

        if result.success:
            self._retry_count = 0
            plan.current_step += 1

            # Update memory based on completed actions
            self._update_memory_from_step(plan)

            if plan.current_step >= len(plan.steps):
                plan.status = "completed"
                self.memory.log_goal(plan.goal, "completed")
                return AgentAction(
                    action=ActionType.DONE,
                    narration=f"All done! {plan.goal} completed successfully.",
                )
            return self.decide_action(
                result.elements_json, result.screen_description, result.screenshot_base64
            )
        else:
            self._retry_count += 1
            log.warning("Step failed (retry %d/%d): %s",
                        self._retry_count, self.max_retries_per_step, result.error)
            if self._retry_count >= self.max_retries_per_step:
                self._retry_count = 0
                plan.current_step += 1  # Skip stuck step
                if plan.current_step >= len(plan.steps):
                    plan.status = "failed"
                    self.memory.log_goal(plan.goal, "failed")
                    return AgentAction(
                        action=ActionType.FAIL,
                        narration=f"Could not complete: {plan.goal}. Stuck on a step.",
                    )
                return AgentAction(
                    action=ActionType.WAIT,
                    narration=f"Skipping stuck step. Moving to: {plan.steps[plan.current_step]}",
                )
            return self.decide_action(
                result.elements_json, result.screen_description, result.screenshot_base64
            )

    def _update_memory_from_step(self, plan: AgentPlan):
        """Update memory based on what step just completed."""
        if plan.current_step == 0:
            return
        prev_step = plan.steps[plan.current_step - 1].lower()
        if "sign in" in prev_step or "log in" in prev_step or "login" in prev_step:
            # Try to figure out which app
            for step in plan.steps:
                if "open" in step.lower():
                    app_name = step.split("Open")[-1].strip().rstrip(" app").strip()
                    self.memory.set_logged_in(app_name, True)
                    break

    def get_status_narration(self) -> str:
        """Return a human-readable status for TTS."""
        if not self.current_plan:
            return "No task in progress. Tell me what you'd like to do."
        plan = self.current_plan
        if plan.status == "completed":
            return f"Task completed: {plan.goal}"
        elif plan.status == "failed":
            return f"Task failed: {plan.goal}. Please try again or give me a different command."
        elif plan.status == "awaiting_confirmation":
            msg = self._pending_confirmation.confirmation_message if self._pending_confirmation else "Waiting for your permission."
            return f"Paused — {msg}"
        else:
            step_num = plan.current_step + 1
            total = len(plan.steps)
            current = plan.steps[plan.current_step] if plan.current_step < total else "finishing up"
            current = current.replace("[CONFIRM] ", "")
            return f"Step {step_num} of {total}: {current}"

    def reset(self):
        """Clear current plan and history."""
        self.current_plan = None
        self.action_history.clear()
        self._retry_count = 0
        self._pending_confirmation = None
        self._vision_used_count = 0
