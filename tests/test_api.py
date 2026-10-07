import json

import cv2
from fastapi.testclient import TestClient

from cuttersnap.api import app

client = TestClient(app)


def test_health_and_page():
    assert client.get("/api/health").json()["ok"]
    assert "CutterSnap" in client.get("/").text


def test_trace_then_cutter(star_photo):
    img, _ = star_photo
    ok, png = cv2.imencode(".png", img)
    res = client.post("/api/trace", files={"image": ("star.png", png.tobytes(), "image/png")},
                      data={"rect": json.dumps([130, 50, 540, 520]), "size_mm": "80"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert max(body["width_mm"], body["height_mm"]) <= 80.5
    assert len(body["outline_px"]) == len(body["outline_mm"])
    res = client.post("/api/cutter", json={"outline_mm": body["outline_mm"]})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "model/stl"
    assert len(res.content) > 10_000


def test_bad_image_rejected():
    res = client.post("/api/trace", files={"image": ("x.png", b"not an image", "image/png")})
    assert res.status_code == 400
