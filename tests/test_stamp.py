import json

import cv2
import numpy as np
import trimesh
from fastapi.testclient import TestClient
from shapely.geometry import Point, Polygon

from cuttersnap.api import app
from cuttersnap.cutter import CutterParams, build_cutter
from cuttersnap.outline import mask_to_outline
from cuttersnap.stamp import build_stamp, detail_lines, from_rings, rings


def _photo_with_mark():
    """Round tan cookie with a dark ring on its left side and the edge of icing."""
    img = np.full((600, 600, 3), 230, np.uint8)
    cookie = np.zeros(img.shape[:2], np.uint8)
    cv2.circle(cookie, (300, 300), 240, 255, -1)
    img[cookie > 0] = (90, 160, 205)
    cv2.circle(img, (200, 300), 50, (40, 40, 40), 8)  # left of centre in the photo
    return img, cookie


def test_stamp_finds_the_icing_line_and_mirrors_it():
    img, cookie = _photo_with_mark()
    outline = mask_to_outline(cookie, 80)
    lines = detail_lines(img, outline)
    assert len(lines.geoms) >= 1
    # the mark is left of centre in the photo, so in mm too
    cx = (outline.polygon.bounds[0] + outline.polygon.bounds[2]) / 2
    assert lines.centroid.x < cx - 5
    # nothing traced along the cookie's own edge
    assert lines.intersection(outline.polygon.exterior.buffer(1.5)).area < 1.0

    mesh = build_stamp(outline.polygon, lines)
    assert mesh.is_watertight
    assert mesh.extents[2] == np.float64(6.0) or abs(mesh.extents[2] - 6.0) < 0.05
    # the stamp is printed face up and turned over to use, so the raised
    # ring sits right of centre on the printed part
    top = mesh.vertices[mesh.vertices[:, 2] > 5]
    assert top[:, 0].mean() > (mesh.bounds[0][0] + mesh.bounds[1][0]) / 2 + 5


def test_rings_round_trip():
    img, cookie = _photo_with_mark()
    lines = detail_lines(img, mask_to_outline(cookie, 80))
    again = from_rings(json.loads(json.dumps(rings(lines))))
    assert abs(again.area - lines.area) < 0.5


def test_cutter_is_mirrored_for_blade_down_use():
    # right triangle with its tall, square side on the left
    outline = Polygon([(0, 0), (60, 0), (0, 40)])
    mesh = build_cutter(outline, CutterParams())
    top = mesh.vertices[mesh.vertices[:, 2] > 17.9]
    # turned over in use, so it is printed with the tall side on the right
    assert top[np.argmax(top[:, 1]), 0] > top[:, 0].mean()


def test_stamp_endpoints():
    img, cookie = _photo_with_mark()
    client = TestClient(app)
    png = cv2.imencode(".png", img)[1].tobytes()
    tr = client.post("/api/trace", files={"image": ("c.png", png, "image/png")}, data={"size_mm": "80"}).json()
    res = client.post("/api/stamp-lines", files={"image": ("c.png", png, "image/png")},
                      data={"outline_mm": json.dumps(tr["outline_mm"]), "frame": json.dumps(tr["frame"])})
    assert res.status_code == 200, res.text
    lines = res.json()
    assert lines["lines_mm"] and len(lines["lines_px"]) == len(lines["lines_mm"])
    # the pixel copy lands on the dark ring in the photo
    ring = np.array(lines["lines_px"][0][0])
    assert abs(ring[:, 0].mean() - 200) < 15 and abs(ring[:, 1].mean() - 300) < 15
    res = client.post("/api/stamp", json={"outline_mm": tr["outline_mm"], "lines_mm": lines["lines_mm"]})
    assert res.status_code == 200, res.text
    assert trimesh.load(trimesh.util.wrap_as_stream(res.content), file_type="stl").is_watertight
    res = client.post("/api/stamp", json={"outline_mm": tr["outline_mm"], "lines_mm": []})
    assert res.status_code == 400


def test_stamp_needs_lines():
    import pytest

    with pytest.raises(ValueError):
        build_stamp(Point(0, 0).buffer(30), from_rings([]))
