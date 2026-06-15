# Samvit 👁️🌉

> *Samvit (संवित्) — Sanskrit for "Conscious Awareness"*

> **"We don't just navigate the system for blind users — we navigate the world."**

An AI-powered assistive system that helps visually impaired individuals independently find, understand, and physically reach public services — starting with healthcare.

---

## 🧩 The Problem

Visually impaired individuals face **two walls**, not one:

1. They can't independently navigate apps or screens to find nearby healthcare, benefits, or public services
2. Even when someone helps them find it — **they still can't get there alone**

Existing solutions solve neither problem completely. Screen readers tell you *what's on screen* but don't help you *understand* or *act*. Navigation apps help sighted people. Nothing bridges both worlds.

---

## 💡 The Solution

Samvit is a **two-layer assistive system** combining AI software and sensory hardware:

### 🧠 Layer 1 — Software (The Brain)
A Jarvis-like voice AI that understands your phone screen and the web on your behalf.

- Say *"Find me the nearest free clinic"* — it searches, reads, filters, and explains results in plain language
- Guides users through benefits eligibility questions conversationally
- Makes phone calls on command (*"Call the clinic and ask if they take walk-ins"*)
- Reads and interprets any screen content aloud with context, not just raw text

### 👁️ Layer 2 — Hardware (The Game-Changer)
A wearable sensory substitution device inspired by Neil Harbisson's pioneering work in human sensory extension.

- Uses **heatmapping** to translate the visual environment into sensory feedback
- Converts spatial information (obstacles, paths, destinations) into perceivable signals
- Allows the user to **physically navigate** to their destination — independently, without a guide
- Works in real-time alongside the software layer for end-to-end assistance

---

## 🎯 Challenge Alignment

**Brief 4 — Public Service, Direction A: Benefits Navigator**

| Requirement | Samvit |
|---|---|
| Help users interpret rules and reduce confusion | ✅ Voice AI simplifies eligibility criteria in plain language |
| Translate criteria into plain language | ✅ Reads and contextualizes screen content aloud |
| Ask questions to guide users through their situation | ✅ Conversational AI walks users step by step |
| Healthcare as a primary use case | ✅ Core use case of the product |
| Go beyond a directory — help users actually act | ✅ Hardware ensures they can physically reach the service |

---

## 🏗️ Architecture Overview

```
User Voice Input
      │
      ▼
┌─────────────────────┐
│   Voice AI Layer    │  ← Understands intent, reads screen, navigates web
│  (Jarvis Engine)    │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Screen & Web       │  ← Finds clinics, reads eligibility, makes calls
│  Understanding      │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Hardware Layer     │  ← Heatmap-based sensory substitution wearable
│  (Sensory Bridge)   │    guides user to physical destination
└─────────────────────┘
```

---

## 🔬 Inspiration

- **Neil Harbisson** — Pioneer of sensory substitution; the first human officially recognized as a cyborg, who perceives color through sound via his "eyeborg" antenna
- **Sensory Substitution Research** — The science of routing one sense's information through another (e.g., visual data → tactile or auditory feedback)
- **Heatmap Navigation** — Using thermal/spatial density mapping to encode environmental information into perceivable signals

---

## 🚀 MVP Scope

**Phase 1 — Software MVP**
- [ ] Voice-activated screen reader with contextual understanding
- [ ] Healthcare clinic finder with eligibility pre-screening
- [ ] Conversational benefits guidance flow
- [ ] One-tap call routing to clinics/services

**Phase 2 — Hardware Prototype**
- [ ] Wearable sensor unit (prototype)
- [ ] Heatmap generation from camera/depth input
- [ ] Sensory feedback output (vibration/audio)
- [ ] Integration with software navigation layer

**Phase 3 — Integration**
- [ ] End-to-end flow: voice query → find service → navigate there
- [ ] User testing with visually impaired individuals
- [ ] Feedback loop and refinement

---

## 👥 Target Users

- Visually impaired individuals (partial or full vision loss)
- Blind individuals navigating public services independently
- Families assisting visually impaired members remotely
- Community organizations supporting disability access

---

## 🌍 Impact

Every other Benefits Navigator is just an app. Samvit goes further:

- **Finds** the nearest relevant service
- **Explains** eligibility in plain language
- **Calls** on your behalf
- **Gets you there** — physically, independently

This isn't just accessibility software. It's **independence as a service.**

---

## 📄 License

MIT License — Open for contribution and community development.

---

*Built for the Undergraduate Track — AI for Life & Work | Brief 4: Public Service*
