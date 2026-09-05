"""Shared floor-area control totals and building-weighted allocation.

Residential totals are reconstructed from Eurostat Census 2021 dwelling counts
by useful-floor-space class. Where countries report rooms instead of area, room
counts are converted with the configured mean area per room. Useful area is then
converted to gross floor area with the configured ratio. Building centroids
locate EUBUCCO or Microsoft building support on the hectare grid. GHS-POP is
used only to estimate dwelling totals outside Eurostat coverage.

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
import shapely
from _schemas import validate_census
from affine import Affine
from gregor.aggregate import aggregate_raster_to_polygon
from rasterio.windows import Window


def select_building_sectors(buildings, residential_type, commercial_subtypes):
    """Return residential and commercial/public building subsets."""
    return (
        buildings.loc[buildings["type"].eq(residential_type)],
        buildings.loc[buildings["subtype"].isin(commercial_subtypes)],
    )


def points_within_scope(points, scope):
    """Test centroid coordinates against a prepared scope with strict containment."""
    return shapely.contains_xy(scope, points.x, points.y)


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


def dwelling_counts(data: pd.DataFrame, settings: dict[str, Any]) -> pd.Series:
    """Return dwelling counts from the same census classes used for floor area."""
    common = data.loc[
        data.freq.eq("A") & data.building.eq("TOTAL") & data.unit.eq("NR")
    ]
    area = common.loc[
        common.n_room.eq("TOTAL") & common.area.isin(settings["floor_space_m2"])
    ].groupby("geo").value.sum(min_count=1)
    rooms = common.loc[
        common.area.eq("TOTAL") & common.n_room.isin(settings["rooms"])
    ].groupby("geo").value.sum(min_count=1)
    return area.where(area.gt(0), rooms)


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


def output_profile(bounds, settings, crs="EPSG:3035", count=3):
    """Return an equal-area raster profile aligned to the hectare grid.

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
        "count": count,
        "dtype": settings["dtype"],
        "crs": crs,
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
