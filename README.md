# CutterSnap

Turn a photo of a cookie into a sturdy, smooth, 3D-printable cookie cutter.
Self-hosted in Docker. Classical computer vision only: no AI models, no cloud calls.

## Run it

```sh
docker compose up -d --build
```

Then open http://localhost:8080.

1. Choose a photo. Phone screenshots of cookie trays work too.
2. Draw a box around the cookie you want. On busy or low-contrast photos, add a
   **Cookie click** on it and a **Not cookie click** on anything it grabs by mistake.
3. Pick the size (or a Mini 5 cm, Standard 7.5 cm or Large 10 cm preset) and your
   nozzle, then **Trace outline** and **Make cutter**. The size is the cookie's longest
   side, measured on the inside of the cutter where it cuts; the page shows the finished
   cookie size and the cutter's footprint.
4. Download the cutter and print it base-down with no supports. **Download pusher** gives
   a matching plate 2 mm smaller all round with a knob: press it down through the cutter
   to push out dough that sticks in narrow parts.

If the outline still follows the icing instead of the cookie (white icing on a white
plate, stripes near the edge, a pale rim the same colour as the table):

- Press **Zoom to box**, choose **Edge points**, and click 6 to 12 points on the cookie's
  outer edge in order around it. The outline follows the photo's edge between your
  points and updates after every click. Drag a point to move it, click near the line
  to add one there, and shift-click to remove one.
- Or press **Edit as points** after an automatic trace to turn it into points you can drag.

**Save project** writes a small `.json` file with the outline, your marks and the
settings. **Open project** loads it again, and **Make cutter** then rebuilds exactly the
same cutter, even without the photo.

## What makes the cutter good

| Part | Default | Why |
| --- | --- | --- |
| Height | 18 mm | Cuts dough rolled to 6 to 10 mm with room to spare |
| Base (flange) | 2.4 mm thick, 6 mm wide | Prints flat, spreads hand pressure, stops the outline warping |
| Wall | 1.6 mm (4 x nozzle), straight to about 10 mm | Stiff where you push |
| Cutting edge | 0.8 mm (2 x nozzle), tapered over the top 8 mm | Clean cut; slices as two whole lines (see below) |
| Chamfer from base to wall | 1.6 mm | Removes the weak corner where cutters snap |
| Smallest outward point radius | 1.5 mm | Cookie points survive cutting and baking |
| Smallest inward notch radius | 2.5 mm | Dough releases instead of sticking |
| Outline | Smoothing spline, a point every 0.5 mm | No jagged or stair-stepped edges |
| Dough spread | 0 mm (try 1 mm for sugar cookies) | A baked cookie is bigger than the dough that was cut |

**Slicer check.** A blade thinner than two slicer lines can print as one wobbly line or
gap fill, which is the most common complaint about printed cutters. CI slices a cutter in
PrusaSlicer 2.7 with both the classic and Arachne wall generators, at 0.42, 0.45 and
0.5 mm lines for a 0.4 mm nozzle (plus 0.25 and 0.6 mm nozzles), and checks every layer
of the taper prints as two full loops right up to the top. Slightly wider edges
(0.9 to 1 mm) did worse: classic mode filled the middle with a gap-fill line. OrcaSlicer
was not tested; it uses the same Arachne generator by default.

The inside face of the blade sits exactly on the traced outline and is vertical, so the
cookie comes out the size and shape you asked for. Every outline is checked for radius
of curvature after smoothing, and every cutter is checked to be one watertight piece.

## What CutterSnap does that other cutter makers don't

Most cutter makers are web apps with a subscription, or OpenSCAD and Inkscape scripts
that need a clean SVG. CutterSnap starts from an ordinary photo and runs on your own
machine.

- **A real base.** A 2.4 x 6 mm flange with a 1.6 mm chamfer into the wall. Other tools
  don't publish a base spec, and warped, snapping corners are a common complaint.
- **Rules for points and notches.** Points are rounded to at least 1.5 mm and notches
  to at least 2.5 mm, and the outline is re-checked after smoothing, so there are no
  dough-tearing slivers or jagged edges.
- **Dough spread.** Shrink the cutter so the baked cookie matches the one in the photo.
- **A blade sized to your nozzle and slice-tested** (see above), with a continuous taper
  instead of a stepped "extra blade".
- **Tracing that copes with real photos.** Automatic edge tracing ignores icing details,
  and Edge points handle white-on-white cookies and striped icing.
- **Pusher plate** for shapes where dough sticks.
- **Project files** that rebuild the same STL, byte for byte.
- **Free, self-hosted, no accounts, no AI, nothing uploaded anywhere.**

Printed cutters are not food-safe in any certified sense: layer lines hold on to dough.
Wash by hand in warm (not hot) water, dry right away, and replace them when the edge gets
rough. PETG lasts longer than PLA, which softens around 50 °C.

## How the tracing works

1. **Edge shape.** Canny edges inside your box are thickened just enough to close small
   gaps, and whatever the box border cannot flood into is the cookie. This finds the
   outer edge even for white icing on a white plate, and ignores icing details inside.
2. **GrabCut refinement** adjusts a narrow band around that shape by colour and obeys
   your clicks.
3. **Edge points** (when you place them) replace steps 1 and 2: OpenCV's Intelligent
   Scissors finds the cheapest edge path between neighbouring points on a
   median-filtered copy of the photo, which wipes out thin icing lines first.
4. **Outline rules.** Holes are filled, the shape is scaled to your size in mm, corners
   are rounded to the minimum radii, and a closed smoothing spline is fitted.

## Command line

```sh
pip install .
cuttersnap photo.jpg cutter.stl --box 520,1060,350,380 --cookie 690,1250 --size 90 --preview check.jpg
cuttersnap photo.jpg cutter.stl --edge 876,602 --edge 920,582 --edge 1031,655 ... --save-project heart.json
cuttersnap heart.json cutter.stl --pusher pusher.stl   # rebuild a saved project, plus a pusher plate
```

## Development

```sh
pip install -e '.[dev]'
pytest
uvicorn cuttersnap.api:app --reload --port 8080
```

## Status

Early. Planned next: a "this is dough" colour click, edge snapping for white-on-white
cookies, draggable outline points, red-circle detection on screenshots, 3MF export,
and saving projects as JSON.

Licensed MIT. Bundles [three.js](https://threejs.org) (MIT) for the 3D preview.
