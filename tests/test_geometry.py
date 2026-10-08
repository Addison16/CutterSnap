import numpy as np
import pytest
from shapely.geometry import Point, Polygon

from conftest import star_points
from cuttersnap.cutter import CutterParams, build_cutter
from cuttersnap.outline import OutlineError, check_outline, mask_to_outline
import cv2


def star_mask():
    m = np.zeros((800, 800), np.uint8)
    cv2.fillPoly(m, [star_points(400, 400, 380, 150)], 255)
    return m


def test_outline_is_smooth_and_sized():
    o = mask_to_outline(star_mask(), 90)
    minx, miny, maxx, maxy = o.polygon.bounds
    assert max(maxx - minx, maxy - miny) == pytest.approx(90, abs=4)  # points get rounded
    assert check_outline(o.polygon)["ok"]
    spacing = np.linalg.norm(np.diff(np.array(o.polygon.exterior.coords), axis=0), axis=1)
    assert spacing.max() < 1.0


def test_minimum_radii_enforced():
    o = mask_to_outline(star_mask(), 90, min_convex_r=1.5, min_concave_r=2.5).polygon
    # a shape already obeying the radii survives opening and closing unchanged
    opened = o.buffer(-1.4).buffer(1.4)
    closed = o.buffer(2.4).buffer(-2.4)
    assert opened.symmetric_difference(o).area / o.area < 0.01
    assert closed.symmetric_difference(o).area / o.area < 0.01


def test_tiny_shape_rejected():
    m = np.zeros((200, 200), np.uint8)
    with pytest.raises(OutlineError):
        mask_to_outline(m, 90)


def test_cutter_watertight_and_dimensions():
    outline = Point(0, 0).buffer(40, 256)
    p = CutterParams()
    mesh = build_cutter(Polygon(outline.exterior.coords), p)
    assert mesh.is_watertight and mesh.volume > 0
    assert mesh.bounds[1][2] == pytest.approx(p.height)
    # cookie side of the blade sits on the outline: nothing inside radius 40
    r = np.linalg.norm(mesh.vertices[:, :2], axis=1)
    assert r.min() == pytest.approx(40, abs=0.05)
    # base reaches out to wall + flange width
    assert r.max() == pytest.approx(40 + p.wall_base + p.flange_w, abs=0.2)
    # cutting edge: vertices at the top span exactly the tip thickness
    top = r[np.isclose(mesh.vertices[:, 2], p.height)]
    assert top.max() - top.min() == pytest.approx(p.wall_tip, abs=0.05)


def test_cutter_from_star_is_one_watertight_piece():
    o = mask_to_outline(star_mask(), 100).polygon
    mesh = build_cutter(o)
    assert mesh.is_watertight
    assert len(mesh.split(only_watertight=False)) == 1


def test_nozzle_sizing():
    p = CutterParams.for_nozzle(0.6)
    assert (p.wall_base, p.wall_tip) == (2.4, 1.2)
    thin = CutterParams.for_nozzle(0.4, wall_tip=0.6)
    assert thin.warnings(0.4)  # under two lines: tell the user about thin-wall mode
    with pytest.raises(ValueError):
        CutterParams(wall_tip=2.0, wall_base=1.0).validate()


def test_outline_maps_back_onto_photo():
    m = star_mask()
    o = mask_to_outline(m, 90)
    px = o.to_pixels()
    # every overlay point lies within a few pixels of the traced mask edge
    edge = cv2.Canny(m, 50, 150)
    dist = cv2.distanceTransform(255 - edge, cv2.DIST_L2, 3)
    d = dist[px[:, 1].round().astype(int).clip(0, 799), px[:, 0].round().astype(int).clip(0, 799)]
    assert np.median(d) < 3


def test_outline_passes_curvature_check_after_smoothing():
    report = check_outline(mask_to_outline(star_mask(), 90).polygon)
    assert report["ok"], report


def test_tight_notch_does_not_fold_the_blade():
    # a slot just wider than the 2.5 mm notch rule, deeper than the blade is thick
    body = Point(0, 0).buffer(30, 64)
    slot = Polygon([(-1.3, 0), (1.3, 0), (1.3, 40), (-1.3, 40)]).buffer(1.3, 16)
    outline = body.difference(slot)
    mesh = build_cutter(outline)
    assert mesh.is_watertight and mesh.volume > 0


def test_dough_spread_shrinks_cutting_face():
    outline = Polygon(Point(0, 0).buffer(40, 256).exterior.coords)
    mesh = build_cutter(outline, CutterParams(spread=1.0))
    r = np.linalg.norm(mesh.vertices[:, :2], axis=1)
    assert r.min() == pytest.approx(39, abs=0.05)


@pytest.mark.parametrize("size", [50, 75, 90, 100])
def test_radius_minimums_met_at_every_preset_size(star_photo, size):
    from cuttersnap.outline import check_outline, mask_to_outline

    _, truth = star_photo
    c = check_outline(mask_to_outline(truth, size).polygon)
    assert c["min_convex_radius_mm"] >= 1.5 and c["min_concave_radius_mm"] >= 2.5, c
