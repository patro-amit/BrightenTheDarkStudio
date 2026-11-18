import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from src.enhancement import equalize_histogram_numpy
from src.metrics import metric_row
from src.project_io import save_png
from src.run_project import run_project
from src.run_video import SceneState
from src.scene import IDENTITY, Setting, apply_luma, profile


class ProjectTest(unittest.TestCase):
    def test_global_he_and_identity_metrics(self):
        source = np.random.default_rng(5).integers(0, 256, (100, 100), dtype=np.uint8)
        np.testing.assert_array_equal(equalize_histogram_numpy(source), cv2.equalizeHist(source))
        metrics = metric_row(source, source)
        self.assertEqual(metrics["SSIM_vs_input"], 1)
        self.assertEqual(metrics["PSNR_vs_input_dB"], float("inf"))
        self.assertEqual(metric_row(source[:2, :3], source[:2, :3])["SSIM_vs_input"], 1)

    def test_audit_covers_readable_corrupt_and_unsupported_inputs(self):
        with TemporaryDirectory() as scratch:
            source = Path(scratch) / "source"
            target = Path(scratch) / "output"
            source.mkdir()
            save_png(source / "room_தமிழ்.png", np.full((40, 40, 3), 30, dtype=np.uint8))
            (source / "broken.jpg").write_bytes(b"invalid image")
            (source / "notes.txt").write_text("not an image")
            self.assertTrue(run_project(source, target, figures=False))
            with (target / "image_run_log.csv").open() as stream:
                rows = {row["image"]: row for row in csv.DictReader(stream)}
            self.assertEqual(rows["room_தமிழ்.png"]["status"], "processed")
            self.assertIn("decode", rows["broken.jpg"]["reason"])
            self.assertEqual(rows["notes.txt"]["reason"], "unsupported extension")
            with (target / "metrics.csv").open() as stream:
                self.assertEqual(len(list(csv.DictReader(stream))), 12)

    def test_shadow_mode_preserves_highlights_and_selects_identity_when_bright(self):
        gradient = np.tile(np.arange(256, dtype=np.uint8), (128, 1))
        out = apply_luma(gradient, Setting(4, 8, 0.85))
        np.testing.assert_array_equal(out[:, 170:], gradient[:, 170:])
        self.assertGreater(float(out[:, :80].mean()), float(gradient[:, :80].mean()))
        selected, candidates = profile(np.full((120, 120), 190, dtype=np.uint8))
        self.assertEqual(selected, IDENTITY)
        self.assertEqual(sum(row["selected"] for row in candidates), 1)

    def test_scene_detection_uses_layout_and_resets_stabilizer(self):
        first = np.tile(np.arange(20, 116, dtype=np.uint8), (96, 1))
        second = np.fliplr(first).copy()
        state = SceneState(0.43, 0.22)
        self.assertTrue(state.update(first)[0])
        self.assertFalse(state.update(first + 3)[0])
        state.stabilize(first, first + 8)
        self.assertTrue(state.update(second)[0])
        np.testing.assert_array_equal(state.stabilize(second, second + 2), second + 2)


if __name__ == "__main__":
    unittest.main()
