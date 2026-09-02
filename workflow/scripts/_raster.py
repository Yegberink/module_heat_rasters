"""Conservative raster operations shared by hectare regionalisation scripts.

The functions preserve alignment with an existing hectare raster, allocate a
known regional total in proportion to a proxy band, and derive the total band
from its two sector bands. Windowed reads and writes keep memory use bounded.
"""

import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import rasterio
from rasterio.features import geometry_mask, geometry_window
from rasterio.windows import Window
from shapely.geometry.base import BaseGeometry


def output_window(reference: rasterio.DatasetReader, bounds) -> Window:
    """Return the smallest whole-cell reference window covering ``bounds``."""
    raw = rasterio.windows.from_bounds(*bounds, transform=reference.transform)
    window = Window(
        math.floor(raw.col_off),
        math.floor(raw.row_off),
        math.ceil(raw.col_off + raw.width) - math.floor(raw.col_off),
        math.ceil(raw.row_off + raw.height) - math.floor(raw.row_off),
    )
    return window.intersection(Window(0, 0, reference.width, reference.height))


def create_output(
    path: str | Path, reference: rasterio.DatasetReader, bounds, schema: dict[str, Any]
) -> tuple[rasterio.DatasetWriter, Window]:
    """Create a three-band raster aligned exactly to a reference grid.

    The returned base window links output-local row and column offsets back to
    the reference raster during sector allocation.
    """
    window = output_window(reference, bounds)
    profile = reference.profile | {
        "width": int(window.width),
        "height": int(window.height),
        "transform": reference.window_transform(window),
        "count": 3,
        "dtype": schema["dtype"],
        "nodata": schema["nodata"],
        "compress": schema["compression"],
        "tiled": True,
        "blockxsize": schema["block_size"],
        "blockysize": schema["block_size"],
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return rasterio.open(path, "w+", **profile), window


def raster_sum(
    raster: rasterio.DatasetReader, geometry: BaseGeometry, band: int = 1
) -> float:
    """Sum values whose cell centres fall inside one geometry.

    This uses Rasterio's default geometry-mask semantics consistently for both
    calculation of proxy support and subsequent allocation.
    """
    window = geometry_window(raster, [geometry])
    values = raster.read(band, window=window)
    inside = geometry_mask(
        [geometry], values.shape, raster.window_transform(window), invert=True
    )
    return float(values[inside].sum(dtype="float64"))


def write_scaled(
    output: rasterio.DatasetWriter,
    band: int,
    reference: rasterio.DatasetReader,
    base_window: Window,
    geometry: BaseGeometry,
    total: float,
    source_band: int = 1,
) -> None:
    r"""Allocate ``total`` over a geometry in proportion to a reference band.

    If :math:`f_i` is floor area in hectare :math:`i`, the output is
    :math:`f_i T / \sum_i f_i`. Positive totals are validated against positive
    proxy support by the calling script before this function is reached.
    """
    if total == 0:
        return
    window = geometry_window(output, [geometry])
    source_window = Window(
        base_window.col_off + window.col_off,
        base_window.row_off + window.row_off,
        window.width,
        window.height,
    )
    proxy = reference.read(source_band, window=source_window)
    inside = geometry_mask(
        [geometry], proxy.shape, output.window_transform(window), invert=True
    )
    values = output.read(band, window=window)
    values[inside] = proxy[inside] * total / proxy[inside].sum(dtype="float64")
    output.write(values, band, window=window)


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
