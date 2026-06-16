# Samvit — Hardware Spec

## What It Is
A wearable sensory substitution device that converts real-time visual/spatial environment data into non-visual feedback (haptic or audio), enabling independent physical navigation for visually impaired users.

---

## Input
| Source | Data |
|---|---|
| Camera / depth sensor | Real-time environmental feed |
| Software layer | Destination coordinates from voice AI |

## Processing
- Generates spatial heatmap from camera/depth input
- Encodes obstacle positions, paths, and destination direction into feedback signals

## Output
| Feedback Type | Encodes |
|---|---|
| Vibration pattern | Obstacle proximity / direction |
| Audio tone | Path guidance / destination proximity |

---

## Constraints
- Must run in real-time (low latency)
- Wearable form factor — lightweight, body-mounted
- Must integrate with Layer 1 software via a defined interface
- Works outdoors and indoors
- No vision required to operate

---

## Interface with Software Layer
Receives destination coordinates from the Jarvis voice engine → translates into directional feedback for the user in real-time.

---

## Success Criteria
- User can navigate from point A to point B independently without sighted assistance
- Obstacle detection is reliable enough to avoid collisions
- Feedback is learnable within a short training period
- Hardware stays functional during a full transit journey (battery + durability)

## Note
Don't build the software layer, as soon as you complete the hardware input and output just save the files and then you will be called again when the software layer has been built. 

