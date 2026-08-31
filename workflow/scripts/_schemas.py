"""Schemas for regionalisation inputs and outputs."""

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine

SECTORS = ("residential", "non_residential")
RASTER_BANDS = (*SECTORS, "total")


def validate_shapes(path: str | Path) -> gpd.GeoDataFrame:
    """Validate user polygons and return the land shapes."""
    shapes = gpd.read_parquet(path)
    assert {"shape_id", "country_id", "shape_class", "geometry"} <= set(shapes)
    shapes = shapes.loc[shapes.shape_class.eq("land")].copy()
    shapes["shape_id"] = shapes.shape_id.astype(str).str.replace(".", "-", regex=False)
    assert shapes.crs
    assert shapes.shape_id.is_unique
    assert shapes.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert shapes.geometry.is_valid.all()
    assert (~shapes.geometry.is_empty).all()
    projected = shapes.to_crs("EPSG:3035")
    assert np.isclose(
        projected.geometry.area.sum(), projected.geometry.union_all().area
    )
    return shapes


def validate_nuts3(path: str | Path) -> gpd.GeoDataFrame:
    """Validate prepared NUTS-3 polygons."""
    nuts3 = gpd.read_parquet(path)
    assert list(nuts3.columns) == ["nuts3_id", "geometry"]
    assert nuts3.crs
    assert nuts3.nuts3_id.is_unique
    assert nuts3.geometry.is_valid.all()
    assert (~nuts3.geometry.is_empty).all()
    return nuts3


def validate_reference_rasters(paths: list[str], schema: dict[str, Any]) -> None:
    """Validate the shared Hotmaps hectare grid."""
    left, bottom, right, top = schema["bounds_m"]
    transform = Affine(schema["cell_size_m"], 0, left, 0, -schema["cell_size_m"], top)
    for path in paths:
        with rasterio.open(path) as raster:
            assert raster.crs.to_string() == schema["crs"]
            assert raster.transform == transform
            assert raster.bounds == (left, bottom, right, top)
            assert (raster.width, raster.height) == (schema["width"], schema["height"])
            assert raster.count == 1
            assert raster.dtypes == (schema["dtype"],)
            assert raster.nodatavals == (schema["nodata"],)


def validate_floor_area_table(path: str | Path, nuts3_ids: pd.Index) -> pd.DataFrame:
    """Validate NUTS-3 heated gross floor-area totals."""
    table = pd.read_parquet(path).set_index("nuts3_id")
    assert list(table.columns) == ["residential_m2", "non_residential_m2", "total_m2"]
    assert table.index.is_unique
    assert set(table.index) == set(nuts3_ids)
    assert np.isfinite(table.to_numpy()).all()
    assert table.ge(0).all().all()
    assert np.allclose(table.total_m2, table.residential_m2 + table.non_residential_m2)
    return table


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
    path: str | Path, schema: dict[str, Any], units: tuple[str, str, str]
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
        assert raster.descriptions == RASTER_BANDS
        assert raster.units == units


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
