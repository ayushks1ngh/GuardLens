"""Optional bounded ASL static-fingerspelling classifier adapter.

This adapter intentionally does not ship an unverified model or claim continuous ASL.
Operators provide a licensed ONNX classifier and labels for static handshapes only.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from guardlens.gestures import GestureVocabulary, normalized_features, register_vocabulary


@register_vocabulary
class AslStaticVocabulary(GestureVocabulary):
    key = "asl_static"
    label = "ASL static fingerspelling (optional model)"
    scope = "isolated static ASL handshapes; excludes dynamic J/Z and sentence translation"

    def setup(self, config):
        self._threshold = float(config.get("confidence", 0.75))
        model = Path(str(config.get("model", "")))
        labels = Path(str(config.get("labels", "")))
        self._net = None; self._labels = []
        if model.is_file() and labels.is_file():
            self._net = cv2.dnn.readNetFromONNX(str(model))
            self._labels = json.loads(labels.read_text(encoding="utf-8"))

    @property
    def available(self) -> bool:
        return self._net is not None and bool(self._labels)

    def classify(self, landmarks):
        if not self.available:
            return "unknown", 0.0
        features = normalized_features(landmarks).astype(np.float32)[None, :]
        self._net.setInput(features)
        scores = np.asarray(self._net.forward()).reshape(-1)
        index = int(np.argmax(scores)); confidence = float(scores[index])
        if index >= len(self._labels) or confidence < self._threshold:
            return "unknown", confidence
        return str(self._labels[index]), confidence
