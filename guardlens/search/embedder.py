"""Image/text embedding backends (CLIP family). Swappable: implement ``Embedder`` and register."""
from __future__ import annotations

import logging
import threading
from typing import Protocol, Sequence

import cv2
import numpy as np

logger = logging.getLogger("guardlens.search")


class Embedder(Protocol):
    name: str

    def encode_images(self, frames: Sequence[np.ndarray]) -> np.ndarray: ...
    def encode_text(self, text: str) -> np.ndarray: ...


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-9)).astype(np.float32)


class OpenClipEmbedder:
    """open_clip model run on CPU. Default is ViT-B/32 (MIT licensed weights, ~60 ms per image)."""

    def __init__(self, model: str = "ViT-B-32", pretrained: str = "laion2b_s34b_b79k", threads: int = 2) -> None:
        import open_clip
        import torch
        torch.set_num_threads(threads)
        self._torch = torch
        self.name = f"{model}/{pretrained}"
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(model, pretrained=pretrained)
        self._model.eval()
        self._tokenizer = open_clip.get_tokenizer(model)
        self._lock = threading.Lock()

    def encode_images(self, frames: Sequence[np.ndarray]) -> np.ndarray:
        from PIL import Image
        tensors = [self._preprocess(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))) for f in frames]
        with self._lock, self._torch.no_grad():
            out = self._model.encode_image(self._torch.stack(tensors))
        return _normalize(out.cpu().numpy())

    def encode_text(self, text: str) -> np.ndarray:
        with self._lock, self._torch.no_grad():
            out = self._model.encode_text(self._tokenizer([text]))
        return _normalize(out.cpu().numpy())[0]


def create_embedder(settings: dict) -> Embedder:
    return OpenClipEmbedder(settings.get("model", "ViT-B-32"), settings.get("pretrained", "laion2b_s34b_b79k"))
