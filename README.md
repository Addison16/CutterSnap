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
3. Pick the size and your nozzle, then **Trace outline** and **Make cutter**.
4. Download the STL and print it base-down with no supports.

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
| Cutting edge | 0.8 mm (2 x nozzle), tapered over the top 8 mm | Clean cut, prints the same in every slicer |
| Chamfer from base to wall | 1.6 mm | Removes the weak corner where cutters snap |
| Smallest outward point radius | 1.5 mm | Cookie points survive cutting and baking |
| Smallest inward notch radius | 2.5 mm | Dough releases instead of sticking |
| Outline | Smoothing spline, a point every 0.5 mm | No jagged or stair-stepped edges |
| Dough spread | 0 mm (try 1 mm for sugar cookies) | A baked cookie is bigger than the dough that was cut |

The inside face of the blade sits exactly on the traced outline and is vertical, so the
cookie comes out the size and shape you asked for. Every outline is checked for radius
of curvature after smoothing, and every cutter is checked to be one watertight piece.

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
cuttersnap heart.json cutter.stl   # rebuild from a saved project, byte for byte
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
