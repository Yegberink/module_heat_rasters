"""Validate external data once, at download or user-input ingestion.

Generated tables and rasters are trusted and read directly by downstream jobs.
The contracts below describe only fields consumed by the workflow.
"""

import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import rasterio
import shapely


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
    # Overlapping land polygons would count the same floor area more than once.
    land = shapes.loc[shapes.shape_class.eq("land")].to_crs("ESRI:54009")
    assert not land.empty
    assert np.isclose(land.geometry.area.sum(), land.geometry.union_all().area)
    return shapes


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


def validate_building_age_census(path: str | Path, year: int) -> pd.DataFrame:
    """Validate the Eurostat NUTS-3 dwelling construction-period table."""
    data = pd.read_csv(path, sep="\t", dtype=str)
    assert data.columns[0].endswith("\\TIME_PERIOD")
    dimensions = data.columns[0].removesuffix("\\TIME_PERIOD").split(",")
    assert dimensions == ["freq", "housing", "y_const", "unit", "geo"]
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


def validate_eubucco_source(path: str | Path, source: str) -> None:
    """Validate fields consumed from an EUBUCCO distribution."""
    schema = pq.read_schema(path)
    common = {"id", "region_id", "type", "subtype", "floors", "height"}
    required = (
        common | {"footprint_area", "lon", "lat"}
        if source == "lightweight"
        else common | {"geometry"}
    )
    assert required <= set(schema.names)
    if source == "full":
        geo = json.loads(schema.metadata[b"geo"])
        assert geo["primary_column"] == "geometry"
        assert geo["columns"]["geometry"]["crs"]["id"] == {
            "authority": "EPSG",
            "code": 3035,
        }


def validate_population_raster(path: str | Path, resolution: int) -> None:
    """Validate a GHSL GHS-POP Mollweide raster."""
    with rasterio.open(path) as raster:
        assert raster.count == 1
        assert raster.crs.to_string() == "ESRI:54009"
        assert np.allclose(np.abs(raster.res), resolution)
        assert np.issubdtype(np.dtype(raster.dtypes[0]), np.floating)
