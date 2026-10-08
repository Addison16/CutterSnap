# CutterSnap

Turn a photo of a cookie into a sturdy, smooth, 3D-printable cookie cutter.
Self-hosted in Docker. Classical computer vision only: no AI models, no cloud calls.

## Install with Docker

CutterSnap ships as a ready-made image for 64-bit PCs, Macs and Raspberry Pis
(`linux/amd64` and `linux/arm64`), so there is nothing to build.

**Docker run.** One command:

```sh
docker run -d --name cuttersnap --restart unless-stopped \
  -p 8080:8080 -v cuttersnap-designs:/data \
  ghcr.io/addison16/cuttersnap:latest
```

**Docker Compose.** Save this as `compose.yaml` and run `docker compose up -d`:

```yaml
services:
  cuttersnap:
    image: ghcr.io/addison16/cuttersnap:latest
    ports:
      - "8080:8080"
    volumes:
      - designs:/data   # saved designs survive updates
    restart: unless-stopped

volumes:
  designs:
```

Then open http://localhost:8080.

- **Port.** To use another port, change the left number, for example `-p 9000:8080`.
- **Saved designs** live in the volume mounted at `/data`. Keep the `-v` (or `volumes:`) line
  and they survive updates and restarts.
- **Pin a version** with `:0.1.0` instead of `:latest` if you want updates only when you choose.
- **Update** with `docker pull ghcr.io/addison16/cuttersnap:latest`, then remove and re-run the
  container (`docker compose pull && docker compose up -d` with Compose). Your designs stay.
- **Build it yourself** from a clone instead: `docker compose up -d --build`.

**Accounts.** The first time you open CutterSnap it asks you to create the admin account.
Designs saved before accounts existed become that account's. After that, anyone who can open
the page can create their own account, and each person sees only their own designs. Once
everyone has one, open your name in the top corner, choose **Users and sign-up** and turn
sign-up off. That menu also sets a new password for anyone who forgets theirs, or deletes an
account with its designs. Accounts live in `/data/cuttersnap.db` in the same volume, with
passwords stored as salted scrypt hashes; nothing is sent anywhere.

Forgot the admin password? Set a new one from the computer running CutterSnap:

```sh
docker exec -it cuttersnap python -m cuttersnap.users reset-password YOUR_NAME
```

With Compose, run `docker compose exec cuttersnap python -m cuttersnap.users reset-password YOUR_NAME`
from the folder with `docker-compose.yml`.

**On your phone.** Open the same address from any phone on your home Wi-Fi, using the
computer's local address (for example http://192.168.1.20:8080), sign in, take the photo there,
and **Save to my designs**. The design then waits under **My designs** wherever you sign in,
ready to download on the computer next to your printer.

**Reaching it from outside your home.** Put CutterSnap behind a reverse proxy with HTTPS
(Caddy, Traefik, nginx or a Cloudflare tunnel) rather than opening port 8080 directly, so
passwords never cross the internet unencrypted. The sign-in cookie is marked secure when the
proxy sends `X-Forwarded-Proto: https`, and a proxy that rewrites the `Host` header must pass
the original as `X-Forwarded-Host`. Turn sign-up off before you open it up.

## Use it

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

**Corners.** Orange rings on the photo show where the outline was rounded to the minimum
point and notch radii, so you can see what changed from the photo.

**More options.**
- **Halo border** grows the cutter all round, for a "bubble" outline around the design.
- **Initials on the base** presses up to 3 letters into the underside of the base, which
  faces up when you cut. They follow the curve of the base, as low on the cookie as they fit.
- **Mirror image** makes the other one of a pair, like left and right mittens.

**Matching stamp.** Tick **Matching stamp** and the icing lines inside the cookie show in
blue on the photo. **Stamp detail** finds fainter lines or gives a cleaner stamp, and
**Erase stamp line** removes any line you don't want (crumbs, watermarks, shine). Make
cutter then also offers **Download stamp**: a 4 mm plate that fits inside the cutter with
1.5 mm clearance (1 mm was too tight in other makers' stamps) and the lines raised 2 mm.
**Stamp depth** raises them 1 to 4 mm, deeper for thicker dough. Print it flat side down. After cutting, press
it into the dough inside the cutter to print the design.

The cutter and stamp are built as mirror images, because both are turned over to use;
the cookie and its imprint come out the same way round as the photo.

If the outline still follows the icing instead of the cookie (white icing on a white
plate, stripes near the edge, a pale rim the same colour as the table):

- Press **Zoom to box**, choose **Edge points**, and click 6 to 12 points on the cookie's
  outer edge in order around it. The outline follows the photo's edge between your
  points and updates after every click. Drag a point to move it, click near the line
  to add one there, and shift-click to remove one.
- Or press **Edit as points** after an automatic trace to turn it into points you can drag.

**Save project file** writes a small `.json` file with the outline, your marks and the
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

**Smooth curves.** A cutter is only as smooth as its STL: some cutter makers export coarse
meshes whose flat facets show as ridges on round cutters. CutterSnap places outline points
every 0.5 mm and rounds points with 16 segments per quarter circle, and the page reports how
far the flat facets stray from the true curve (usually about 0.02 mm, far below one printed
line). The check fails above 0.05 mm.

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
- **Pusher plate** for shapes where dough sticks, and a **matching stamp** made from the
  icing lines in the same photo.
- **Project files** that rebuild the same STL, byte for byte, and **My designs**, so a cutter
  made on your phone is waiting on the computer by your printer.
- **A smoothness check** on the STL itself, not just the outline.
- **Free and self-hosted, no AI, nothing uploaded anywhere.** Accounts are kept on your own
  CutterSnap, so a family or a club can share one with each person's designs kept apart.

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
cuttersnap apple.jpg cutter.stl --box 520,1060,350,380 --stamp stamp.stl --stamp-detail 0.5 --stamp-depth 3
cuttersnap mitten.json right.stl --flip --initials AH --halo 3   # the other mitten of a pair
```

With a `.json` project, `--spread`, `--halo`, `--initials` and `--flip` change its saved
settings; without them it rebuilds exactly what was saved.

## Development

```sh
pip install -e '.[dev]'
pytest
uvicorn cuttersnap.api:app --reload --port 8080
```

## Releasing

1. Set the version in `pyproject.toml` and `cuttersnap/__init__.py`.
2. Write the notes in `docs/releases/vX.Y.Z.md`.
3. Push a tag: `git tag v0.1.0 && git push origin v0.1.0`.

CI then tests the code, publishes `ghcr.io/addison16/cuttersnap` as `0.1.0`, `0.1` and
`latest` for amd64 and arm64, and creates the GitHub release from the notes file.

## Status

Early but complete: tracing, edge points, smooth outlines, a slice-tested blade, pusher plate,
matching stamp, initials, project files, saved designs and accounts. A possible next step is
red-circle detection on phone screenshots.

Licensed MIT. Bundles [three.js](https://threejs.org) (MIT) for the 3D preview.
