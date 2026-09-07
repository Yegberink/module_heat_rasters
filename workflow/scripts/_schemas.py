"""Executable schemas for all floor-area and heat-support inputs and outputs.

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
from _microsoft import (
    MICROSOFT_COLUMNS,
    MICROSOFT_SCHEMA,
    MICROSOFT_TILE_STATISTICS_COLUMNS,
    MICROSOFT_TILE_STATISTICS_SCHEMA,
    MICROSOFT_TOTALS_SCHEMA,
)

FLOOR_AREA_BANDS = ("residential", "commercial", "total")
SPACE_HEAT_WEIGHT_BANDS = ("residential_space_heat_weight",)
SUPPORT_BANDS = {
    "floor_area": FLOOR_AREA_BANDS[:2],
    "residential_full": (
        "residential",
        "population",
        "sv_valid_floor_area",
        "sv_weighted_floor_area",
    ),
    "residential_scoped": (
        "population",
        "sv_valid_floor_area",
        "sv_weighted_floor_area",
    ),
}
SUPPORT_UNITS = {
    "floor_area": ("m2/ha", "m2/ha"),
    "residential_full": ("m2/ha", "people/ha", "m2/ha", "m2/ha * sv_power"),
    "residential_scoped": ("people/ha", "m2/ha", "m2/ha * sv_power"),
}


def validate_microsoft_totals(path):
    """Read regional footprint sums, including the typed empty-source table."""
    assert pq.read_schema(path) == MICROSOFT_TOTALS_SCHEMA
    totals = pd.read_parquet(path)
    assert totals.region_id.is_unique
    assert totals.region_id.str.len().gt(0).all()
    assert np.isfinite(totals.footprint_area_m2).all()
    assert totals.footprint_area_m2.ge(0).all()
    return totals


def validate_support_summary(path, region_ids=None):
    """Read one row per complete region with conserved support and provenance."""
    summary = pd.read_parquet(path)
    assert list(summary) == [
        "region_id",
        "country_id",
        "residential_source",
        "commercial_source",
        "population",
        "residential_floor_area_m2",
        "commercial_floor_area_m2",
        "valid_floor_area_m2",
        "weighted_sv_power",
    ]
    assert summary.region_id.is_unique
    if region_ids is not None:
        assert set(summary.region_id) == set(region_ids)
    assert summary.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert (
        summary[["residential_source", "commercial_source"]]
        .isin(["eubucco", "microsoft"])
        .all()
        .all()
    )
    values = summary.iloc[:, 4:]
    assert np.isfinite(values).all().all()
    assert values.ge(0).all().all()
    assert (
        summary.valid_floor_area_m2.le(summary.residential_floor_area_m2)
        | np.isclose(summary.valid_floor_area_m2, summary.residential_floor_area_m2)
    ).all()
    assert (
        summary.loc[
            summary.residential_source.eq("microsoft"),
            ["valid_floor_area_m2", "weighted_sv_power"],
        ]
        .eq(0)
        .all()
        .all()
    )
    return summary


def validate_support_batch(directory, region_ids):
    """Require exactly the declared regions and all three raster intermediates."""
    directory = Path(directory)
    assert {
        path.name for path in directory.iterdir() if not path.name.startswith(".")
    } == set(region_ids) | {"summary.parquet"}
    for region_id in region_ids:
        assert {path.name for path in (directory / region_id).iterdir()} == {
            f"{kind}.tif" for kind in SUPPORT_BANDS
        }
    return validate_support_summary(directory / "summary.parquet", region_ids)


def read_support_raster(path, settings, kind, region_id):
    """Validate and load a persistent intermediate on the common hectare grid."""
    with rasterio.open(path) as raster:
        assert raster.crs.to_string() in {"EPSG:3035", "ESRI:54009"}
        cell = settings["cell_size_m"]
        assert raster.transform.a == cell
        assert raster.transform.e == -cell
        assert raster.transform.b == raster.transform.d == 0
        assert np.allclose(
            np.array([raster.transform.c, raster.transform.f]) / cell,
            np.round(np.array([raster.transform.c, raster.transform.f]) / cell),
        )
        assert raster.count == len(SUPPORT_BANDS[kind])
        assert raster.descriptions == SUPPORT_BANDS[kind]
        assert raster.units == SUPPORT_UNITS[kind]
        assert raster.dtypes == (settings["dtype"],) * raster.count
        assert raster.nodatavals == (settings["nodata"],) * raster.count
        assert raster.tags()["region_id"] == region_id
        values = raster.read()
        assert np.isfinite(values).all()
        assert (values >= 0).all()
        return values, raster.profile


def validate_region_support(directory, settings, summary):
    """Validate spatial alignment and complete-region conservation at I/O boundaries."""
    directory = Path(directory)
    floor, profile = read_support_raster(
        directory / "floor_area.tif", settings, "floor_area", summary.name
    )
    full, full_profile = read_support_raster(
        directory / "residential_full.tif", settings, "residential_full", summary.name
    )
    scoped, scoped_profile = read_support_raster(
        directory / "residential_scoped.tif",
        settings,
        "residential_scoped",
        summary.name,
    )
    for key in ("crs", "transform", "height", "width"):
        assert profile[key] == scoped_profile[key]
    assert profile["crs"] == full_profile["crs"]
    full_bounds = rasterio.transform.array_bounds(
        full_profile["height"], full_profile["width"], full_profile["transform"]
    )
    bounds = rasterio.transform.array_bounds(
        profile["height"], profile["width"], profile["transform"]
    )
    assert bounds[0] >= full_bounds[0]
    assert bounds[1] >= full_bounds[1]
    assert bounds[2] <= full_bounds[2]
    assert bounds[3] <= full_bounds[3]
    assert np.allclose(
        full.sum(axis=(1, 2)),
        [
            summary.residential_floor_area_m2,
            summary.population,
            summary.valid_floor_area_m2,
            summary.weighted_sv_power,
        ],
    )
    for area, valid in ((full[0], full[2]), (floor[0], scoped[1])):
        assert ((valid <= area) | np.isclose(valid, area)).all()
    assert (
        np.less_equal(scoped.sum(axis=(1, 2)), full[1:].sum(axis=(1, 2)))
        | np.isclose(scoped.sum(axis=(1, 2)), full[1:].sum(axis=(1, 2)))
    ).all()
    for value, total in zip(
        floor.sum(axis=(1, 2)),
        [summary.residential_floor_area_m2, summary.commercial_floor_area_m2],
        strict=True,
    ):
        assert value <= total or np.isclose(value, total)
    return floor, full, scoped, profile


def validate_raster_alignment(floor_path, heat_path, profile):
    """Require paired regional outputs on the final grid and within its bounds."""
    with rasterio.open(floor_path) as floor, rasterio.open(heat_path) as heat:
        assert floor.crs == heat.crs == profile["crs"]
        assert floor.transform == heat.transform
        assert floor.shape == heat.shape
        window = rasterio.windows.from_bounds(*floor.bounds, profile["transform"])
        offsets = [window.col_off, window.row_off, window.width, window.height]
        assert np.allclose(offsets, np.round(offsets))
        assert window.col_off >= 0
        assert window.row_off >= 0
        assert window.col_off + window.width <= profile["width"]
        assert window.row_off + window.height <= profile["height"]


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


def validate_eubucco_plan(path: str | Path) -> dict:
    """Validate building-source precedence and acquisition selections."""
    with open(path) as stream:
        plan = json.load(stream)
    assert list(plan) == [
        "schema_version",
        "eubucco_version",
        "eubucco_source",
        "microsoft_release",
        "crs",
        "regions",
    ]
    assert plan["schema_version"] == 2
    assert plan["eubucco_version"] == "0.2"
    assert plan["eubucco_source"] in {"lightweight", "full"}
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
        assert mapping["eubucco_region_ids"] == sorted(
            set(mapping["eubucco_region_ids"])
        )
        assert mapping["eubucco_nuts2_ids"] == sorted(set(mapping["eubucco_nuts2_ids"]))
        assert mapping["residential_source"] in {"eubucco", "microsoft"}
        assert mapping["commercial_source"] in {"eubucco", "microsoft"}
        assert mapping["microsoft_quadkeys"] == sorted(
            set(mapping["microsoft_quadkeys"])
        )
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
    valid = (
        duckdb.connect()
        .execute(
            """
        SELECT count(*) = count(DISTINCT id),
               coalesce(bool_and(regexp_full_match(quadkey, '[0-3]{9}')), true),
               coalesce(bool_and(length(region_id) > 0), true),
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


def validate_microsoft_tile_statistics(
    path: str | Path, planned_quadkeys=None
) -> pd.DataFrame:
    """Validate raw Microsoft feature counts for every planned quadkey."""
    assert pq.read_schema(path) == MICROSOFT_TILE_STATISTICS_SCHEMA
    statistics = pd.read_parquet(path)
    assert list(statistics) == MICROSOFT_TILE_STATISTICS_COLUMNS
    assert statistics.quadkey.is_unique
    assert statistics.quadkey.str.fullmatch(r"[0-3]{9}").all()
    assert statistics.building_count.ge(0).all()
    if planned_quadkeys is not None:
        assert set(statistics.quadkey) == set(planned_quadkeys)
    return statistics


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


def validate_eubucco_partition(path: str | Path, source=None) -> None:
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
               coalesce(bool_and(footprint_perimeter_m IS NULL OR
                                 (isfinite(footprint_perimeter_m) AND footprint_perimeter_m > 0)), true),
               coalesce(bool_and(isfinite(x) AND isfinite(y)), true)
        FROM read_parquet(?)
        """,
            [str(path)],
        )
        .fetchone()
    )
    assert valid is not None
    assert all(valid)
    if source == "full":
        assert duckdb.connect().execute(
            "SELECT count(*) = count(footprint_perimeter_m) FROM read_parquet(?)",
            [str(path)],
        ).fetchone() == (True,)


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


def validate_nuts3_building_age(path: str | Path, nuts3_ids=None) -> pd.DataFrame:
    """Validate centred NUTS-3 construction-age corrections."""
    age = pd.read_parquet(path)
    assert list(age.columns) == [
        "region_id",
        "country_id",
        "age_factor_raw",
        "age_factor",
        "age_data_available",
        "known_dwellings",
        "total_dwellings",
        "coverage_fraction",
    ]
    assert age.region_id.is_unique
    if nuts3_ids is not None:
        assert set(age.region_id) == set(nuts3_ids)
    assert age.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert age.age_data_available.dtype == bool
    assert (
        np.isfinite(
            age[
                [
                    "age_factor",
                    "known_dwellings",
                    "total_dwellings",
                    "coverage_fraction",
                ]
            ]
        )
        .all()
        .all()
    )
    assert age.age_factor.gt(0).all()
    assert (
        age[["known_dwellings", "total_dwellings", "coverage_fraction"]]
        .ge(0)
        .all()
        .all()
    )
    assert age.age_factor_raw.notna().eq(age.age_data_available).all()
    assert age.loc[~age.age_data_available, "age_factor"].eq(1).all()
    return age


def validate_sv_statistics(path: str | Path, country_ids=None) -> pd.DataFrame:
    """Validate country compactness normalisers."""
    statistics = pd.read_parquet(path)
    assert list(statistics.columns) == [
        "country_id",
        "valid_floor_area_m2",
        "weighted_sv_power",
        "sv_power_reference",
    ]
    assert statistics.country_id.is_unique
    if country_ids is not None:
        assert set(statistics.country_id) == set(country_ids)
    assert statistics.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert np.isfinite(statistics.iloc[:, 1:]).all().all()
    assert statistics[["valid_floor_area_m2", "weighted_sv_power"]].ge(0).all().all()
    assert statistics.sv_power_reference.gt(0).all()
    return statistics


def validate_space_heat_diagnostics(path: str | Path, nuts3_ids=None) -> pd.DataFrame:
    """Validate transparent regional source and correction diagnostics."""
    diagnostics = pd.read_parquet(path)
    assert list(diagnostics.columns) == [
        "country_id",
        "region_id",
        "residential_floor_area_m2",
        "residential_source",
        "sv_valid_floor_area_fraction",
        "age_data_available",
        "age_coverage_fraction",
        "raw_age_factor",
        "normalised_age_factor",
        "raw_heat_weight",
    ]
    assert diagnostics.region_id.is_unique
    if nuts3_ids is not None:
        assert set(diagnostics.region_id) == set(nuts3_ids)
    assert diagnostics.country_id.str.fullmatch(r"[A-Z]{3}").all()
    assert diagnostics.residential_source.isin(["eubucco", "microsoft"]).all()
    finite = diagnostics.drop(columns=["raw_age_factor"])
    numeric = finite.select_dtypes(include=[np.number])
    assert np.isfinite(numeric).all().all()
    assert numeric.ge(0).all().all()
    assert (
        diagnostics.sv_valid_floor_area_fraction.le(1)
        | np.isclose(diagnostics.sv_valid_floor_area_fraction, 1)
    ).all()
    assert diagnostics.raw_age_factor.notna().eq(diagnostics.age_data_available).all()
    return diagnostics


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


def validate_space_heat_weight_raster(path: str | Path, schema: dict[str, Any]) -> None:
    """Validate a shape-scoped single-band non-negative heat-support raster."""
    with rasterio.open(path) as raster:
        assert raster.crs.to_string() in {"EPSG:3035", "ESRI:54009"}
        assert (
            abs(raster.transform.a) == abs(raster.transform.e) == schema["cell_size_m"]
        )
        assert raster.count == 1
        assert raster.dtypes == (schema["dtype"],)
        assert raster.nodatavals == (schema["nodata"],)
        assert raster.descriptions == SPACE_HEAT_WEIGHT_BANDS
        assert raster.units == ("weighted_m2/ha",)
        for _, window in raster.block_windows(1):
            values = raster.read(1, window=window)
            assert np.isfinite(values).all()
            assert (values >= 0).all()


def validate_plot(path: str | Path) -> None:
    """Validate a non-empty PNG plot."""
    import matplotlib.image as mpimg

    assert Path(path).suffix == ".png"
    image = mpimg.imread(path)
    assert image.ndim == 3
    assert image.shape[0] > 0
    assert image.shape[1] > 0
    assert np.isfinite(image).all()


def validate_weight_batch(directory, region_ids):
    """Require every declared regional weight raster and its diagnostic row."""
    directory = Path(directory)
    assert {
        path.name for path in directory.iterdir() if not path.name.startswith(".")
    } == {f"{region}.tif" for region in region_ids} | {"diagnostics.parquet"}
    return validate_space_heat_diagnostics(
        directory / "diagnostics.parquet", region_ids
    )
