"""Open Results Studio and optionally run a fresh experiment first."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "outputs" / "review" / "index.html"
VIDEO_TYPES = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}


def run_script(name, *arguments):
    subprocess.run([sys.executable, str(ROOT / "src" / name), *map(str, arguments)],
                   cwd=ROOT, check=True)


def test_video(path):
    path = path.expanduser().resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in VIDEO_TYPES:
        raise ValueError("Choose a supported video file (MP4, MOV, WebM, M4V, AVI or MKV).")
    source_folder = ROOT / "data" / "video"
    outputs = ROOT / "outputs" / "video"
    source_folder.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    # Reserve a unique run name and keep previous benchmarks available.
    with TemporaryDirectory(prefix="video-test-", dir=outputs) as scratch:
        scratch = Path(scratch)
        name = f"{path.stem}-{scratch.name.removeprefix('video-test-')}"
        target = source_folder / f"{name}{path.suffix.lower()}"
        run_script("run_video.py", path, "--output-dir", scratch)
        shutil.copy2(path, scratch / target.name)
        (scratch / target.name).replace(target)
        final = outputs / name
        final.mkdir()
        for artifact in scratch.iterdir():
            artifact.replace(final / artifact.name)
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    experiment = parser.add_mutually_exclusive_group()
    experiment.add_argument("--video", type=Path, help="Benchmark a new clip with all three video methods.")
    experiment.add_argument("--images", action="store_true", help="Run the image experiment before opening.")
    parser.add_argument("--refresh", action="store_true", help="Re-index results from earlier runs.")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    run = None
    try:
        if args.video:
            run = test_video(args.video)
        if args.images:
            run_script("run_project.py")
        if args.video or args.images or args.refresh or not DASHBOARD.is_file():
            run_script("build_review.py")
        url = DASHBOARD.as_uri() + (f"?{urlencode({'run': run})}#video" if run else "")
        if not args.no_open:
            webbrowser.open(url, new=2)
        print(url)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Could not open results: {error}\n")


if __name__ == "__main__":
    main()
