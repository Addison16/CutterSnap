# Reference outlines

Six finished cookie outlines (bear, squirrel, deer, pine tree, pom-pom hat,
knotted baby gown), 79.248 mm (3.12 in) on the longest side, saved as
CutterSnap project files. They came from a design bundle made outside
CutterSnap, with its own SVG silhouettes and STL cutters.

They are hard on purpose: smooth-looking drawn curves that still have points
as sharp as 0.01 mm, and slits as narrow as 0.8 mm between the gown's sleeves
and body. Built as they were, two of them (pine tree, pom-pom hat) gave
cutters that were not watertight. `test_reference_outlines.py` checks that
every one now builds a watertight cutter whose blade passes the corner rules.

Points were sampled every 0.25 mm along each SVG path, with y flipped to
CutterSnap's y-up millimetre frame.
