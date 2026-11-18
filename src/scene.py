"""Explainable luminance-only CLAHE selection for each image or video scene."""
from dataclasses import asdict, dataclass

import cv2
import numpy as np

if __package__:
    from .enhancement import clahe
else:
    from enhancement import clahe


@dataclass(frozen=True)
class Setting:
    clip: float
    tiles: int
    strength: float


FIXED = Setting(2.0, 8, 1.0)
IDENTITY = Setting(0.0, 0, 0.0)
CANDIDATES = (IDENTITY,) + tuple(
    Setting(clip, tiles, strength)
    for clip in (1.0, 2.0, 4.0)
    for tiles in (4, 8, 16)
    for strength in (0.55, 0.85)
)


def preview(image, max_side=480):
    height, width = image.shape[:2]
    scale = max_side / max(height, width)
    if scale >= 1:
        return image
    return cv2.resize(image, (max(1, round(width * scale)), max(1, round(height * scale))),
                      interpolation=cv2.INTER_AREA)


def shadow_weights(gray):
    # Full strength below level 55, falling smoothly to zero at level 170.
    weight = np.clip((170.0 - gray.astype(np.float32)) / 115.0, 0, 1)
    return weight ** 2 * (3 - 2 * weight)


def apply_luma(gray, setting, shadow_only=True):
    if not setting.strength:
        return gray.copy()
    enhanced = clahe(gray, setting.clip, (setting.tiles, setting.tiles))
    if not shadow_only:
        return enhanced
    lift = np.maximum(enhanced.astype(np.float32) - gray, 0)
    return np.rint(gray + lift * shadow_weights(gray) * setting.strength).astype(np.uint8)


def merge_luma(converted, gray):
    updated = converted.copy()
    updated[:, :, 0] = gray
    return cv2.cvtColor(updated, cv2.COLOR_YCrCb2BGR)


def enhance_color(bgr, setting):
    if not setting.strength:
        return bgr.copy()
    converted = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
    return merge_luma(converted, apply_luma(converted[:, :, 0], setting))


def profile(gray):
    sample = preview(gray)
    base = sample.astype(np.float32)
    baseline_texture = np.abs(base - cv2.GaussianBlur(base, (5, 5), 0))
    shadow = sample < 95
    local_mean = cv2.blur(base, (7, 7))
    local_variance = cv2.blur(base ** 2, (7, 7)) - local_mean ** 2
    flat_shadow = shadow & (local_variance < 16)
    textured_shadow = shadow & (local_variance >= 16)
    shadow_fraction = float(shadow.mean())
    median = float(np.median(sample))
    rows = []

    for setting in CANDIDATES:
        result = apply_luma(sample, setting).astype(np.float32)
        texture = np.abs(result - cv2.GaussianBlur(result, (5, 5), 0))
        shadow_lift = float((result[shadow] - base[shadow]).mean()) if shadow.any() else 0.0
        flat_change = texture[flat_shadow] - baseline_texture[flat_shadow]
        textured_change = texture[textured_shadow] - baseline_texture[textured_shadow]
        noise_gain = max(0.0, float(flat_change.mean())) if flat_change.size else 0.0
        detail_gain = float(textured_change.mean()) if textured_change.size else 0.0
        # Bright scenes receive a stronger penalty for unnecessary adjustment.
        target = 20 if median < 65 else 14
        exposure_weight = min(1.0, shadow_fraction * 2)
        if median >= 105:
            exposure_weight *= 0.35
        score = (
            exposure_weight * (min(shadow_lift, target) + 0.6 * detail_gain)
            - 0.8 * max(shadow_lift - target, 0)
            - 3.0 * noise_gain
            - 0.045 * float((result - base).mean())
            - (0.7 if setting.strength else 0.0)
        )
        rows.append({**asdict(setting), "shadow_fraction": shadow_fraction,
                     "input_median": median, "shadow_lift": shadow_lift,
                     "detail_gain": detail_gain, "flat_noise_proxy_gain": noise_gain,
                     "score": score, "selected": False})
    winner = max(range(len(rows)), key=lambda i: rows[i]["score"])
    rows[winner]["selected"] = True
    return CANDIDATES[winner], rows
