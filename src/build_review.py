"""Build the offline project dashboard and index the current outputs."""
import argparse
from collections import defaultdict
import csv
import json
import os
from pathlib import Path
from shutil import copyfile
import time
from urllib.parse import quote

import cv2

if __package__:
    from .project_io import load_image, output_tags
    from .run_project import EXTENSIONS, INPUT_DIR, OUT_DIR
    from .scene import preview
else:
    from project_io import load_image, output_tags
    from run_project import EXTENSIONS, INPUT_DIR, OUT_DIR
    from scene import preview

FORMATS = {".png": "image", ".jpg": "image", ".jpeg": "image", ".mp4": "video",
           ".webm": "video", ".mov": "video", ".m4v": "video", ".avi": "video", ".mkv": "video", ".csv": "table", ".pdf": "pdf",
           ".docx": "document", ".md": "text"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv"}


def read_csv(path):
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def build_review(source, outputs):
    source, outputs = Path(source), Path(outputs)
    dashboard = outputs / "review"
    previews = dashboard / "images"
    previews.mkdir(parents=True, exist_ok=True)
    # New URLs on every rebuild so browsers never replay cached, stale media.
    stamp = str(int(time.time()))

    def link(path):
        return f"{quote(Path(os.path.relpath(path, dashboard)).as_posix())}?v={stamp}"

    images = []
    scores = defaultdict(list)
    for row in read_csv(outputs / "metrics.csv"):
        scores[row["image"]].append(row)
    selected = [row for row in read_csv(outputs / "scene_tuning.csv") if row["selected"] == "True"]
    if source.is_dir():
        tags = output_tags(p for p in source.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
        for index, row in enumerate(selected):
            name = row["image"]
            original = source / name
            if name not in tags or not original.is_file():
                continue
            folder = outputs / "enhanced_images" / tags[name]
            methods = [{"label": "Original", "path": link(original)}]
            thumb = previews / f"source-{index}.jpg"
            small = preview(load_image(original), 480)
            ok, encoded = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                thumb.write_bytes(encoded.tobytes())
            for metric in scores[name]:
                path = folder / f'{metric["method"]}.png'
                if path.is_file():
                    methods.append({"label": metric["method"], "path": link(path)})
            images.append({"name": name, "thumb": link(thumb if ok else original),
                           "methods": methods, "metrics": scores[name], "settings": row})

    videos = []
    for summary in sorted((outputs / "video").glob("*/video_summary.csv")):
        folder = summary.parent
        source_video = next((item for item in sorted((source.parent / "video").glob(f"{folder.name}.*"))
                             if item.suffix.lower() in VIDEO_EXTENSIONS), None)
        methods = []
        for row in read_csv(summary):
            name = row["method"]
            output = next((folder / f"{name}{extension}" for extension in (".webm", ".mp4")
                           if (folder / f"{name}{extension}").is_file()), None)
            if output is None:
                continue
            frames = [
                [float(frame["time_s"]), float(frame["input_luma"]), float(frame["mean_lift"]),
                 float(frame["flicker"]) if frame["flicker"] else None,
                 float(frame["enhancement_ms"]) + float(frame["profile_ms"]), frame["cut"] == "True"]
                for frame in read_csv(folder / f"{name}_frames.csv")
            ]
            methods.append({"summary": row, "path": link(output), "frames": frames})
        if methods:
            videos.append({"name": folder.name, "source": link(source_video) if source_video else None,
                           "methods": methods, "csv": link(summary),
                           "settings": [r for r in read_csv(folder / "video_scene_tuning.csv")
                                        if r.get("selected") == "True"]})

    project = Path(__file__).resolve().parents[1]
    files = []
    tables = {}
    roots = ((outputs, "Results"), (source, "Source images"), (source.parent / "video", "Source video"))
    entries = []
    for root, label in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and dashboard not in path.parents and path.suffix.lower() in FORMATS:
                entries.append((path, f"{label}/{path.relative_to(root).as_posix()}"))
    for path in sorted((*project.glob("*.docx"), *project.glob("*.pdf"))):
        entries.append((path, f"Reports/{path.name}"))
    for path, name in entries:
        url = link(path)
        kind = FORMATS[path.suffix.lower()]
        files.append({"name": name, "kind": kind, "path": url, "size": path.stat().st_size})
        if kind == "table":
            tables[url] = read_csv(path)
        elif kind == "text":
            tables[url] = path.read_text(encoding="utf-8")
    data = {"images": images, "videos": videos, "files": files, "tables": tables}
    here = Path(__file__).parent
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True).replace("<", "\\u003c")
    (dashboard / "index.html").write_text(
        (here / "review.html").read_text(encoding="utf-8")
        .replace("__PROJECT_DATA__", payload, 1)
        .replace("__STAMP__", stamp),
        encoding="utf-8",
    )
    for filename in ("review.css", "review.js"):
        copyfile(here / filename, dashboard / filename)
    print(f"Dashboard: {dashboard / 'index.html'} ({len(files)} files, {len(videos)} video runs)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()
    build_review(args.input_dir, args.output_dir)
