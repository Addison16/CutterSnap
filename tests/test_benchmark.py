import json

import cv2
import numpy as np
from shapely.geometry import Polygon

from cuttersnap import benchmark
from cuttersnap.project import Project, sha256_file


def test_overlap_ignores_size_and_position():
    sq = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    big = Polygon([(50, 50), (90, 50), (90, 90), (50, 90)])
    assert benchmark.overlap(sq, big) > 0.999


def test_benchmark_scores_a_traced_photo(tmp_path, star_photo, capsys):
    img, truth = star_photo
    photos = tmp_path / "photos"
    photos.mkdir()
    cv2.imwrite(str(photos / "star.png"), img)
    cnts, _ = cv2.findContours(truth, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    ring = cnts[0][:, 0, :].astype(float) * [1, -1]  # y up, like project outlines
    Project(outline_mm=ring.tolist()).save(tmp_path / "star.json")
    cases = {"cases": [
        {"name": "star", "photo_sha256": sha256_file(photos / "star.png"), "reference": "star.json",
         "box": [130, 50, 540, 520]},
        {"name": "missing", "photo_sha256": "0" * 64, "reference": "star.json"},
    ]}
    (tmp_path / "cases.json").write_text(json.dumps(cases))
    rows = benchmark.run(tmp_path / "cases.json", photos)
    assert rows[0]["score"] > 0.8  # the star's needle points get rounded and rows[1]["score"] is None
    benchmark.main([str(tmp_path / "cases.json"), "--photos", str(photos)])
    assert "photo not found" in capsys.readouterr().out
    assert np.isfinite(rows[0]["score"])
