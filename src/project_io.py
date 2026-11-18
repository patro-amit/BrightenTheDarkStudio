"""Shared output and input helpers."""
from collections import Counter
import csv
from pathlib import Path

import cv2
import numpy as np


def write_csv(path, fields, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def load_image(path):
    data = path.read_bytes()
    if not data:
        raise ValueError("empty file")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("OpenCV could not decode the image")
    return image


def save_png(path, image):
    ok, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 2])
    if not ok:
        raise OSError(f"Could not encode {path}")
    path.write_bytes(encoded.tobytes())

def output_tags(paths):
    """Keep familiar stems and reserve unique names for case-insensitive collisions."""
    paths = sorted(paths)
    counts = Counter(path.stem.casefold() for path in paths)
    reserved = {key for key, count in counts.items() if count == 1}
    tags = {}
    for path in paths:
        tag = path.stem
        if counts[tag.casefold()] > 1:
            tag = f"{path.name}_input"
            while tag.casefold() in reserved:
                tag += "_"
            reserved.add(tag.casefold())
        tags[path.name] = tag
    return tags
