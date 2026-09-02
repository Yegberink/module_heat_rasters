"""Executable schemas for all regionalisation inputs and outputs.

Each reader checks structural, spatial, and numeric invariants before returning
data to a calculation. Output validators additionally enforce band ordering,
units, non-negativity, and conservation identities. Assertions are intentional:
invalid throughput must stop the workflow rather than be repaired silently.

Source contracts represented here include EUBUCCO v0.2, Eurostat GISCO NUTS,
Eurostat Census 2021, GHS-POP R2023A, and ``module_euro_building_heat``.
"""

import json
from pathlib import Path
from typing import Any

import duckdb
import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import rasterio
from _eubucco import EUBUCCO_COLUMNS, EUBUCCO_SCHEMA

SECTORS = ("residential", "non_residential")
RASTER_BANDS = (*SECTORS, "total")
FLOOR_AREA_BANDS = ("residential", "commercial", "total")


def validate_shape_source(path: str | Path) -> gpd.GeoDataFrame:
    """Validate user-provided land and maritime polygons."""
    shapes = gpd.read_parquet(path)
    assert {"shape_id", "country_id", "shape_class", "geometry"} <= set(shapes)
    shapes["shape_id"] = shapes.shape_id.astype(str).str.replace(".", "-", regex=False)
    assert shapes.crs
    assert shapes.shape_id.is_unique
    assert shapes.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert shapes.shape_class.isin(["land", "maritime"]).all()
    assert shapes.geometry.is_valid.all()
    assert (~shapes.geometry.is_empty).all()
    return shapes


def validate_shapes(path: str | Path) -> gpd.GeoDataFrame:
    """Validate prepared land polygons."""
    shapes = validate_shape_source(path)
    assert shapes.shape_class.eq("land").all()
    projected = shapes.to_crs("EPSG:3035")
    assert np.isclose(
        projected.geometry.area.sum(), projected.geometry.union_all().area
    )
    return shapes


def validate_nuts3(path: str | Path) -> gpd.GeoDataFrame:
    """Validate prepared NUTS-3 polygons."""
    nuts3 = gpd.read_parquet(path)
    assert list(nuts3.columns) == ["nuts3_id", "country_id", "geometry"]
    assert nuts3.crs
    assert nuts3.nuts3_id.is_unique
    assert nuts3.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert nuts3.geometry.is_valid.all()
    assert (~nuts3.geometry.is_empty).all()
    return nuts3


def validate_nuts3_source(path: str | Path) -> gpd.GeoDataFrame:
    """Validate the GISCO NUTS-3 source."""
    nuts3 = gpd.read_file(path)
    assert {"NUTS_ID", "CNTR_CODE", "LEVL_CODE", "geometry"} <= set(nuts3)
    assert nuts3.crs
    assert nuts3.NUTS_ID.is_unique
    assert nuts3.LEVL_CODE.eq(3).all()
    assert nuts3.geometry.notna().all()
    return nuts3


def validate_census(path: str | Path, year: int) -> pd.DataFrame:
    """Validate the Eurostat dwelling floor-space table structure."""
    data = pd.read_csv(path, sep="\t", dtype=str)
    assert data.columns[0].endswith("\\TIME_PERIOD")
    dimensions = data.columns[0].removesuffix("\\TIME_PERIOD").split(",")
    assert dimensions == ["freq", "area", "n_room", "building", "unit", "geo"]
    assert sum(column.strip() == str(year) for column in data.columns) == 1
    return data


def validate_eubucco_nuts(path: str | Path) -> gpd.GeoDataFrame:
    """Validate EUBUCCO administrative-region metadata."""
    regions = gpd.read_parquet(path, columns=["region_id", "geometry"])
    assert regions.crs.to_epsg() == 3035
    assert regions.region_id.is_unique
    assert regions.region_id.str.fullmatch(r"[A-Z0-9]+").all()
    assert regions.geometry.is_valid.all()
    return regions


def validate_eubucco_stats(path: str | Path) -> gpd.GeoDataFrame:
    """Validate EUBUCCO NUTS-3 floor-area statistics."""
    columns = [
        "region_id",
        "country",
        "n",
        "floor_area_subtype_commercial",
        "floor_area_subtype_public",
        "geometry",
    ]
    stats = gpd.read_parquet(path, columns=columns)
    assert stats.crs.to_epsg() == 3035
    assert stats.region_id.is_unique
    assert stats.country.str.fullmatch(r"[A-Z]{2}").all()
    assert np.isfinite(stats[columns[2:-1]].to_numpy()).all()
    assert stats[columns[2:-1]].ge(0).all().all()
    return stats


def validate_eubucco_plan(path: str | Path) -> dict:
    """Validate an adaptive EUBUCCO acquisition manifest."""
    with open(path) as stream:
        plan = json.load(stream)
    assert list(plan) == [
        "schema_version",
        "eubucco_version",
        "requested_strategy",
        "selected_strategy",
        "regional_max_fraction",
        "regional_estimated_bytes",
        "lightweight_bytes",
        "regions",
    ]
    assert plan["schema_version"] == 1
    assert plan["eubucco_version"] == "0.2"
    assert plan["requested_strategy"] in {"auto", "regional", "lightweight"}
    assert plan["selected_strategy"] in {"regional", "lightweight"}
    assert 0 < plan["regional_max_fraction"] <= 1
    assert plan["regional_estimated_bytes"] >= 0
    assert plan["lightweight_bytes"] > 0
    assert plan["regions"]
    for nuts3, mapping in plan["regions"].items():
        assert len(nuts3) == 5
        assert list(mapping) == ["region_ids", "nuts2_ids"]
        assert mapping["region_ids"] == sorted(set(mapping["region_ids"]))
        assert mapping["nuts2_ids"] == sorted(set(mapping["nuts2_ids"]))
        assert mapping["nuts2_ids"] == sorted(
            {region[:4] for region in mapping["region_ids"]}
        )
    return plan


def validate_eubucco_partition(path: str | Path) -> None:
    """Validate one canonical local EUBUCCO NUTS-2 partition."""
    schema = pq.read_schema(path)
    assert schema.names == EUBUCCO_COLUMNS
    assert schema == EUBUCCO_SCHEMA
    valid = duckdb.connect().execute(
        """
        SELECT count(*) = count(DISTINCT id),
               coalesce(bool_and(regexp_full_match(region_id, '[A-Z0-9]{5}')), true),
               coalesce(bool_and(isfinite(floors) AND floors > 0), true),
               coalesce(bool_and(isfinite(footprint_area_m2) AND footprint_area_m2 > 0), true),
               coalesce(bool_and(isfinite(x_3035) AND isfinite(y_3035)), true)
        FROM read_parquet(?)
        """,
        [str(path)],
    ).fetchone()
    assert all(valid)


def validate_eubucco_lightweight(path: str | Path) -> None:
    """Validate the required columns of the Europe-wide lightweight parquet."""
    fields = {
        "id",
        "region_id",
        "type",
        "subtype",
        "floors",
        "footprint_area",
        "lat",
        "lon",
    }
    assert fields <= set(pq.read_schema(path).names)


def validate_eubucco_footprints(path: str | Path) -> None:
    """Validate the required columns of a regional EUBUCCO parquet."""
    fields = {"id", "region_id", "type", "subtype", "floors", "geometry"}
    assert fields <= set(pq.read_schema(path).names)


def validate_floor_area_totals(path: str | Path, nuts3_ids=None) -> pd.DataFrame:
    """Validate prepared current-NUTS-3 floor-area totals."""
    totals = pd.read_parquet(path)
    assert list(totals.columns) == [
        "nuts3_id",
        "country_id",
        "population",
        "residential_total_m2",
        "commercial_fallback_m2",
    ]
    assert totals.nuts3_id.is_unique
    if nuts3_ids is not None:
        assert set(totals.nuts3_id) == set(nuts3_ids)
    assert totals.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert np.isfinite(totals[["population", "residential_total_m2"]]).all().all()
    assert totals[["population", "residential_total_m2"]].ge(0).all().all()
    fallback = totals.commercial_fallback_m2.dropna()
    assert np.isfinite(fallback).all()
    assert fallback.ge(0).all()
    return totals


def validate_population_raster(path: str | Path, resolution: int) -> None:
    """Validate a GHSL GHS-POP Mollweide raster."""
    with rasterio.open(path) as raster:
        assert raster.count == 1
        assert raster.crs.to_string() == "ESRI:54009"
        assert np.allclose(np.abs(raster.res), resolution)
        assert np.issubdtype(np.dtype(raster.dtypes[0]), np.floating)


def validate_annual_heat_demand(path: str | Path, shape_ids: pd.Index) -> pd.DataFrame:
    """Validate the annual useful-heat output of module_euro_building_heat."""
    demand = pd.read_parquet(path)
    assert demand.index.names == ["year", "end_use", "cat_name"]
    assert set(demand.columns.astype(str)) == set(shape_ids.astype(str))
    assert np.isfinite(demand.to_numpy()).all()
    assert demand.ge(0).all().all()
    return demand


def validate_scaling_support(totals: np.ndarray, proxy_sums: np.ndarray) -> None:
    """Require a positive proxy wherever a positive total must be allocated."""
    assert np.all(proxy_sums[totals > 0] > 0)


def validate_density_raster(
    path: str | Path,
    schema: dict[str, Any],
    units: tuple[str, str, str],
    bands: tuple[str, str, str] = RASTER_BANDS,
) -> None:
    """Validate a shape-scoped three-band hectare raster."""
    with rasterio.open(path) as raster:
        assert raster.crs.to_string() == "EPSG:3035"
        assert (
            abs(raster.transform.a) == abs(raster.transform.e) == schema["cell_size_m"]
        )
        assert raster.count == 3
        assert raster.dtypes == (schema["dtype"],) * 3
        assert raster.nodatavals == (schema["nodata"],) * 3
        assert raster.descriptions == bands
        assert raster.units == units
        for _, window in raster.block_windows(1):
            values = raster.read(window=window)
            assert np.isfinite(values).all()
            assert (values >= 0).all()
            assert np.allclose(values[2], values[0] + values[1])


def validate_plot(path: str | Path) -> None:
    """Validate a non-empty PNG plot."""
    import matplotlib.image as mpimg

    assert Path(path).suffix == ".png"
    image = mpimg.imread(path)
    assert image.ndim == 3
    assert image.shape[0] > 0
    assert image.shape[1] > 0
    assert np.isfinite(image).all()


def validate_nuts3_heat_demand(path: str | Path, year: int) -> None:
    """Validate annual useful heat-demand totals at NUTS 3."""
    table = pd.read_parquet(path)
    assert list(table.columns) == [
        "year",
        "nuts3_id",
        "residential_mwh",
        "non_residential_mwh",
        "total_mwh",
    ]
    assert table.nuts3_id.is_unique
    assert table.year.eq(year).all()
    assert np.isfinite(table.iloc[:, 2:].to_numpy()).all()
    assert table.iloc[:, 2:].ge(0).all().all()
    assert np.allclose(
        table.total_mwh, table.residential_mwh + table.non_residential_mwh
    )
