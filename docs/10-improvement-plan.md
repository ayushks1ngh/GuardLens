# 10 — Post-2.0 Improvement Plan

**Status:** Research complete; planning only. No implementation starts until the
acceptance gates and product choices below are approved.

**Current baseline:** GuardLens 2.0 phases 0–8 are complete; 47 tests pass. This plan
extends that baseline without replacing the stable Detection → Rule → Event pipeline.

---

## 1. Goals

1. Add cameras from the current computer, phones, laptops, IP cameras, RTSP streams,
   HTTP/MJPEG streams, and video files through one guided Add Camera flow.
2. Let several phones/laptops act as cameras concurrently, with reconnect/status,
   existing YOLO/face/rule analysis, evidence, activity, and reports applied uniformly.
3. Add continuous and motion/event-triggered clip recording with retention controls.
4. Add hand/gesture recognition as an optional detector family, then implement an
   explicitly chosen real sign-language vocabulary and temporal recognition model.
5. Preserve the flexibility invariant: transport, detectors, rules, recorders, and
   gesture vocabularies remain replaceable/config-driven plugins.

## 2. Research conclusions

### CCTV motion repository

[`dognehari12-commits/-CCTV-Style-Motion-Detection-using-OpenCV`](https://github.com/dognehari12-commits/-CCTV-Style-Motion-Detection-using-OpenCV)
shows a useful MOG2 pipeline: background subtraction, thresholding, morphology,
contour-area filtering, and recording until a no-motion grace period expires.

**Use in GuardLens:** reimplement the pattern as a `MotionDetector`/`MotionRule` plus a
separate `ClipRecorder`; do not copy its single-process webcam/display loop. It does not
solve mobile/laptop networking or multi-camera ingest. Its README claims MIT, but no
root `LICENSE` file was found during research, so code copying is blocked until the
license is verified. The algorithmic pattern itself is standard OpenCV usage.

### MediaPipe gesture repository

[`kinivi/hand-gesture-recognition-mediapipe`](https://github.com/kinivi/hand-gesture-recognition-mediapipe)
(Apache-2.0) uses MediaPipe Hands landmarks, normalized keypoints, a small TFLite MLP
for static poses, and a 16-frame point-history classifier for motion gestures. Its
built-in labels are basic gestures (open/closed/pointing and motion), **not a complete
sign language**.

**Use in GuardLens:** strongest reference for a detector plugin that emits hand boxes,
21 landmarks, handedness, static gesture, dynamic gesture, and confidence. Model
training/data collection must be separate from the always-on monitoring runtime.

### NARUTO hand-sign repository

[`Kazuhito00/NARUTO-HandSignDetection`](https://github.com/Kazuhito00/NARUTO-HandSignDetection)
(MIT) uses a YOLOX-Nano ONNX detector for 14 fictional NARUTO signs. Its sequence demo
adds sign history, interval reset, and repeated-detection/chattering suppression.

**Use in GuardLens:** useful reference for an ONNX hand-sign detector plugin and a
sequence rule. It is **not sign-language recognition** and must be exposed only as an
optional NARUTO/demo vocabulary, never labeled as accessibility translation.

## 3. Proposed architecture

### 3.1 Camera source adapters

The current `CaptureWorker` assumes every source can be pulled through
`cv2.VideoCapture`. Keep that adapter, but add a `CameraSource` registry:

```text
CameraSource.open/read/close/status
  ├─ OpenCvSource: local index, file, RTSP, HTTP/MJPEG
  └─ WebRtcSource: frames pushed by a paired browser/phone/laptop
```

A camera stores `source_type` and flexible JSON `source_config`. Add migration support
before changing the camera table. The analysis pipeline continues consuming latest BGR
frames and therefore remains unchanged.

### 3.2 Guided Add Camera experience

The Add Camera UI becomes a source-type wizard:

- **This device camera:** enumerate browser cameras with `getUserMedia`; either publish
  through WebRTC or, for the GuardLens host only, select a local OpenCV device.
- **Phone/laptop as camera:** create a short-lived pairing session and QR/link; opening
  the publisher page requests camera permission, selects front/back camera and quality,
  and publishes WebRTC video to GuardLens.
- **IP/RTSP/HTTP camera:** URL + optional credentials stored via secret references,
  validation preview, connection timeout, and actionable errors.
- **Video file/sample:** file path for testing and demonstrations.

Browser camera access requires user permission and a secure context (HTTPS), except
localhost. WebRTC transport is encrypted; signaling/pairing, authorization, expiry,
reconnect, and device revocation are GuardLens responsibilities.

### 3.3 Multi-device operation

- One source adapter and latest-frame buffer per camera.
- One shared model per detector; bounded analysis scheduling rather than one CPU-heavy
  inference loop per device.
- Per-camera capture FPS, analysis FPS, resolution, status, last-frame age, and errors.
- Pairing tokens expire, are single-use, and are stored hashed; publishers can be
  revoked. No camera is silently accessible without permission.
- LAN first. Internet/NAT operation is deferred until authentication, HTTPS, and a TURN
  strategy are intentionally designed.

### 3.4 Recording and motion

Recording is a separate service so detector/rule plugins never write video directly:

```text
latest frames → pre-roll ring buffer → ClipRecorder → event.clip_path
                     ▲                   modes: off / motion / event / continuous
MotionDetector/Rule ─┘                   post-roll + quota/retention
```

- Motion: MOG2 + configurable contour area, learning rate, shadows, morphology,
  warm-up, zones, and no-motion post-roll.
- Clips: raw camera frames by default; optional overlay export later.
- Container/codec: prefer MP4/H.264 when available, with a tested fallback.
- Include pre-event seconds so the cause is visible, post-event grace, maximum clip
  length, disk quota, retention days, and explicit recording state in the UI.
- Continuous recording is segmented (for example 5-minute files), never one unbounded
  file. Events reference clips rather than duplicating them.

### 3.5 Hand gestures and sign language

Add an optional `HandGestureDetector` plugin with structured attributes; do not mix it
into the object detector:

```text
Detection(class_name="hand", attributes={
  landmarks, handedness, static_gesture, dynamic_gesture, vocabulary, confidence
})
```

Then add rules such as `GestureDetectedRule`, `HelpGestureRule`, and
`GestureSequenceRule`. Keep every vocabulary/model separately selectable:

- `basic_gestures` — initial MediaPipe/TFLite proof of integration.
- `naruto_14` — optional demo/entertainment ONNX plugin, if desired.
- A real sign language (ASL, ISL, etc.) — separate dataset/model and acceptance plan.

A real sign-language feature requires choosing the language and scope. Static alphabet
classification is not sentence translation; dynamic signs, two hands, face/body cues,
continuous segmentation, grammar, and signer diversity require temporal multimodal
models and representative data. Product wording must match actual capability.

## 4. Delivery order and acceptance gates

### Improvement Phase A — Source abstraction and cleanup

- Archive/fix the old local DB containing 17 duplicate sample cameras.
- Add migrations and `CameraSource` registry; keep OpenCV adapter behavior unchanged.
- Add source metadata/status and deterministic adapter tests.

**Gate A:** local webcam, sample file, and RTSP/MJPEG test source all pass through the
same adapter contract; existing 47 tests remain green.

### Improvement Phase B — Phone/laptop browser cameras

- HTTPS development setup, WebRTC signaling, publisher page, pairing QR/link,
  front/back camera selection, quality controls, revoke/reconnect workflow.
- Bounded shared analysis scheduler for multiple sources.

**Gate B:** two phones/laptops and one host camera connect concurrently; unplug/reload
recovers; each receives correct overlays/events without cross-camera frame leakage.

### Improvement Phase C — Motion and clip recording

- Motion detector/rule, pre/post-roll recorder, recording modes, event clip API/player,
  retention/quota, disk-full and codec failure handling.

**Gate C:** motion starts one bounded clip with pre/post-roll; cooldown avoids clip
floods; no-motion stops recording; event clip plays/downloads; restart/low-disk tests
leave no corrupt active writer.

### Improvement Phase D — Hand-gesture foundation

- MediaPipe hand-landmark backend and lightweight classifier adapter.
- Structured overlays, per-camera enable/FPS, model/vocabulary registry, dataset tooling
  outside the runtime service.

**Gate D:** basic gestures are stable on recorded test clips and one live camera;
missing MediaPipe/model disables only this plugin, never GuardLens.

### Improvement Phase E — Chosen sign vocabulary

- Product decision: target language (for example ISL vs ASL), alphabet/isolated signs
  vs continuous phrases, one/two hands, expected signer/camera conditions.
- Build/license a representative dataset, temporal smoothing/sequence recognition,
  confidence/unknown handling, evaluation split, and privacy documentation.

**Gate E:** agreed vocabulary meets measured accuracy/latency on unseen people and real
GuardLens camera conditions. UI labels the exact supported scope—never “full sign
language” unless continuous translation is genuinely validated.

### Improvement Phase F — Hardening and release

- End-to-end multi-device soak/load tests, HTTPS/auth review, bandwidth/CPU profiles,
  recording retention recovery, docs, Docker, and upgrade/migration test.

**Gate F:** clean upgrade from 2.0 data, three concurrent publishers, recording and all
enabled detectors run within agreed resource limits for an extended soak period.

## 5. Decisions required before implementation

1. **First phone path:** quick IP-camera-app URL support first, or browser-only WebRTC?
   Recommendation: support existing RTSP/MJPEG immediately through the adapter wizard,
   then build browser WebRTC pairing as the durable no-app experience.
2. **Network scope:** LAN only first (recommended) or internet access? Internet support
   requires stronger auth, TLS, TURN, abuse controls, and deployment decisions.
3. **Recording mode/defaults:** motion clips only, event clips, continuous segments, or
   all selectable? Recommendation: selectable; default event/motion, continuous off.
4. **Retention:** proposed defaults: 5-second pre-roll, 10-second post-roll, 2-minute
   max clip, 7-day retention, configurable disk quota.
5. **Sign language:** which language and scope? Recommendation: ship basic gestures as
   infrastructure first; choose ISL/ASL and a bounded vocabulary before claiming sign
   recognition.
6. **NARUTO model:** include as an optional demo plugin or use only as architecture
   reference? Recommendation: reference/optional extra, not a default security feature.

## 6. Documentation rule for every future session

At the start: read `docs/09-session-recovery.md` and this plan. During work, update this
file when a decision changes. At every gate/end of session:

1. Append built behavior, tests, failures/fixes, and commit to `docs/08-build-log.md`.
2. Update `docs/09-session-recovery.md`: exact completed gate, working tree, test count,
   immediate next action, and blockers/decisions.
3. Update API/data/architecture/ADR docs in the same commit as behavior changes.
4. Add every external reference to the reference table with license and exact use.
5. Never leave recovery saying a phase is complete unless its acceptance gate passed.
