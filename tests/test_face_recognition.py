"""Stage 3.5: SFace recognition beats the pixel method; people enrolled the old way are upgraded automatically."""
from __future__ import annotations

import itertools
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from guardlens import models
from guardlens.app import app
from guardlens.detectors import create_detector
from guardlens.detectors._face_runtime import FaceRuntime, face_runtime
from guardlens.detectors.face_detector import YUNET_FILE
from guardlens.events import FaceImage, Person, get_engine

MODELS = Path("data/models")
PHOTO = Path("tests/assets/solvay_conference.jpg")
need = pytest.mark.skipif(not ((MODELS / models.SFACE_FILE).is_file() and (MODELS / YUNET_FILE).is_file() and PHOTO.exists()),
                          reason="run scripts/setup_face_model.py first")


@pytest.fixture
def runtime(tmp_path):
    rt = FaceRuntime()
    with TestClient(app):  # database
        rt.configure(tmp_path / "faces", models_dir=MODELS)
        yield rt


def _altered(img, alpha, beta, dx, dy, blur):
    h, w = img.shape[:2]
    out = cv2.convertScaleAbs(img, alpha=alpha, beta=beta)
    out = cv2.warpAffine(out, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h))
    return cv2.GaussianBlur(out, (blur, blur), 0) if blur > 1 else out


@need
def test_same_face_under_lighting_shift_and_blur_is_recognised_and_strangers_are_not(runtime):
    assert runtime.backend == "sface" and runtime.threshold == 0.5
    im = cv2.imread(str(PHOTO))
    det = create_detector("face", {"backend": "yunet", "model": str(MODELS / YUNET_FILE)})
    base = det._boxes(im)
    assert len(base) == 29
    same = []
    for cond in [(1.35, 25, 4, 3, 3), (0.7, -20, 2, 2, 1), (1.0, 0, -5, 4, 5)]:
        im2 = _altered(im, *cond)
        other = det._boxes(im2)
        for (x, y, w, h, _s, row) in base:
            ctr = np.array([x + w / 2, y + h / 2])
            q = min(other, key=lambda b: np.linalg.norm(np.array([b[0] + b[2] / 2, b[1] + b[3] / 2]) - ctr))
            a, b = runtime.embed_detection(im, row, im[y:y + h, x:x + w]), runtime.embed_detection(im2, q[5], im2)
            same.append(float(a @ b))
    embeddings = [runtime.embed_detection(im, r, im) for (*_x, r) in base]
    strangers = [float(embeddings[i] @ embeddings[j]) for i, j in itertools.combinations(range(len(embeddings)), 2)]
    assert np.mean(np.array(same) >= runtime.threshold) >= 0.95   # measured 98.9%
    assert np.mean(np.array(strangers) >= runtime.threshold) <= 0.01  # measured 0.25% on tiny 1927 faces
    assert embeddings[0].shape == (128,)


@need
def test_enrol_one_person_then_only_that_person_is_named_in_a_changed_picture(runtime, tmp_path, monkeypatch):
    im = cv2.imread(str(PHOTO))
    det = create_detector("face", {"backend": "yunet", "model": str(MODELS / YUNET_FILE)})
    x, y, w, h, _s, _row = det._boxes(im)[7]
    pad = 60
    portrait = im[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]   # the picture a person would upload
    with TestClient(app) as client:
        runtime.configure(tmp_path / "faces", models_dir=MODELS)
        from guardlens.api import faces as faces_api
        import guardlens.detectors.face_detector as fd
        monkeypatch.setattr(faces_api, "face_runtime", runtime)  # undone automatically after the test
        monkeypatch.setattr(fd, "face_runtime", runtime)
        pid = client.post("/api/persons", json={"name": "Dr Seven", "watchlist": False}).json()["id"]
        ok, buf = cv2.imencode(".jpg", portrait)
        up = client.post(f"/api/persons/{pid}/images", files={"image": ("p.jpg", buf.tobytes(), "image/jpeg")})
        assert up.status_code in (200, 201), up.text
        with Session(get_engine()) as session:
            assert len(session.exec(select(FaceImage)).all()) == 1 and len(session.exec(select(FaceImage)).first().embedding) == 128
        found = det.process(_altered(im, 1.3, 20, 3, 2, 3))
        names = [f.attributes["name"] for f in found]
        assert names.count("Dr Seven") == 1 and names.count("unknown") == len(found) - 1


@need
def test_people_enrolled_with_the_old_pixel_method_are_upgraded_automatically(tmp_path):
    faces = tmp_path / "faces"; faces.mkdir()
    im = cv2.imread(str(PHOTO))
    cv2.imwrite(str(faces / "old.jpg"), im[300:480, 150:350])  # a portrait saved by an earlier version
    with TestClient(app):
        with Session(get_engine()) as session:
            person = Person(name="Old enrolment", watchlist=False); session.add(person); session.commit(); session.refresh(person)
            session.add(FaceImage(person_id=person.id, image_path="old.jpg", embedding=[0.1] * 1024)); session.commit()
        rt = FaceRuntime(); rt.configure(faces, models_dir=MODELS)
        with Session(get_engine()) as session:
            assert len(session.exec(select(FaceImage)).first().embedding) == 128  # saved in the new method, once


def test_without_the_models_everything_keeps_working_on_the_pixel_method(tmp_path, caplog):
    rt = FaceRuntime()
    with TestClient(app):
        with caplog.at_level("WARNING", logger="guardlens.faces"):
            rt.configure(tmp_path / "faces", models_dir=tmp_path / "no-models")
    assert rt.backend == "pixels" and rt.threshold == 0.82 and "setup_face_model.py" in caplog.text
    face = np.random.default_rng(1).integers(0, 255, (80, 80, 3), dtype=np.uint8)
    vec = rt.embed_detection(face, None, face)
    assert vec.shape == (1024,) and rt.match(vec)[1] == "unknown"
