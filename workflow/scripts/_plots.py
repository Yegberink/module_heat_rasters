"""Create diagnostic maps of hectare floor-area density.

The 99th percentile limits the influence of isolated extreme cells, while a
power-law normalisation keeps both low- and high-density settlements visible.
These plots are diagnostics; the underlying GeoTIFF retains untransformed data.
"""

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import rioxarray
from matplotlib.colors import PowerNorm


def plot_floor_area(
    raster_path: str,
    band: int,
    title: str,
    output_path: str,
    chunk_size: int,
    max_size: int,
    colorbar_label: str = "Floor area (m²/ha)",
) -> None:
    """Plot a Dask-coarsened density band without loading the full raster."""
    opened: Any = rioxarray.open_rasterio(
        raster_path, chunks={"x": chunk_size, "y": chunk_size}
    )
    with opened as raster:
        values = raster.sel(band=band)
        factor = max(1, int(np.ceil(max(values.shape) / max_size)))
        values = (
            values.coarsen(x=factor, y=factor, boundary="pad")
            .max()
            .compute()
            .to_numpy()
        )
        values = np.ma.masked_equal(values, raster.rio.nodata)
        bounds = raster.rio.bounds()
        extent = bounds[0], bounds[2], bounds[1], bounds[3]
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
    figure.colorbar(image, ax=axis, label=colorbar_label)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=200)
    plt.close(figure)
