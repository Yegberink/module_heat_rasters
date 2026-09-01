"""Schemas for regionalisation inputs and outputs."""

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio

SECTORS = ("residential", "non_residential")
RASTER_BANDS = (*SECTORS, "total")
FLOOR_AREA_BANDS = ("residential", "commercial", "total")


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


def validate_eubucco_buildings(buildings: gpd.GeoDataFrame) -> None:
    """Validate a streamed EUBUCCO building subset."""
    assert list(buildings.columns) == ["id", "type", "subtype", "floors", "geometry"]
    assert buildings.crs.to_epsg() == 3035
    assert buildings.id.is_unique
    assert np.isfinite(buildings.floors).all()
    assert buildings.floors.gt(0).all()
    assert buildings.geometry.is_valid.all()
    assert (~buildings.geometry.is_empty).all()


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
