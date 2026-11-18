"""Plot image comparisons, histograms/CDFs, and CLAHE settings."""
import cv2
import matplotlib.pyplot as plt
import numpy as np


def _hist_cdf(gray):
    hist = np.bincount(gray.ravel(), minlength=256).astype(float)
    cdf = hist.cumsum()
    if cdf[-1] > 0:
        cdf /= cdf[-1]
    return hist, cdf


def save_comparison_figure(name, original, results, out_path):
    """Save rows: image, histogram, and CDF for source and each result."""
    images = [("Original", original)] + list(results.items())
    fig, axes = plt.subplots(len(images), 3, figsize=(12, 3.2 * len(images)), squeeze=False)
    for row, (label, image) in enumerate(images):
        gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        shown = gray if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        axes[row, 0].imshow(shown, cmap="gray" if image.ndim == 2 else None,
                            **({"vmin": 0, "vmax": 255} if image.ndim == 2 else {}))
        axes[row, 0].set_title(label)
        hist, cdf = _hist_cdf(gray)
        axes[row, 1].plot(hist, color="steelblue")
        axes[row, 1].set_title("Grayscale histogram")
        axes[row, 2].plot(cdf, color="darkorange")
        axes[row, 2].set_title("Normalized CDF")
        axes[row, 2].set_ylim(0, 1)
        for ax in axes[row]:
            if ax is not axes[row, 0]:
                ax.set_xlim(0, 255)
            else:
                ax.axis("off")
    fig.suptitle(name)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)


def save_clahe_sweep(gray, name, out_path, clip_limits=(1, 2, 4, 8),
                     grids=((4, 4), (8, 8), (16, 16))):
    """Create a visual parameter sweep for CLAHE."""
    fig, axes = plt.subplots(len(clip_limits), len(grids),
                             figsize=(4 * len(grids), 3 * len(clip_limits)), squeeze=False)
    for r, clip in enumerate(clip_limits):
        for c, grid in enumerate(grids):
            op = cv2.createCLAHE(clipLimit=float(clip), tileGridSize=grid)
            out = op.apply(gray)
            axes[r, c].imshow(out, cmap="gray", vmin=0, vmax=255)
            axes[r, c].set_title(f"clip={clip}, grid={grid}")
            axes[r, c].axis("off")
    fig.suptitle(f"CLAHE parameter sweep: {name}")
    fig.tight_layout()
    fig.savefig(out_path, dpi=160, bbox_inches="tight")
    plt.close(fig)
