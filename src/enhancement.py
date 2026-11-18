"""Histogram-based enhancement functions for uint8 grayscale/color images."""
import cv2
import numpy as np


def equalize_histogram_numpy(gray):
    """Global HE from scratch using a 256-bin histogram and its CDF."""
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("Expected a 2-D uint8 grayscale image")
    hist = np.bincount(gray.ravel(), minlength=256)
    cdf = hist.cumsum()
    nonzero = np.flatnonzero(hist)
    if len(nonzero) == 0:
        return gray.copy()
    cdf_min = cdf[nonzero[0]]
    denominator = gray.size - cdf_min
    if denominator <= 0:  # Constant image: avoid division by zero.
        return gray.copy()
    lut = np.round((cdf - cdf_min) * 255 / denominator)
    lut = np.clip(lut, 0, 255).astype(np.uint8)
    return lut[gray]


def ahe(gray, kernel_size=32, clip_limit=0.0):
    """Tile-based AHE. A zero clip limit disables clipping in OpenCV."""
    height, width = gray.shape
    grid = (max(1, round(width / kernel_size)), max(1, round(height / kernel_size)))
    return clahe(gray, clip_limit, grid)


def clahe(gray, clip_limit=2.0, tile_grid_size=(8, 8)):
    """OpenCV CLAHE. tile_grid_size is the number of tiles (columns, rows)."""
    op = cv2.createCLAHE(clipLimit=float(clip_limit), tileGridSize=tile_grid_size)
    return op.apply(gray)


def gamma_correction(image, gamma=1.5):
    """Gamma baseline using output=(input/255) ** (1/gamma)."""
    lut = np.round(((np.arange(256) / 255.0) ** (1.0 / gamma)) * 255)
    return cv2.LUT(image, np.clip(lut, 0, 255).astype(np.uint8))


def equalize_rgb_channels(bgr):
    """Equalize B, G and R independently (included to show color distortion)."""
    return cv2.merge([cv2.equalizeHist(ch) for ch in cv2.split(bgr)])


def equalize_luminance(bgr, color_space="YCrCb"):
    """Equalize brightness channel only, keeping chroma channels unchanged."""
    if color_space == "YCrCb":
        converted = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)
        converted[:, :, 0] = cv2.equalizeHist(converted[:, :, 0])
        return cv2.cvtColor(converted, cv2.COLOR_YCrCb2BGR)
    if color_space == "Lab":
        converted = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        converted[:, :, 0] = cv2.equalizeHist(converted[:, :, 0])
        return cv2.cvtColor(converted, cv2.COLOR_LAB2BGR)
    raise ValueError("color_space must be 'YCrCb' or 'Lab'")


def enhance_gray_set(gray):
    """Named grayscale methods used by the experiment runner."""
    return {
        "HE_numpy": equalize_histogram_numpy(gray),
        "HE_OpenCV": cv2.equalizeHist(gray),
        "AHE": ahe(gray),
        "CLAHE_c2_g8x8": clahe(gray, 2.0, (8, 8)),
        "CLAHE_c4_g8x8": clahe(gray, 4.0, (8, 8)),
        "CLAHE_c2_g4x4": clahe(gray, 2.0, (4, 4)),
        "Gamma_1.5": gamma_correction(gray, 1.5),
    }
