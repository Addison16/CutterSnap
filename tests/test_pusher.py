from shapely.affinity import scale
from shapely.geometry import Point, Polygon, box
from shapely.ops import orient, unary_union

from cuttersnap.cutter import CutterParams, PusherParams, build_pusher


def test_pusher_fits_inside_cutter_with_clearance():
    outline = Point(0, 0).buffer(30, quad_segs=64)
    plate, notes = build_pusher(outline)
    assert plate.is_watertight and not notes
    w, _, z = plate.extents
    assert abs(w - (60 - 2 * PusherParams().clearance)) < 0.3
    # the knob sticks out above the cutter when the plate reaches the blade tip
    assert z > CutterParams().height


def test_pusher_follows_dough_spread():
    outline = Point(0, 0).buffer(30, quad_segs=64)
    plain, _ = build_pusher(outline)
    spread, _ = build_pusher(outline, CutterParams(spread=1.0))
    assert abs((plain.extents[0] - spread.extents[0]) - 2.0) < 0.3


def test_pusher_drops_parts_too_narrow_to_print():
    # two blobs joined by a 4 mm neck: shrinking 2 mm all round cuts the neck
    outline = unary_union([Point(0, 0).buffer(20), Point(60, 0).buffer(12), box(15, -2, 50, 2)])
    plate, notes = build_pusher(outline)
    assert plate.is_watertight and notes
    assert plate.extents[0] < 41


def test_pusher_needs_room_for_a_knob():
    import pytest

    with pytest.raises(ValueError):
        build_pusher(Polygon([(0, 0), (80, 0), (80, 6), (0, 6)]))


def test_pusher_endpoint():
    from fastapi.testclient import TestClient

    from cuttersnap.api import app

    outline = list(Point(0, 0).buffer(30, quad_segs=16).exterior.coords)[:-1]
    res = TestClient(app).post("/api/pusher", json={"outline_mm": outline})
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "model/stl"
    assert res.headers["x-cutterSnap-size"].startswith("56.")


def test_knob_flare_stays_on_plate_with_small_clearance():
    # a 40 x 17 mm oval: the knob is limited by the plate's width
    outline = scale(Point(0, 0).buffer(20, 128), 1, 0.425)
    mesh, _ = build_pusher(outline, CutterParams(), PusherParams(clearance=0.5))
    plate = orient(outline, 1.0).buffer(-0.5, join_style=1)
    above = mesh.vertices[mesh.vertices[:, 2] > PusherParams().plate_h - 1e-6]
    assert all(plate.buffer(1e-3).contains(Point(x, y)) for x, y, _ in above)
