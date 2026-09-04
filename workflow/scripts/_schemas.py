"""Executable schemas for all floor-area inputs and outputs.

Each reader checks structural, spatial, and numeric invariants before returning
data to a calculation. Output validators additionally enforce band ordering,
units, non-negativity, and conservation identities. Assertions are intentional:
invalid throughput must stop the workflow rather than be repaired silently.

Source contracts represented here include EUBUCCO v0.2, Eurostat GISCO NUTS,
Eurostat Census 2021, and GHS-POP R2023A.
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
import shapely
from _eubucco import EUBUCCO_COLUMNS, EUBUCCO_SCHEMA
from _microsoft import MICROSOFT_COLUMNS, MICROSOFT_SCHEMA

FLOOR_AREA_BANDS = ("residential", "commercial", "total")


def validate_shape_source(path: str | Path) -> gpd.GeoDataFrame:
    """Validate user-provided land and maritime polygons."""
    shapes = gpd.read_parquet(path)
    assert {"shape_id", "country_id", "shape_class", "geometry"} <= set(shapes)
    shapes["shape_id"] = shapes.shape_id.astype(str).str.replace(".", "-", regex=False)
    assert shapes.crs
    assert shapes.shape_id.is_unique
    assert shapes.shape_id.str.fullmatch(r"[A-Za-z0-9_-]+").all()
    assert shapes.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert shapes.shape_class.isin(["land", "maritime"]).all()
    assert shapes.geometry.is_valid.all()
    assert (~shapes.geometry.is_empty).all()
    return shapes


def validate_shapes(path: str | Path) -> gpd.GeoDataFrame:
    """Validate prepared land polygons."""
    shapes = validate_shape_source(path)
    assert shapes.shape_class.eq("land").all()
    projected = shapes.to_crs("ESRI:54009")
    assert np.isclose(
        projected.geometry.area.sum(), projected.geometry.union_all().area
    )
    return shapes


def validate_scope(path: str | Path) -> gpd.GeoDataFrame:
    """Validate the precomputed processing scope in an equal-area grid CRS."""
    scope = gpd.read_parquet(path)
    assert list(scope.columns) == ["geometry"]
    assert scope.crs.to_string() in {"EPSG:3035", "ESRI:54009"}
    assert len(scope) == 1
    assert scope.geom_type.isin(["Polygon", "MultiPolygon"]).all()
    assert scope.geometry.is_valid.all()
    assert (~scope.geometry.is_empty).all()
    return scope


def validate_nuts3(path: str | Path, country_ids=None) -> gpd.GeoDataFrame:
    """Validate prepared NUTS-3 and input-shape control regions."""
    nuts3 = gpd.read_parquet(path)
    assert list(nuts3.columns) == ["region_id", "country_id", "geometry"]
    assert nuts3.crs
    assert nuts3.region_id.is_unique
    assert nuts3.region_id.str.fullmatch(r"(?:[A-Z0-9]{5}|shape-.+)").all()
    assert nuts3.country_id.str.fullmatch(r"[A-Z]{3}").all()
    if country_ids is not None:
        assert set(nuts3.country_id) == set(country_ids)
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
        "floor_area_type_residential",
        "n_floors_0_2",
        "n_floors_2_4",
        "n_floors_4_7",
        "n_floors_7_inf",
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
    """Validate building-source precedence and acquisition selections."""
    with open(path) as stream:
        plan = json.load(stream)
    assert list(plan) == [
        "schema_version",
        "eubucco_version",
        "microsoft_release",
        "crs",
        "regions",
    ]
    assert plan["schema_version"] == 1
    assert plan["eubucco_version"] == "0.2"
    assert plan["crs"] in {"EPSG:3035", "ESRI:54009"}
    assert plan["regions"]
    for region, mapping in plan["regions"].items():
        assert region
        assert list(mapping) == [
            "eubucco_region_ids",
            "eubucco_nuts2_ids",
            "residential_source",
            "commercial_source",
            "microsoft_quadkeys",
        ]
        assert mapping["eubucco_region_ids"] == sorted(set(mapping["eubucco_region_ids"]))
        assert mapping["eubucco_nuts2_ids"] == sorted(set(mapping["eubucco_nuts2_ids"]))
        assert mapping["residential_source"] in {"eubucco", "microsoft"}
        assert mapping["commercial_source"] in {"eubucco", "microsoft"}
        assert mapping["microsoft_quadkeys"] == sorted(set(mapping["microsoft_quadkeys"]))
        assert all(
            len(key) == 9 and set(key) <= set("0123")
            for key in mapping["microsoft_quadkeys"]
        )
    return plan


def validate_microsoft_index(path: str | Path) -> pd.DataFrame:
    """Validate the columns used from Microsoft's pinned tile index."""
    links = pd.read_csv(path, dtype={"QuadKey": str})
    assert {"Location", "QuadKey", "Url"} <= set(links)
    assert links.QuadKey.str.fullmatch(r"[0-3]{9}").all()
    assert links.Url.str.startswith("https://").all()
    return links


def validate_microsoft_feature(feature: dict):
    """Normalize and validate one GeoJSONL building footprint."""
    assert "geometry" in feature
    geometry = shapely.make_valid(
        shapely.geometry.shape(feature["geometry"]),
        method="structure",
        keep_collapsed=False,
    )
    assert geometry.geom_type in {"Polygon", "MultiPolygon"}
    assert geometry.is_valid
    assert not geometry.is_empty
    return geometry


def validate_microsoft_partition(path: str | Path) -> None:
    """Validate one canonical Microsoft footprint partition."""
    assert pq.read_schema(path) == MICROSOFT_SCHEMA
    assert pq.read_schema(path).names == MICROSOFT_COLUMNS
    valid = duckdb.connect().execute(
        """
        SELECT count(*) = count(DISTINCT id),
               coalesce(bool_and(length(region_id) > 0), true),
               coalesce(bool_and(isfinite(footprint_area_m2) AND footprint_area_m2 > 0), true),
               coalesce(bool_and(isfinite(x) AND isfinite(y)), true)
        FROM read_parquet(?)
        """,
        [str(path)],
    ).fetchone()
    assert valid is not None
    assert all(valid)


def validate_floor_area_batches(path: str | Path, nuts3_ids=None) -> dict:
    """Validate deterministic NUTS-3 floor-area batch membership."""
    with open(path) as stream:
        plan = json.load(stream)
    assert list(plan) == ["schema_version", "batches"]
    assert plan["schema_version"] == 1
    assert plan["batches"]
    assert list(plan["batches"]) == [
        f"{index:03d}" for index in range(len(plan["batches"]))
    ]
    assert all(plan["batches"].values())
    assert all(regions == sorted(set(regions)) for regions in plan["batches"].values())
    batched = [region for regions in plan["batches"].values() for region in regions]
    assert len(batched) == len(set(batched))
    if nuts3_ids is not None:
        assert set(batched) == set(nuts3_ids)
    return plan


def validate_eubucco_partition(path: str | Path) -> None:
    """Validate one canonical local EUBUCCO NUTS-2 partition."""
    schema = pq.read_schema(path)
    assert schema.names == EUBUCCO_COLUMNS
    assert schema == EUBUCCO_SCHEMA
    valid = (
        duckdb.connect()
        .execute(
            """
        SELECT count(*) = count(DISTINCT id),
               coalesce(bool_and(regexp_full_match(region_id, '[A-Z0-9]{5}')), true),
               coalesce(bool_and(isfinite(floors) AND floors > 0), true),
               coalesce(bool_and(isfinite(footprint_area_m2) AND footprint_area_m2 > 0), true),
               coalesce(bool_and(isfinite(x) AND isfinite(y)), true)
        FROM read_parquet(?)
        """,
            [str(path)],
        )
        .fetchone()
    )
    assert valid is not None
    assert all(valid)


def validate_floor_area_totals(path: str | Path, nuts3_ids=None) -> pd.DataFrame:
    """Validate prepared control-region floor-area totals."""
    totals = pd.read_parquet(path)
    assert list(totals.columns) == [
        "region_id",
        "country_id",
        "population",
        "residential_total_m2",
        "commercial_fallback_m2",
    ]
    assert totals.region_id.is_unique
    if nuts3_ids is not None:
        assert set(totals.region_id) == set(nuts3_ids)
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


def validate_density_raster(
    path: str | Path,
    schema: dict[str, Any],
    units: tuple[str, str, str],
    bands: tuple[str, str, str],
) -> None:
    """Validate a shape-scoped three-band hectare raster."""
    with rasterio.open(path) as raster:
        assert raster.crs.to_string() in {"EPSG:3035", "ESRI:54009"}
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
