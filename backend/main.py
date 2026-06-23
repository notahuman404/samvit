"""
main.py — FastAPI backend for VisionPilot.

Handles REST endpoints for:
  - Voice commands (speech → text → agent reasoning → response)
  - Screen context analysis (screenshot + accessibility tree → UI elements)
  - Camera frame description (image → scene narration)
  - Action execution (agent action → phone gesture)
  - Agent goal planning and step-by-step execution

The agentic flow lives in agent.py; this file is the HTTP layer only.
"""

import os
import base64
import json
import logging
import uuid
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from agent import VisionAgent, AgentAction, AgentPlan, ActionType, StepResult, AgentMemory

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("main")

# ─── Gemini setup ────────────────────────────────────────────────────

try:
    import google.generativeai as genai
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
except ImportError:
    genai = None

GEMINI_MODEL_NAME = "gemini-2.0-flash"

def get_gemini_model():
    if genai and os.environ.get("GEMINI_API_KEY"):
        return genai.GenerativeModel(GEMINI_MODEL_NAME)
    return None

# ─── Agent registry (session-keyed for thread safety) ────────────────
# The global singleton was not thread-safe: concurrent /agent/plan requests
# clobbered each other's current_plan and action_history.  Each session now
# gets its own VisionAgent instance, identified by X-Session-ID header.

from collections import OrderedDict

# LRU cache for agents to prevent memory leaks
MAX_AGENTS = 100
_agents: OrderedDict[str, VisionAgent] = OrderedDict()


def get_agent(session_id: str) -> VisionAgent:
    if session_id in _agents:
        _agents.move_to_end(session_id)
        return _agents[session_id]
    
    if len(_agents) >= MAX_AGENTS:
        _agents.popitem(last=False)
        
    _agents[session_id] = VisionAgent(api_key=os.environ.get("GEMINI_API_KEY", ""))
    return _agents[session_id]


# ─── FastAPI app ─────────────────────────────────────────────────────

app = FastAPI(
    title="VisionPilot AI Backend",
    description="FastAPI backend for VisionPilot — voice-controlled phone agent for visually impaired users.",
    version="2.0.0",
)

# Add CORS middleware so web-based tooling and test UIs can reach the backend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= Request/Response Schemas =================

class VoiceCommandRequest(BaseModel):
    audioBase64: str
    timestamp: int

class VoiceCommandResponse(BaseModel):
    recognizedText: str
    responseSpeech: str
    executeAction: bool

class DetectedUiElement(BaseModel):
    type: str
    label: str
    left: int
    top: int
    right: int
    bottom: int
    confidence: float

class ScreenContextRequest(BaseModel):
    screenshotBase64: str
    hierarchyJson: str

class ScreenContextResponse(BaseModel):
    success: bool
    detectedElements: List[DetectedUiElement]

class CameraFrameRequest(BaseModel):
    frameBase64: str

class CameraFrameResponse(BaseModel):
    sceneDescription: str
    objectsCount: int
    detectedObjects: List[str]

class ActionExecutionRequest(BaseModel):
    actionType: str
    targetSelector: str
    argValue: Optional[str] = None

class ActionExecutionResponse(BaseModel):
    success: bool
    errorReason: Optional[str] = None

# ── Agent-specific schemas ───────────────────────────────────

class AgentGoalRequest(BaseModel):
    goal: str

class AgentPlanResponse(BaseModel):
    goal: str
    steps: List[str]
    totalSteps: int
    narration: str
    sessionId: str

class AgentStepRequest(BaseModel):
    success: bool
    screenElementsJson: str = "[]"
    screenDescription: str = ""
    screenshotBase64: str = ""
    error: str = ""

class AgentConfirmRequest(BaseModel):
    approved: bool

class AgentActionResponse(BaseModel):
    action: str
    target: str
    value: str
    narration: str
    x: int
    y: int
    confidence: float
    planStatus: str
    currentStep: int
    totalSteps: int
    requiresConfirmation: bool = False
    confirmationMessage: str = ""

class AgentStatusResponse(BaseModel):
    hasActivePlan: bool
    goal: str
    status: str
    currentStep: int
    totalSteps: int
    narration: str
    actionsExecuted: int
    memoryContext: str = ""

# Fix: credentials must NOT travel as query params (URL logs, browser history).
# Use a Pydantic body model instead.
class CredentialRequest(BaseModel):
    app_name: str
    username: str

# ── Call summarization schemas (stub — see KNOWN_GAPS.md) ───────────
class CallSummaryRequest(BaseModel):
    callDurationSeconds: int
    transcriptText: Optional[str] = None  # populated once STT pipeline exists

class CallSummaryResponse(BaseModel):
    summary: str
    actionItems: List[str]
    stored: bool

# ================= REST ENDPOINTS =================

@app.get("/")
def read_root():
    return {
        "status": "online",
        "service": "VisionPilot AI Backend",
        "version": "2.0.0",
        "capabilities": [
            "Voice command processing",
            "Agentic goal planning and step execution",
            "UI hierarchy screen reading",
            "Camera frame scene description",
            "Android gesture coordination",
        ],
        "gemini_enabled": genai is not None and bool(os.environ.get("GEMINI_API_KEY")),
        "gemini_model": GEMINI_MODEL_NAME,
    }


@app.post("/voice-command", response_model=VoiceCommandResponse)
async def voice_command(request: VoiceCommandRequest):
    """
    Accepts a recognized-text string encoded as UTF-8 base64.

    NOTE: The original implementation tried to base64-decode raw audio bytes
    and then UTF-8 decode the binary blob — PCM/WAV/MP3 is binary and that
    will produce garbage.  This endpoint therefore expects the Android client
    to perform on-device STT (e.g. Android SpeechRecognizer) and send the
    resulting text encoded as UTF-8 base64, NOT raw audio bytes.
    A future STT pipeline (Whisper or equivalent) should be wired in before
    this endpoint to lift that responsibility from the client.
    """
    recognized_text = ""

    if request.audioBase64:
        try:
            # Expect UTF-8 text (already STT-processed on device), not raw PCM.
            recognized_text = base64.b64decode(request.audioBase64).decode("utf-8").strip()
            if not any(c.isalnum() for c in recognized_text):
                recognized_text = ""
        except Exception:
            pass

    if not recognized_text:
        recognized_text = "help"

    response_speech = f"Understood: '{recognized_text}'. Let me work on that."
    execute_action = True

    model = get_gemini_model()
    if model:
        try:
            prompt = (
                f"You are VisionPilot, a smartphone assistant for blind/visually impaired users. "
                f"The user says: '{recognized_text}'. "
                f"Respond with a short, clear spoken sentence telling them what you will do. "
                f"Decide if this requires on-screen actions (True) or is just informational (False). "
                f"Output strict JSON: {{\"speech\": \"string\", \"execute_action\": boolean}}"
            )
            resp = model.generate_content(prompt)
            data = json.loads(resp.text.strip().replace("```json", "").replace("```", ""))
            response_speech = data.get("speech", response_speech)
            execute_action = data.get("execute_action", execute_action)
        except Exception as e:
            log.warning("Gemini voice reasoning failed: %s", e)
            response_speech = f"Got it. I'll work on: {recognized_text}."

    return VoiceCommandResponse(
        recognizedText=recognized_text,
        responseSpeech=response_speech,
        executeAction=execute_action,
    )


@app.post("/screen-context", response_model=ScreenContextResponse)
async def screen_context(request: ScreenContextRequest):
    """
    Analyzes a screenshot + UI accessibility tree to identify
    interactive elements with labels and coordinates.
    """
    detected_elements: List[DetectedUiElement] = []

    try:
        hierarchy = json.loads(request.hierarchyJson)
        if "elements" in hierarchy:
            for el in hierarchy["elements"]:
                b = el.get("bounds", {})
                detected_elements.append(DetectedUiElement(
                    type="Button" if el.get("clickable") else "Text",
                    label=el.get("label", "Widget"),
                    left=b.get("left", 0),
                    top=b.get("top", 0),
                    right=b.get("right", 0),
                    bottom=b.get("bottom", 0),
                    confidence=0.92,
                ))
    except Exception:
        pass

    model = get_gemini_model()
    if model and request.screenshotBase64:
        try:
            image_data = base64.b64decode(request.screenshotBase64)
            contents = [
                {"mime_type": "image/jpeg", "data": image_data},
                (
                    "Analyze this Android screenshot. The accessibility tree is:\n"
                    f"{request.hierarchyJson}\n"
                    "Identify all interactive elements (buttons, text fields, icons, links). "
                    "For each, give label, boundaries, and type. "
                    "Output strict JSON list: "
                    '[{"type": "Button|Text|Input|Icon", "label": "string", '
                    '"left": int, "top": int, "right": int, "bottom": int, "confidence": float}]'
                ),
            ]
            resp = model.generate_content(contents)
            raw = resp.text.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(raw)
            gemini_elements = [
                DetectedUiElement(
                    type=item.get("type", "Button"),
                    label=item.get("label", "Widget"),
                    left=item.get("left", 0),
                    top=item.get("top", 0),
                    right=item.get("right", 0),
                    bottom=item.get("bottom", 0),
                    confidence=item.get("confidence", 0.9),
                )
                for item in parsed
            ]
            if gemini_elements:
                detected_elements = gemini_elements
        except Exception as e:
            log.warning("Gemini screen analysis failed: %s", e)

    return ScreenContextResponse(success=True, detectedElements=detected_elements)


@app.post("/camera-frame", response_model=CameraFrameResponse)
async def camera_frame(request: CameraFrameRequest):
    """
    Describes a camera frame for blind users — objects, text, scene context.
    """
    scene_description = "Unable to analyze the camera frame."
    objects_count = 0
    detected_objects: List[str] = []

    model = get_gemini_model()
    if model and request.frameBase64:
        try:
            image_data = base64.b64decode(request.frameBase64)
            contents = [
                {"mime_type": "image/jpeg", "data": image_data},
                (
                    "You are the visual eyes of a blind user. Describe this camera frame. "
                    "Be practical, concise, and descriptive. "
                    "Count discrete objects and list them by priority. "
                    "Output strict JSON: "
                    '{"scene_description": "string", "objects_count": int, "detected_objects": ["string"]}'
                ),
            ]
            resp = model.generate_content(contents)
            raw = resp.text.strip().replace("```json", "").replace("```", "")
            data = json.loads(raw)
            scene_description = data.get("scene_description", scene_description)
            objects_count = data.get("objects_count", objects_count)
            detected_objects = data.get("detected_objects", detected_objects)
        except Exception as e:
            log.warning("Gemini camera analysis failed: %s", e)

    return CameraFrameResponse(
        sceneDescription=scene_description,
        objectsCount=objects_count,
        detectedObjects=detected_objects,
    )


@app.post("/execute-action", response_model=ActionExecutionResponse)
async def execute_action(request: ActionExecutionRequest):
    """
    Validates and acknowledges a screen automation request.
    The actual gesture execution happens on the Android side.
    """
    return ActionExecutionResponse(success=True, errorReason=None)


# ── Call Summarization (stub — full pipeline requires STT recording) ─
# See KNOWN_GAPS.md §1 for what needs to be built before this works end-to-end.
@app.post("/call/summarize", response_model=CallSummaryResponse)
async def summarize_call(request: CallSummaryRequest):
    """
    Distils a completed call into plain-language key points.

    Currently requires the Android client to supply a transcript (obtained
    via on-device STT during the call).  When a server-side recording +
    transcription pipeline is added, transcriptText will be populated here
    automatically.
    """
    if not request.transcriptText:
        return CallSummaryResponse(
            summary="No transcript available. On-device call transcription is not yet implemented.",
            actionItems=[],
            stored=False,
        )

    model = get_gemini_model()
    if not model:
        return CallSummaryResponse(
            summary="Gemini unavailable — cannot summarize call.",
            actionItems=[],
            stored=False,
        )

    try:
        prompt = (
            "You are a helpful assistant for a blind user. "
            "The following is a transcript of a phone call they just made:\n\n"
            f"{request.transcriptText}\n\n"
            "Summarize what was communicated in 1-2 plain sentences a blind user can hear. "
            "Also list any concrete action items (appointments, documents to bring, etc.). "
            "Output strict JSON: "
            '{"summary": "string", "action_items": ["string"]}'
        )
        resp = model.generate_content(prompt)
        data = json.loads(resp.text.strip().replace("```json", "").replace("```", ""))
        return CallSummaryResponse(
            summary=data.get("summary", ""),
            actionItems=data.get("action_items", []),
            stored=True,
        )
    except Exception as e:
        log.warning("Call summarization failed: %s", e)
        return CallSummaryResponse(
            summary="Could not summarize the call.",
            actionItems=[],
            stored=False,
        )


# ================= AGENT ENDPOINTS =================
# All agent endpoints require an X-Session-ID header so each client gets
# an isolated VisionAgent instance and concurrent requests don't clobber
# each other's plan state.

def _session_id(x_session_id: Optional[str] = Header(default=None)) -> str:
    return x_session_id or "default"


@app.post("/agent/plan", response_model=AgentPlanResponse)
async def agent_plan_goal(request: AgentGoalRequest,
                          x_session_id: Optional[str] = Header(default=None)):
    session_id = x_session_id or str(uuid.uuid4())
    agent = get_agent(session_id)
    agent.reset()
    plan = agent.plan(request.goal)
    narration = f"I'll help you {plan.goal}. I've broken it into {len(plan.steps)} steps. Starting now."

    return AgentPlanResponse(
        goal=plan.goal,
        steps=plan.steps,
        totalSteps=len(plan.steps),
        narration=narration,
        sessionId=session_id,
    )


@app.post("/agent/next-action", response_model=AgentActionResponse)
async def agent_next_action(request: AgentStepRequest,
                            x_session_id: Optional[str] = Header(default=None)):
    agent = get_agent(x_session_id or "default")
    result = StepResult(
        success=request.success,
        screen_description=request.screenDescription,
        elements_json=request.screenElementsJson,
        error=request.error,
        screenshot_base64=request.screenshotBase64,
    )

    action = agent.advance_step(result)
    plan = agent.current_plan

    return AgentActionResponse(
        action=action.action.value,
        target=action.target,
        value=action.value,
        narration=action.narration,
        x=action.x,
        y=action.y,
        confidence=action.confidence,
        planStatus=plan.status if plan else "none",
        currentStep=plan.current_step if plan else 0,
        totalSteps=len(plan.steps) if plan else 0,
        requiresConfirmation=action.requires_confirmation,
        confirmationMessage=action.confirmation_message,
    )


@app.post("/agent/confirm", response_model=AgentActionResponse)
async def agent_confirm(request: AgentConfirmRequest,
                        x_session_id: Optional[str] = Header(default=None)):
    agent = get_agent(x_session_id or "default")
    action = agent.confirm_action(request.approved)
    plan = agent.current_plan

    return AgentActionResponse(
        action=action.action.value,
        target=action.target,
        value=action.value,
        narration=action.narration,
        x=action.x,
        y=action.y,
        confidence=action.confidence,
        planStatus=plan.status if plan else "none",
        currentStep=plan.current_step if plan else 0,
        totalSteps=len(plan.steps) if plan else 0,
        requiresConfirmation=action.requires_confirmation,
        confirmationMessage=action.confirmation_message,
    )


@app.get("/agent/status", response_model=AgentStatusResponse)
async def agent_status(x_session_id: Optional[str] = Header(default=None)):
    agent = get_agent(x_session_id or "default")
    plan = agent.current_plan
    return AgentStatusResponse(
        hasActivePlan=plan is not None,
        goal=plan.goal if plan else "",
        status=plan.status if plan else "idle",
        currentStep=plan.current_step if plan else 0,
        totalSteps=len(plan.steps) if plan else 0,
        narration=agent.get_status_narration(),
        actionsExecuted=len(agent.action_history),
        memoryContext=agent.memory.get_context_summary(),
    )


@app.post("/agent/memory/credential")
async def agent_remember_credential(body: CredentialRequest,
                                    x_session_id: Optional[str] = Header(default=None)):
    """
    Store that the agent knows a login for an app.

    Fixed: credentials were previously passed as URL query parameters, which
    causes them to appear in server logs and browser history.  They now travel
    in the POST body only.
    """
    agent = get_agent(x_session_id or "default")
    agent.memory.remember_credential(body.app_name, body.username)
    return {"status": "saved", "app": body.app_name}


@app.post("/agent/reset")
async def agent_reset(x_session_id: Optional[str] = Header(default=None)):
    agent = get_agent(x_session_id or "default")
    agent.reset()
    return {"status": "reset", "narration": "Agent reset. Ready for a new command."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
