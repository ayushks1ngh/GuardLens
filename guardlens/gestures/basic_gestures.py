"""Small model-free vocabulary for infrastructure and help-gesture rules."""
from __future__ import annotations

from guardlens.gestures import GestureVocabulary, register_vocabulary


@register_vocabulary
class BasicGestures(GestureVocabulary):
    key = "basic_gestures"
    label = "Basic hand gestures"
    scope = "open palm, closed fist, pointing; not sign-language translation"

    def classify(self, landmarks):
        if len(landmarks) != 21:
            return "unknown", 0.0
        wrist_y = landmarks[0][1]
        tip_ids = (4, 8, 12, 16, 20)
        pip_ids = (3, 6, 10, 14, 18)
        extended = [landmarks[tip][1] < landmarks[pip][1] for tip, pip in zip(tip_ids, pip_ids)]
        count = sum(extended)
        if count >= 4:
            return "open_palm", 0.8
        if count == 0 and all(landmarks[tip][1] >= wrist_y - 0.25 for tip in tip_ids):
            return "closed_fist", 0.75
        if extended[1] and count <= 2:
            return "pointing", 0.72
        return "unknown", 0.0
