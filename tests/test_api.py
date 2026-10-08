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


def _png(img):
    return cv2.imencode(".png", img)[1].tobytes()


def test_box_outside_photo_and_bad_box_rejected(star_photo):
    img, _ = star_photo
    for rect in ("[5000, 5000, 100, 100]", "not json", "[1, 2]", "{}"):
        res = client.post("/api/trace", files={"image": ("s.png", _png(img), "image/png")},
                          data={"rect": rect})
        assert res.status_code == 400, (rect, res.text)


def test_cookie_click_outside_box_still_traces(star_photo):
    img, _ = star_photo
    res = client.post("/api/trace", files={"image": ("s.png", _png(img), "image/png")},
                      data={"rect": json.dumps([130, 50, 540, 520]), "fg": "[[790, 590], [400, 310]]"})
    assert res.status_code == 200, res.text


def test_oversized_upload_refused(monkeypatch, star_photo):
    import cuttersnap.api as api

    monkeypatch.setattr(api, "MAX_UPLOAD", 1000)
    img, _ = star_photo
    res = client.post("/api/trace", files={"image": ("s.png", _png(img), "image/png")})
    assert res.status_code == 413


def test_huge_dimensions_refused(monkeypatch, star_photo):
    import cuttersnap.api as api

    monkeypatch.setattr(api, "MAX_PIXELS", 1000)
    img, _ = star_photo
    res = client.post("/api/trace", files={"image": ("s.png", _png(img), "image/png")})
    assert res.status_code == 413


def test_trace_with_edge_points(star_photo):
    from conftest import star_points

    img, _ = star_photo
    pts = star_points(400, 310, 230, 110).tolist()
    res = client.post("/api/trace", files={"image": ("s.png", _png(img), "image/png")},
                      data={"edge": json.dumps(pts), "size_mm": "80"})
    assert res.status_code == 200, res.text
    res = client.post("/api/trace", files={"image": ("s.png", _png(img), "image/png")},
                      data={"edge": json.dumps(pts[:2])})
    assert res.status_code == 400


def test_check_measures_the_cutting_face_after_spread():
    from shapely.geometry import box

    sq = list(box(0, 0, 40, 40).buffer(2, join_style=1).exterior.coords)[:-1]
    c0 = client.post("/api/check", json={"outline_mm": sq}).json()
    c1 = client.post("/api/check", json={"outline_mm": sq, "spread": 1.0}).json()
    assert c0["ok"] and c1["ok"]
    assert c1["min_convex_radius_mm"] >= 1.5 * 0.9
