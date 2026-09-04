"""Raster operations shared by hectare floor-area scripts."""

from typing import Any

import geopandas as gpd
import rasterio
from shapely.geometry.base import BaseGeometry


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
