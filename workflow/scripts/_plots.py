"""Create diagnostic maps of hectare floor-area density.

The 99th percentile limits the influence of isolated extreme cells, while a
power-law normalisation keeps both low- and high-density settlements visible.
These plots are diagnostics; the underlying GeoTIFF retains untransformed data.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import PowerNorm


def plot_floor_area(raster_path: str, band: int, title: str, output_path: str) -> None:
    """Plot one floor-area band with a zero-safe nonlinear colour scale."""
    with rasterio.open(raster_path) as raster:
        values = raster.read(band, masked=True)
        extent = (
            raster.bounds.left,
            raster.bounds.right,
            raster.bounds.bottom,
            raster.bounds.top,
        )
    positive = values.compressed()
    vmax = (
        max(1, float(np.quantile(positive[positive > 0], 0.99)))
        if np.any(positive > 0)
        else 1
    )
    figure, axis = plt.subplots(figsize=(9, 7), constrained_layout=True)
    image = axis.imshow(
        values, extent=extent, cmap="magma", norm=PowerNorm(0.35, vmin=0, vmax=vmax)
    )
    axis.set(title=title, xlabel="Easting (m)", ylabel="Northing (m)")
    figure.colorbar(image, ax=axis, label="Floor area (m²/ha)")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=200)
    plt.close(figure)
