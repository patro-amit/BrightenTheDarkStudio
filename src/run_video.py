"""Enhance a video and measure frame latency and changes in brightness lift."""
import argparse
from dataclasses import asdict
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from time import perf_counter

import cv2
import numpy as np

if __package__:
    from .project_io import write_csv
    from .scene import FIXED, apply_luma, merge_luma, preview, profile, shadow_weights
else:
    from project_io import write_csv
    from scene import FIXED, apply_luma, merge_luma, preview, profile, shadow_weights

MODES = ("fixed", "scene_tuned", "stabilized")
FRAME_FIELDS = ("frame", "time_s", "scene", "cut", "histogram_distance", "spatial_correlation", "clip", "tiles",
                "strength", "input_luma", "mean_lift", "flicker", "enhancement_ms", "profile_ms")


class SceneState:
    """Retune on cuts and smooth the enhancement lift within each scene."""

    def __init__(self, cut_threshold, alpha):
        self.cut_threshold = cut_threshold
        self.alpha = alpha
        self.histogram = None
        self.previous_thumbnail = None
        self.setting = None
        self.scene = 0
        self.smoothed_lift = None

    def update(self, gray):
        sample = preview(gray, 160)
        thumbnail = cv2.resize(sample, (32, 32), interpolation=cv2.INTER_AREA)
        hist = cv2.calcHist([sample], [0], None, [32], [0, 256]).ravel() / sample.size
        distance = 0.0 if self.histogram is None else float(np.abs(hist - self.histogram).sum() / 2)
        change, correlation = 0.0, 1.0
        if self.previous_thumbnail is not None:
            change = float(cv2.absdiff(thumbnail, self.previous_thumbnail).mean())
            current = thumbnail.astype(np.float32)
            previous = self.previous_thumbnail.astype(np.float32)
            current -= current.mean()
            previous -= previous.mean()
            spread = float(current.std() * previous.std())
            if spread >= 16:
                correlation = float((current * previous).mean() / spread)
        cut = self.histogram is None or distance >= self.cut_threshold or (
            distance >= 0.15 and change >= 34
        ) or (correlation <= 0.4 and change >= 12)
        self.histogram, self.previous_thumbnail = hist, thumbnail
        rows, profile_ms = [], 0.0
        if cut:
            start = perf_counter()
            self.setting, rows = profile(gray)
            profile_ms = (perf_counter() - start) * 1000
            self.scene += 1
            self.smoothed_lift = None
        return cut, distance, correlation, rows, profile_ms

    def stabilize(self, gray, tuned):
        lift = tuned.astype(np.float32) - gray
        observed = float(lift.mean())
        if self.smoothed_lift is None:
            self.smoothed_lift = observed
            return tuned
        self.smoothed_lift += self.alpha * (observed - self.smoothed_lift)
        weight = shadow_weights(gray)
        # Distribute the correction only to shadows and cap it to limit lag artifacts.
        correction = np.clip((self.smoothed_lift - observed) / max(float(weight.mean()), 0.05),
                             -8.0, 8.0)
        corrected = np.clip(lift + weight * correction, 0, 255 - gray)
        return np.rint(gray + corrected).astype(np.uint8)


def find_ffmpeg():
    """Locate FFmpeg on PATH or through the bundled imageio-ffmpeg binary."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        return None


def export_video(intermediate, source, target, audio):
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        if audio:
            print("FFmpeg is unavailable. The MP4 output contains video only.")
        shutil.copyfile(intermediate, target)
        return
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(intermediate)]
    if audio:
        command += ["-i", str(source), "-map", "0:v:0", "-map", "1:a:0?", "-c:a", "aac"]
    command += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264",
                "-preset", "fast", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if audio:
        command += ["-af", "apad", "-shortest"]
    result = subprocess.run(command + [str(target)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"FFmpeg export failed: {result.stderr.strip()}")


def export_browser_video(intermediate, target, fps, size):
    """Create a browser-compatible VP8 WebM fallback when FFmpeg is unavailable."""
    capture = cv2.VideoCapture(str(intermediate))
    writer = cv2.VideoWriter(str(target), cv2.VideoWriter_fourcc(*"VP80"), fps, size)
    if not capture.isOpened() or not writer.isOpened():
        capture.release()
        writer.release()
        raise RuntimeError("Could not create the browser-compatible WebM output.")
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            writer.write(frame)
    finally:
        capture.release()
        writer.release()


def analyze_video(source, destination, cut_threshold=0.43, alpha=0.22, audio=True):
    source, destination = Path(source), Path(destination)
    if not source.is_file():
        raise ValueError(f"Video file does not exist: {source}")
    if not 0 < cut_threshold <= 1 or not 0 < alpha <= 1:
        raise ValueError("Cut threshold and alpha must be in (0, 1].")
    capture = cv2.VideoCapture(str(source))
    state = SceneState(cut_threshold, alpha)
    metrics = {mode: [] for mode in MODES}
    previous_lift = {}
    tuning = []
    destination.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(dir=destination) as temp:
        temp = Path(temp)
        writers = {}
        files = {mode: temp / f"{mode}_intermediate.mp4" for mode in MODES}
        fps = capture.get(cv2.CAP_PROP_FPS)
        try:
            ok, frame = capture.read()
            if not ok or not np.isfinite(fps) or fps <= 0:
                raise ValueError("OpenCV could not decode the video or determine a positive FPS.")
            height, width = frame.shape[:2]
            size = (width + width % 2, height + height % 2)
            for mode in MODES:
                writers[mode] = cv2.VideoWriter(str(files[mode]), cv2.VideoWriter_fourcc(*"mp4v"),
                                                fps, size)
                if not writers[mode].isOpened():
                    raise RuntimeError(f"Could not open an MP4 writer for {mode}")
            index = 0
            while ok:
                if frame.shape[:2] != (height, width):
                    raise ValueError("Frame resolution changed. Convert the source to fixed size first.")
                converted = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
                gray = converted[:, :, 0]
                mean_input = float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
                cut, distance, correlation, candidates, profile_ms = state.update(gray)
                tuning.extend({"scene": state.scene, "start_frame": index, **row}
                              for row in candidates)

                start = perf_counter()
                fixed_luma = apply_luma(gray, FIXED, shadow_only=False)
                fixed_ms = (perf_counter() - start) * 1000
                start = perf_counter()
                tuned_luma = apply_luma(gray, state.setting)
                tuned_ms = (perf_counter() - start) * 1000
                start = perf_counter()
                stable_luma = state.stabilize(gray, tuned_luma)
                stable_ms = tuned_ms + (perf_counter() - start) * 1000

                outputs = {"fixed": (fixed_luma, FIXED, fixed_ms),
                           "scene_tuned": (tuned_luma, state.setting, tuned_ms),
                           "stabilized": (stable_luma, state.setting, stable_ms)}
                for mode, (luma, setting, elapsed) in outputs.items():
                    start = perf_counter()
                    bgr = frame if not setting.strength else merge_luma(converted, luma)
                    elapsed += (perf_counter() - start) * 1000
                    mean_lift = float(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).mean()) - mean_input
                    flicker = None if cut else abs(mean_lift - previous_lift[mode])
                    previous_lift[mode] = mean_lift
                    metrics[mode].append({
                        "frame": index, "time_s": index / fps, "scene": state.scene,
                        "cut": cut, "histogram_distance": distance,
                        "spatial_correlation": correlation, **asdict(setting),
                        "input_luma": mean_input, "mean_lift": mean_lift, "flicker": flicker,
                        "enhancement_ms": elapsed,
                        "profile_ms": 0.0 if mode == "fixed" else profile_ms,
                    })
                    padded = cv2.copyMakeBorder(bgr, 0, height % 2, 0, width % 2,
                                                cv2.BORDER_REPLICATE)
                    writers[mode].write(padded)
                index += 1
                ok, frame = capture.read()
        finally:
            capture.release()
            for writer in writers.values():
                writer.release()

        summaries = []
        for mode, rows in metrics.items():
            target = temp / f"{mode}.mp4"
            export_video(files[mode], source, target, audio)
            export_browser_video(files[mode], temp / f"{mode}.webm", fps, size)
            timings = [row["enhancement_ms"] + row["profile_ms"] for row in rows]
            flicker = [row["flicker"] for row in rows if row["flicker"] is not None]
            summaries.append({"method": mode, "frames": len(rows), "width": width, "height": height,
                              "fps": fps, "scenes": state.scene, "analyzed_transitions": len(flicker),
                              "mean_ms": float(np.mean(timings)), "p95_ms": float(np.percentile(timings, 95)),
                              "max_ms": max(timings),
                              "mean_flicker": float(np.mean(flicker)) if flicker else None,
                              "p95_flicker": float(np.percentile(flicker, 95)) if flicker else None,
                              "mean_lift": float(np.mean([row["mean_lift"] for row in rows]))})
            write_csv(temp / f"{mode}_frames.csv", FRAME_FIELDS, rows)

        write_csv(temp / "video_summary.csv", tuple(summaries[0]), summaries)
        write_csv(temp / "video_scene_tuning.csv", tuple(tuning[0]), tuning)
        for path in temp.iterdir():
            if not path.stem.endswith("_intermediate"):
                path.replace(destination / path.name)
    print(f"{index} frames across {state.scene} scene(s). Results: {destination}")
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--cut-threshold", type=float, default=0.43)
    parser.add_argument("--alpha", type=float, default=0.22)
    parser.add_argument("--mute", action="store_true")
    args = parser.parse_args()
    output = args.output_dir or Path(__file__).resolve().parents[1] / "outputs" / "video" / args.video.stem
    try:
        analyze_video(args.video, output, args.cut_threshold, args.alpha, not args.mute)
    except (OSError, ValueError, RuntimeError, cv2.error) as error:
        parser.exit(1, f"Video run failed: {error}\n")


if __name__ == "__main__":
    main()
