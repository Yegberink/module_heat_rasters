"""Shared floor-area calculations and population-weighted allocation.

Residential totals are reconstructed from Eurostat Census 2021 dwelling counts
by useful-floor-space class. Where countries report rooms instead of area, room
counts are converted with the configured mean area per room. Useful area is then
converted to gross floor area with the configured ratio. Building centroids
locate EUBUCCO floor area on the hectare grid; GHS-POP supplies the fallback
spatial distribution where building coverage is absent.

The use of building stock and population proxies follows the hectare-level
floor-area regionalisation approach described by Müller et al. (2019).

Sources:
    Method: https://doi.org/10.3390/en12244789
    Census definitions: https://ec.europa.eu/eurostat/cache/metadata/en/cens_21_esms.htm
    GHS-POP R2023A: https://human-settlement.emergency.copernicus.eu/documents/GHSL_Data_Package_2023.pdf
"""

import math
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from _schemas import validate_census, validate_scaling_support
from affine import Affine
from gregor.aggregate import aggregate_raster_to_polygon
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, geometry_window
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window


def census_values(path: str, year: int) -> pd.DataFrame:
    """Read one Eurostat census year into explicit dimension columns.

    Eurostat bulk TSV files encode all non-time dimensions in the first column
    and append observation flags to values. Splitting the series key and parsing
    only the leading numeric token preserves unavailable observations as NaN.
    """
    data = validate_census(path, year)
    series_key = data.columns[0]
    dimensions = series_key.removesuffix("\\TIME_PERIOD").split(",")
    year_column = next(column for column in data if column.strip() == str(year))
    data[dimensions] = data.pop(series_key).str.split(",", expand=True)
    data["value"] = pd.to_numeric(
        data.pop(year_column).str.strip().str.split().str[0], errors="coerce"
    )
    return data


def residential_floor_area(data: pd.DataFrame, settings: dict[str, Any]) -> pd.Series:
    """Calculate NUTS-3 gross residential floor area in square metres.

    Dwelling counts are multiplied by representative areas for their reported
    floor-space classes. If that estimate is absent or zero, room-class counts
    are multiplied by representative room counts and ``floor_area_per_room_m2``.
    The selected useful-area estimate is finally multiplied by
    ``useful_to_gross_ratio``. All class representatives and conversion factors
    are explicit assumptions in ``config/config.yaml``.
    """
    common = data.loc[
        data.freq.eq("A") & data.building.eq("TOTAL") & data.unit.eq("NR")
    ]
    area = (
        common.loc[
            common.n_room.eq("TOTAL") & common.area.isin(settings["floor_space_m2"])
        ]
        .pivot_table(index="geo", columns="area", values="value", aggfunc="sum")
        .mul(pd.Series(settings["floor_space_m2"]))
        .sum(axis=1, min_count=1)
    )
    rooms = (
        common.loc[common.area.eq("TOTAL") & common.n_room.isin(settings["rooms"])]
        .pivot_table(index="geo", columns="n_room", values="value", aggfunc="sum")
        .mul(pd.Series(settings["rooms"]))
        .sum(axis=1, min_count=1)
        .mul(settings["floor_area_per_room_m2"])
    )
    return area.where(area.gt(0), rooms).mul(settings["useful_to_gross_ratio"])


def population_sums(population, polygons: gpd.GeoDataFrame) -> pd.Series:
    """Aggregate GHS-POP counts to polygons through bounded Gregor calls.

    Each polygon is reprojected to the population raster CRS and evaluated on a
    clipped raster window. This preserves the source population-count semantics
    while avoiding a Europe-wide in-memory aggregation.
    """
    values = []
    for geometry in polygons.geometry:
        projected = gpd.GeoSeries([geometry], crs=polygons.crs).to_crs(
            population.rio.crs
        )
        window = population.rio.clip_box(*projected.total_bounds)
        values.append(
            aggregate_raster_to_polygon(window, projected, stats="sum")["sum"].iloc[0]
        )
    return pd.Series(values, index=polygons.index, dtype=float)


def output_profile(bounds, settings):
    """Return an EPSG:3035 raster profile aligned to the hectare grid.

    Bounds are rounded outward to exact multiples of ``cell_size_m``. Every
    partial raster therefore has cell boundaries aligned with the final raster
    and can be merged by direct addition.
    """
    cell = settings["cell_size_m"]
    left = math.floor(bounds[0] / cell) * cell
    bottom = math.floor(bounds[1] / cell) * cell
    right = math.ceil(bounds[2] / cell) * cell
    top = math.ceil(bounds[3] / cell) * cell
    return {
        "driver": "GTiff",
        "width": round((right - left) / cell),
        "height": round((top - bottom) / cell),
        "count": 3,
        "dtype": settings["dtype"],
        "crs": "EPSG:3035",
        "transform": Affine(cell, 0, left, 0, -cell, top),
        "nodata": settings["nodata"],
        "compress": settings["compression"],
        "tiled": True,
        "blockxsize": settings["block_size"],
        "blockysize": settings["block_size"],
    }


def write_points(output, band, points, values) -> None:
    """Sum building floor areas into cells containing their centroids.

    ``numpy.add.at`` is used because many buildings may map to the same cell;
    ordinary indexed assignment would overwrite repeated cell indices.
    """
    if points.empty:
        return
    rows, columns = rasterio.transform.rowcol(
        output.transform, points.geometry.x, points.geometry.y
    )
    rows, columns, values = map(np.asarray, (rows, columns, values))
    inside = (
        (rows >= 0) & (rows < output.height) & (columns >= 0) & (columns < output.width)
    )
    raster = output.read(band)
    np.add.at(raster, (rows[inside], columns[inside]), values[inside])
    output.write(raster, band)


def write_population(output, population, band, geometry, total, support) -> None:
    """Allocate a regional total to cells in proportion to GHS-POP.

    For cell population :math:`p_i` and regional support :math:`P`, the written
    value is :math:`p_i T / P`, where :math:`T` is the regional floor-area total.
    The scaling-support schema requires positive population whenever ``T > 0``.
    """
    if total == 0:
        return
    validate_scaling_support(np.array([total]), np.array([support]))
    window = geometry_window(output, [geometry])
    weights = population.read(1, window=window, masked=True).filled(0)
    inside = geometry_mask(
        [geometry], weights.shape, output.window_transform(window), invert=True
    )
    values = output.read(band, window=window)
    values[inside] += weights[inside] * total / support
    output.write(values, band, window=window)


def gridded_population_sum(source, geometry, settings) -> float:
    """Sum population after conservative reprojection to the hectare grid.

    ``Resampling.sum`` retains population counts when moving from the native
    Mollweide grid to EPSG:3035. The complete region, rather than its clipped
    shape intersection, provides the denominator for partial-shape allocation.
    """
    profile = output_profile(geometry.bounds, settings)
    with WarpedVRT(
        source,
        crs=profile["crs"],
        transform=profile["transform"],
        width=profile["width"],
        height=profile["height"],
        nodata=0,
        resampling=Resampling.sum,
    ) as population:
        values = population.read(1, masked=True).filled(0)
        inside = geometry_mask(
            [geometry], values.shape, population.transform, invert=True
        )
    return float(values[inside].sum(dtype="float64"))


def add_partial(output, partial) -> None:
    """Add one aligned NUTS-3 partial's sector bands to the final raster.

    Only residential and commercial bands are merged; the total band is derived
    once after all partials have been added.
    """
    raw = rasterio.windows.from_bounds(*partial.bounds, output.transform)
    window = Window(
        round(raw.col_off), round(raw.row_off), round(raw.width), round(raw.height)
    )
    output.write(
        output.read((1, 2), window=window) + partial.read((1, 2)),
        (1, 2),
        window=window,
    )
