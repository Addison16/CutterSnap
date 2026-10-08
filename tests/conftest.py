import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient


def star_points(cx, cy, r_out, r_in, n=5):
    a = np.linspace(0, 2 * np.pi, 2 * n, endpoint=False) - np.pi / 2
    r = np.where(np.arange(2 * n) % 2 == 0, r_out, r_in)
    return np.c_[cx + r * np.cos(a), cy + r * np.sin(a)].astype(np.int32)


@pytest.fixture
def star_photo():
    """Tan star cookie with white icing and sprinkles on a light, noisy table."""
    rng = np.random.default_rng(0)
    img = np.full((600, 800, 3), (225, 230, 232), np.uint8)
    img = cv2.add(img, rng.integers(0, 12, img.shape, dtype=np.uint8))
    truth = np.zeros(img.shape[:2], np.uint8)
    star = star_points(400, 310, 230, 110)
    cv2.fillPoly(truth, [star], 255)
    img[truth > 0] = (90, 160, 205)  # BGR biscuit colour
    icing = np.zeros_like(truth)
    cv2.fillPoly(icing, [star_points(400, 310, 180, 85)], 255)
    img[icing > 0] = (245, 245, 245)
    for x, y in rng.integers(300, 420, (25, 2)):
        cv2.circle(img, (int(x), int(y)), 6, (60, 60, 220), -1)
    return img, truth


@pytest.fixture
def white_on_white():
    """White iced heart-ish cookie with a thin biscuit rim on a white board."""
    img = np.full((500, 500, 3), 236, np.uint8)
    truth = np.zeros(img.shape[:2], np.uint8)
    cv2.circle(truth, (190, 210), 110, 255, -1)
    cv2.circle(truth, (310, 210), 110, 255, -1)
    cv2.fillPoly(truth, [np.array([[90, 250], [410, 250], [250, 450]], np.int32)], 255)
    img[truth > 0] = (150, 190, 215)
    inner = cv2.erode(truth, np.ones((13, 13), np.uint8))
    img[inner > 0] = (248, 248, 248)
    return img, truth


def iou(a, b):
    a, b = a > 127, b > 127
    return (a & b).sum() / (a | b).sum()


@pytest.fixture
def anon(tmp_path, monkeypatch):
    """The app with its own empty data folder, nobody signed in."""
    from cuttersnap import users
    from cuttersnap.api import app

    monkeypatch.setenv("CUTTERSNAP_DATA", str(tmp_path))
    monkeypatch.setattr(users, "_failures", {})
    return TestClient(app)


@pytest.fixture
def client(anon):
    """Signed in as the first account (the admin)."""
    res = anon.post("/api/signup", json={"username": "baker", "password": "sugar-cookies"})
    assert res.status_code == 200, res.text
    return anon
