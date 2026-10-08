"""Slice real cutters in PrusaSlicer and check the blade prints as whole lines.

Thin cutting edges are the most common complaint about printed cutters: a
blade thinner than two slicer lines can print as one wobbly line, as gap
fill, or not at all. This slices the top of the blade with the classic and
Arachne wall generators at the line widths slicers use by default and checks
every layer of the taper gets two full loops (one on each face).

Skipped when prusa-slicer is not installed; CI installs it.
"""
import math
import os
import shutil
import subprocess
from collections import Counter, defaultdict

import pytest
from shapely.geometry import Point

from cuttersnap.cutter import CutterParams, build_cutter

SLICER = shutil.which("prusa-slicer")
# CI sets CUTTERSNAP_REQUIRE_SLICER so a missing slicer fails instead of skipping
pytestmark = pytest.mark.skipif(not SLICER and not os.environ.get("CUTTERSNAP_REQUIRE_SLICER"),
                                reason="prusa-slicer not installed")
RADIUS = 30.0


def _loops_per_layer(gcode: str) -> dict[float, Counter]:
    """Extruded length per layer and feature type, in multiples of the outline length."""
    z, typ, x, y = 0.0, "", None, None
    layers: dict[float, Counter] = defaultdict(Counter)
    for line in gcode.splitlines():
        if line.startswith(";Z:"):
            z = round(float(line[3:]), 2)
        elif line.startswith(";TYPE:"):
            typ = line[6:].strip()
        elif line.startswith("G1"):
            words = {w[0]: float(w[1:]) for w in line.split(";")[0].split()[1:] if w[0] in "XYE"}
            nx, ny = words.get("X", x), words.get("Y", y)
            if words.get("E", 0) > 0 and x is not None and ("X" in words or "Y" in words):
                layers[z][typ] += math.hypot(nx - x, ny - y) / (2 * math.pi * RADIUS)
            x, y = nx, ny
    return layers


@pytest.mark.parametrize("nozzle,width", [(0.4, 0.42), (0.4, 0.45), (0.4, 0.5), (0.6, 0.62), (0.25, 0.27)])
@pytest.mark.parametrize("generator", ["classic", "arachne"])
def test_blade_slices_as_two_full_lines(tmp_path, nozzle, width, generator):
    params = CutterParams.for_nozzle(nozzle)
    build_cutter(Point(0, 0).buffer(RADIUS, quad_segs=64), params).export(tmp_path / "c.stl")
    gcode = tmp_path / "c.gcode"
    assert SLICER, "prusa-slicer is not installed"
    subprocess.run([SLICER, "--export-gcode", str(tmp_path / "c.stl"), "-o", str(gcode),
                    "--nozzle-diameter", str(nozzle), "--layer-height", "0.2",
                    "--first-layer-height", "0.2", "--perimeter-generator", generator,
                    "--extrusion-width", str(width), "--perimeter-extrusion-width", str(width),
                    "--external-perimeter-extrusion-width", str(width)],
                   check=True, capture_output=True)
    layers = _loops_per_layer(gcode.read_text())
    taper = [z for z in layers if z > params.straight_top]
    assert max(layers) == pytest.approx(params.height, abs=0.01), "blade top went missing"
    for z in taper:
        walls = layers[z]["External perimeter"] + layers[z]["Perimeter"]
        assert walls >= 1.95, f"layer {z}: only {walls:.2f} wall loops"
