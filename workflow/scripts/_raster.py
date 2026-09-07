"""Raster operations shared by hectare floor-area scripts."""

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry.base import BaseGeometry


def write_raster(path, profile, values, bands, units, tags):
    """Persist aligned support arrays with their explicit band contract."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **{**profile, "count": len(bands)}) as output:
        for index, (value, band, unit) in enumerate(
            zip(values, bands, units, strict=True), 1
        ):
            output.write(np.asarray(value, dtype=profile["dtype"]), index)
            output.set_band_description(index, band)
            output.set_band_unit(index, unit)
        output.update_tags(**tags)


def scope_geometry(shapes: gpd.GeoDataFrame, crs: Any) -> BaseGeometry:
    """Return the union of land shapes in the requested CRS."""
    return shapes.to_crs(crs).geometry.union_all()


def finish_raster(
    output: rasterio.DatasetWriter,
    descriptions: tuple[str, str, str],
    units: tuple[str, str, str],
    tags: dict[str, str | int],
) -> None:
    """Create the total band blockwise and attach units and provenance tags."""
    for _, window in output.block_windows(1):
        total = output.read(1, window=window) + output.read(2, window=window)
        output.write(total, 3, window=window)
    for band, (description, unit) in enumerate(
        zip(descriptions, units, strict=True), 1
    ):
        output.set_band_description(band, description)
        output.set_band_unit(band, unit)
    output.update_tags(**tags)
