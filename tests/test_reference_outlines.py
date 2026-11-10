"""Outlines drawn outside CutterSnap must still give a clean, sturdy cutter.

A traced outline is already rounded, but a project file (or an outline sent
to /api/cutter) can come from anywhere. These six reference outlines have
needle points and hairline slits; the cutter must round them, not copy them.
"""
from pathlib import Path

import pytest
from shapely.geometry import Point

from cuttersnap.cutter import build_cutter, cutting_face, needs_rounding
from cuttersnap.outline import check_outline
from cuttersnap.project import Project

DATA = Path(__file__).parent / "data" / "reference_outlines"
NAMES = sorted(p.stem for p in DATA.glob("*.json"))


def test_all_six_are_here():
    assert len(NAMES) == 6


@pytest.mark.parametrize("name", NAMES)
def test_reference_outline_builds_a_clean_cutter(name):
    proj = Project.load(DATA / f"{name}.json")
    poly = proj.polygon()
    assert needs_rounding(poly)  # the raw drawing breaks the corner rules
    face = cutting_face(poly)
    assert check_outline(face)["ok"]
    # rounding fills slits and blunts needles but keeps the shape
    assert face.area == pytest.approx(poly.area, rel=0.03)
    # every point of the new blade stays within 2 mm of the drawing (a needle-sharp
    # notch filled to a 2.5 mm radius moves about 1.5 mm; filled slits
    # sit across the slit mouth, so the other direction can be far)
    assert max(poly.exterior.distance(Point(c)) for c in face.exterior.coords) < 2.0
    notes: list[str] = []
    mesh = build_cutter(poly, proj.params(), notes)
    assert mesh.is_watertight and mesh.is_volume
    assert any("rounded" in n for n in notes)


def test_traced_outline_is_left_alone():
    poly = Point(40, 40).buffer(35, 64)
    assert not needs_rounding(poly)
    assert cutting_face(poly).equals(poly)


def test_thin_drawing_is_rounded_after_the_halo():
    from shapely.geometry import box

    thin = box(0, 0, 80, 2).segmentize(0.5)  # too thin to round on its own
    face = cutting_face(thin, halo=5.0)
    assert check_outline(face)["ok"] and face.bounds[2] - face.bounds[0] > 85
