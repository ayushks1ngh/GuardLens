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

The Phase A `CaptureWorker` consumes an auto-discovered `CameraSource` registry rather
than opening transports directly:

```text
CameraSource.open/read/close/status
  ├─ OpenCvSource: local index, file, RTSP, HTTP/MJPEG (implemented)
  └─ WebRtcSource: frames pushed by a paired browser/phone/laptop (Phase B)
```

A camera stores backward-compatible `source`, registry key `source_type`, and flexible
JSON `source_config`. An additive SQLite migration preserves existing rows. The
analysis pipeline still consumes the same latest BGR frame and remains unchanged.

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

### Improvement Phase A — Source abstraction and cleanup (implemented; cleanup choice pending)

- [x] Add safe additive camera migration (`source_type`, JSON `source_config`).
- [x] Add auto-discovered `CameraSource` registry and OpenCV adapter.
- [x] Keep legacy `{name, source}` requests and worker calls compatible.
- [x] Add source schema/device/probe APIs and probe-first dashboard wizard.
- [x] Add resolution, frame-age, source-type, and error status.
- [x] Verify sample file and real local HTTP/MJPEG transport through the same adapter.
- [x] Verify a physical host webcam: Windows `USB2.0 HD UVC WebCam` attached to WSL2,
  passed one-frame probe and sustained dual-source worker/API/MJPEG checks at 640×480.
  The adapter now negotiates MJPEG by default because YUYV times out over WSL USB/IP.
- [ ] Archive/fix the old local DB containing 17 duplicate sample cameras (requires user approval).

**Gate A:** automated adapter/migration/API/wizard tests pass and existing tests remain
green. Physical host-webcam verification is complete; final closure requires an approved
duplicate-camera cleanup. RTSP uses the same FFmpeg-backed network adapter as verified
HTTP/MJPEG, but a real RTSP device should also be checked when available.

### Improvement Phase B — Phone/laptop browser cameras (implemented; physical gate pending)

- [x] Optional HTTPS launch configuration, WebRTC signaling, publisher page, inline QR/link.
- [x] Front/back device selection via browser camera chooser and quality controls.
- [x] Hashed expiring single-use pairing, rotating reload credential, revoke workflow.
- [x] Bounded frame hub and non-queuing shared detector inference across sources.
- [x] Synthetic aiortc offer/answer and three-publisher isolation/soak tests.
- [ ] Run the final two-phone/laptop + host-camera physical reconnect/leakage soak.

**Gate B:** implementation and synthetic media/load checks pass. Final acceptance remains
pending until two real browser publishers and one host camera run concurrently and recover
from physical unplug/reload under HTTPS without cross-camera leakage.

### Improvement Phase C — Motion and clip recording (implemented; operator gate pending)

- [x] Per-camera MOG2 motion detector and schema-driven motion rule.
- [x] Independent pre/post-roll recorder with event/motion/continuous modes.
- [x] Bounded clips, segmentation, codec fallback, low-disk errors, quota/retention.
- [x] Atomic partial-file finalization/recovery and reference-aware clip deletion.
- [x] Event clip API and dashboard player; generated-clip playback tests pass.
- [ ] Final operator playback and real low-disk/restart scenario check.

**Gate C:** automated motion, pre/post-roll, cooldown via rule engine, codec failure,
retention, restart recovery, linking, playback, and download checks pass. Final physical
operator check remains.

### Improvement Phase D — Hand-gesture foundation (implemented; enabled-model gate pending)

- [x] Optional MediaPipe Tasks hand-landmark detector with structured hand attributes.
- [x] Auto-discovered vocabulary registry and model-free `basic_gestures` classifier.
- [x] Gesture/help/sequence rules, stability/chatter suppression, overlay attributes.
- [x] Missing MediaPipe/model disables only the hand plugin.
- [ ] Install an intentionally selected MediaPipe version/model and validate recorded/live clips.

**Gate D:** plugin/fallback/structure tests pass. Stability on recorded clips and one live
camera is pending because no licensed MediaPipe landmarker model is bundled or downloaded.

### Improvement Phase E — Bounded ASL vocabulary (adapter implemented; accuracy gate pending)

- [x] Product scope selected: isolated static ASL fingerspelling only.
- [x] Optional ONNX vocabulary adapter, confidence/unknown handling, sequence smoothing.
- [x] Offline JSONL evaluation tool with per-label accuracy and unknown rate.
- [x] UI/API metadata states exact vocabulary/scope; NARUTO remains reference-only.
- [ ] Supply/license a representative model/dataset and evaluate unseen signers.

**Gate E:** infrastructure is complete, but no accuracy claim is made. Final acceptance
requires a licensed model/data split and measured latency/accuracy on unseen people in
real GuardLens conditions; dynamic J/Z and continuous translation remain out of scope.

### Improvement Phase F — Hardening and release (automated gates pass; physical soak pending)

- [x] Signaling bounds/session caps, security headers, optional TLS, revoke/shutdown cleanup.
- [x] Legacy 2.0 migration preservation and abandoned-clip recovery tests.
- [x] Three synthetic publishers, latest-frame isolation, and bounded shared inference.
- [x] Full regression, dependency, frontend syntax, Compose, Docker build validation.
- [ ] Extended physical three-device soak with recording and all selected models enabled.

**Gate F:** automated upgrade/security/recovery/Docker/load gates pass. Release sign-off
still requires the extended real-device/model resource soak and final operator review.

## 5. Decisions applied for implementation

The user authorized autonomous progress using recommended defaults. Applied choices:

1. Existing RTSP/MJPEG support remains available; browser WebRTC is the durable no-app path.
2. LAN-only first. Non-local browser publishing requires configured HTTPS; internet/TURN
   is deferred until deployment authentication and abuse controls are selected.
3. Recording modes are selectable; recording is off by default, with event as configured mode.
4. Defaults: 5-second pre-roll, 10-second post-roll, 2-minute max, 7-day retention,
   configurable 2 GiB quota.
5. Gesture infrastructure ships first; language scope is bounded static ASL fingerspelling.
   No continuous translation or accuracy claim without a licensed evaluated model.
6. NARUTO is architecture reference-only, not a default security feature.

## 6. Documentation rule for every future session

At the start: read `docs/09-session-recovery.md` and this plan. During work, update this
file when a decision changes. At every gate/end of session:

1. Append built behavior, tests, failures/fixes, and commit to `docs/08-build-log.md`.
2. Update `docs/09-session-recovery.md`: exact completed gate, working tree, test count,
   immediate next action, and blockers/decisions.
3. Update API/data/architecture/ADR docs in the same commit as behavior changes.
4. Add every external reference to the reference table with license and exact use.
5. Never leave recovery saying a phase is complete unless its acceptance gate passed.
