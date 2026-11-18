"""Simple image quality and brightness metrics."""
import cv2
import numpy as np


def entropy(gray):
    """Shannon entropy in bits, computed from the grayscale histogram."""
    p = np.bincount(gray.ravel(), minlength=256).astype(float)
    p /= p.sum()
    p = p[p > 0]
    return float(-np.sum(p * np.log2(p)))


def mean_brightness(gray):
    return float(np.mean(gray))


def contrast_std(gray):
    return float(np.std(gray))


def ambe(original_gray, enhanced_gray):
    """Absolute mean brightness error (lower means mean brightness preserved)."""
    return abs(mean_brightness(original_gray) - mean_brightness(enhanced_gray))


def structural_similarity(original, enhanced):
    """Mean SSIM over valid windows using sample covariance and 8-bit constants."""
    size = min(7, *original.shape)
    size -= (size + 1) % 2
    first = original.astype(np.float64)
    second = enhanced.astype(np.float64)
    kernel = (size, size)
    mean_a = cv2.blur(first, kernel)
    mean_b = cv2.blur(second, kernel)
    aa, bb, ab = mean_a ** 2, mean_b ** 2, mean_a * mean_b
    count = size ** 2
    correction = count / (count - 1) if count > 1 else 1
    var_a = correction * (cv2.blur(first ** 2, kernel) - aa)
    var_b = correction * (cv2.blur(second ** 2, kernel) - bb)
    cov = correction * (cv2.blur(first * second, kernel) - ab)
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    score = ((2 * ab + c1) * (2 * cov + c2)) / ((aa + bb + c1) * (var_a + var_b + c2))
    pad = size // 2
    valid = score[pad:-pad, pad:-pad] if pad else score
    return float(valid.mean())


def metric_row(original_gray, enhanced_gray):
    """All six metrics. PSNR and SSIM use the original image as reference."""
    mse = float(np.mean((original_gray.astype(np.float64) - enhanced_gray) ** 2))
    return {
        "Entropy_bits": entropy(enhanced_gray),
        "Mean_brightness": mean_brightness(enhanced_gray),
        "Std_contrast": contrast_std(enhanced_gray),
        "AMBE_vs_input": ambe(original_gray, enhanced_gray),
        "PSNR_vs_input_dB": float(10 * np.log10(255 ** 2 / mse)) if mse else float("inf"),
        "SSIM_vs_input": structural_similarity(original_gray, enhanced_gray),
    }


def grayscale_for_metrics(image):
    """Accept grayscale or OpenCV BGR image and return 8-bit grayscale."""
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
