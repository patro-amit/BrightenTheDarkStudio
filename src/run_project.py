"""Run the image experiment and log the disposition of every input file."""
import argparse
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")

if __package__:
    from .enhancement import enhance_gray_set, equalize_rgb_channels, equalize_luminance
    from .metrics import metric_row, grayscale_for_metrics
    from .project_io import load_image, output_tags, save_png, write_csv
    from .scene import enhance_color, profile, FIXED, apply_luma, merge_luma
    from .visualization import save_comparison_figure, save_clahe_sweep
else:
    from enhancement import enhance_gray_set, equalize_rgb_channels, equalize_luminance
    from metrics import metric_row, grayscale_for_metrics
    from project_io import load_image, output_tags, save_png, write_csv
    from scene import enhance_color, profile, FIXED, apply_luma, merge_luma
    from visualization import save_comparison_figure, save_clahe_sweep

ROOT = Path(__file__).resolve().parents[1]
INPUT_DIR = ROOT / "data" / "originals"
OUT_DIR = ROOT / "outputs"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
METRICS = ("Entropy_bits", "Mean_brightness", "Std_contrast", "AMBE_vs_input",
           "PSNR_vs_input_dB", "SSIM_vs_input")
TUNING_FIELDS = ("image", "clip", "tiles", "strength", "shadow_fraction", "input_median",
                 "shadow_lift", "detail_gain", "flat_noise_proxy_gain", "score", "selected")


def run_project(input_dir=INPUT_DIR, out_dir=OUT_DIR, figures=True, enhanced_images=True):
    input_dir, out_dir = Path(input_dir), Path(out_dir)
    if not input_dir.is_dir():
        raise ValueError(f"Input directory does not exist: {input_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    figure_dir = out_dir / "figures"
    if figures:
        figure_dir.mkdir(exist_ok=True)
    files = sorted(p for p in input_dir.iterdir() if p.is_file())
    tags = output_tags(p for p in files if p.suffix.lower() in EXTENSIONS)
    rows, tuning, audit, he_checks = [], [], [], []

    for path in files:
        if path.suffix.lower() not in EXTENSIONS:
            audit.append({"image": path.name, "status": "skipped", "reason": "unsupported extension"})
            continue
        try:
            bgr = load_image(path)
        except (OSError, ValueError, cv2.error) as error:
            audit.append({"image": path.name, "status": "skipped", "reason": str(error)})
            continue

        gray = grayscale_for_metrics(bgr)
        gray_results = enhance_gray_set(gray)
        setting, candidates = profile(gray)
        color_results = {
            "RGB_channels_equalized": equalize_rgb_channels(bgr),
            "YCrCb_luminance_HE": equalize_luminance(bgr, "YCrCb"),
            "Lab_luminance_HE": equalize_luminance(bgr, "Lab"),
        }
        tuned = enhance_color(bgr, setting)
        converted = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        fixed = merge_luma(converted, apply_luma(converted[:, :, 0], FIXED, shadow_only=False))
        results = {**gray_results, **color_results, "Scene_Tuned_CLAHE": tuned,
                   "Fixed_Luminance_CLAHE": fixed}
        tag = tags[path.name]
        image_dir = out_dir / "enhanced_images" / tag
        if enhanced_images:
            image_dir.mkdir(parents=True, exist_ok=True)
        try:
            image_rows = []
            for method, result in results.items():
                if enhanced_images:
                    save_png(image_dir / f"{method}.png", result)
                image_rows.append({"image": path.name, "method": method,
                                   **metric_row(gray, grayscale_for_metrics(result))})
            if figures:
                save_comparison_figure(path.name, bgr, results, figure_dir / f"{tag}_comparison.png")
                save_clahe_sweep(gray, path.name, figure_dir / f"{tag}_clahe_sweep.png")
        except (OSError, ValueError, cv2.error) as error:
            audit.append({"image": path.name, "status": "failed", "reason": str(error)})
            continue

        difference = cv2.absdiff(gray_results["HE_numpy"], gray_results["HE_OpenCV"])
        he_checks.append({"image": path.name, "different_pixels": np.count_nonzero(difference),
                          "max_abs_difference": int(difference.max()), "pixels": gray.size})
        rows.extend(image_rows)
        tuning.extend({"image": path.name, **row} for row in candidates)
        audit.append({"image": path.name, "status": "processed", "reason": ""})
        print(f"Processed {path.name}")

    write_csv(out_dir / "metrics.csv", ("image", "method", *METRICS), rows)
    write_csv(out_dir / "scene_tuning.csv", TUNING_FIELDS, tuning)
    write_csv(out_dir / "image_run_log.csv", ("image", "status", "reason"), audit)
    write_csv(out_dir / "he_verification.csv", ("image", "different_pixels", "max_abs_difference",
                                                "pixels"), he_checks)
    skipped = [row for row in audit if row["status"] != "processed"]
    write_csv(out_dir / "skipped_images.csv", ("image", "status", "reason"), skipped)
    print(f"{len(he_checks)} processed, {len(skipped)} skipped/failed, {len(rows)} metric rows.")
    print(f"Results and input log: {out_dir}")
    return bool(rows) and not any(row["status"] == "failed" for row in audit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--no-figures", action="store_true")
    parser.add_argument("--no-enhanced-images", action="store_true")
    args = parser.parse_args()
    try:
        return 0 if run_project(args.input_dir, args.output_dir, not args.no_figures,
                                not args.no_enhanced_images) else 1
    except (OSError, ValueError) as error:
        parser.exit(1, f"Image run failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
