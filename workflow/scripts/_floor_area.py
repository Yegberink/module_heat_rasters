"""Shared floor-area control totals and building-weighted allocation.

Residential totals are reconstructed from Eurostat Census 2021 dwelling counts
by useful-floor-space class. Where countries report rooms instead of area, room
counts are converted with the configured mean area per room. Useful area is then
converted to gross floor area with the configured ratio. Building centroids
locate EUBUCCO or Microsoft building support on the hectare grid. GHS-POP is
used to estimate totals outside Eurostat coverage and to inform heat support.

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
from _microsoft import quadkey_polygon
from _schemas import validate_census
from affine import Affine
from gregor.aggregate import aggregate_raster_to_polygon
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.warp import reproject
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


def population_grid(source, profile, geometry, resampling, total):
    """Reproject counts, retain region-centred cells, and conserve its total."""
    population = np.zeros((profile["height"], profile["width"]), dtype=float)
    reproject(
        rasterio.band(source, 1),
        population,
        dst_transform=profile["transform"],
        dst_crs=profile["crs"],
        dst_nodata=0,
        resampling=Resampling[resampling],
    )
    population[population == source.nodata] = 0
    population[geometry_mask([geometry], population.shape, profile["transform"])] = 0
    assert np.isfinite(population).all()
    assert (population >= 0).all()
    assert population.sum() > 0 or total == 0
    if total > 0:
        population *= total / population.sum()
    assert np.isclose(population.sum(), total)
    return population


def point_grid(profile, points, values):
    """Sum point values into an aligned raster array."""
    grid = np.zeros((profile["height"], profile["width"]), dtype=float)
    if points.empty:
        return grid
    rows, columns = rasterio.transform.rowcol(
        profile["transform"], points.geometry.x, points.geometry.y
    )
    np.add.at(grid, (np.asarray(rows), np.asarray(columns)), np.asarray(values))
    return grid


def microsoft_floor_area_support(
    profile, buildings, population, sector_total, regional_population, low_quadkeys
):
    """Replace sparse Microsoft tiles and conserve one regional sector total."""
    proxy = np.zeros_like(population, dtype=float)
    if low_quadkeys:
        polygons = gpd.GeoSeries(
            [quadkey_polygon(key) for key in sorted(low_quadkeys)], crs=4326
        ).to_crs(profile["crs"])
        inside_low_tiles = geometry_mask(
            [polygons.union_all()], population.shape, profile["transform"], invert=True
        )
        assert regional_population > 0 or sector_total == 0
        if sector_total > 0:
            proxy[inside_low_tiles] = (
                population[inside_low_tiles] * sector_total / regional_population
            )

    good = buildings.loc[~buildings.quadkey.isin(low_quadkeys)].copy()
    remaining = sector_total - proxy.sum()
    support = good.footprint_area_m2.sum()
    assert remaining >= 0
    assert support > 0 or np.isclose(remaining, 0)
    good["floor_area_m2"] = (
        good.footprint_area_m2 * remaining / support if support > 0 else 0.0
    )
    assert np.isclose(good.floor_area_m2.sum() + proxy.sum(), sector_total)
    return good, proxy


def clipped_grid(grid, source_profile, profile, geometry):
    """Extract one aligned shape window and retain cells centred in its geometry."""
    bounds = rasterio.transform.array_bounds(
        profile["height"], profile["width"], profile["transform"]
    )
    raw = rasterio.windows.from_bounds(*bounds, transform=source_profile["transform"])
    window = Window(
        round(raw.col_off), round(raw.row_off), round(raw.width), round(raw.height)
    )
    clipped = grid[window.toslices()].copy()
    clipped[geometry_mask([geometry], clipped.shape, profile["transform"])] = 0
    return clipped


def add_partial(output, partial, bands=(1, 2)) -> None:
    """Add aligned floor-area or heat bands in bounded raster windows."""
    raw = rasterio.windows.from_bounds(*partial.bounds, output.transform)
    for _, window in partial.block_windows(1):
        destination = Window(
            round(raw.col_off) + window.col_off,
            round(raw.row_off) + window.row_off,
            window.width,
            window.height,
        )
        output.write(
            output.read(bands, window=destination) + partial.read(bands, window=window),
            bands,
            window=destination,
        )
