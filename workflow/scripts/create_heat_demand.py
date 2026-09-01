"""Regionalise annual useful heat demand through NUTS 3 to hectares."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from _raster import (
    create_output,
    finish_raster,
    raster_sum,
    scope_geometry,
    write_scaled,
)
from _schemas import (
    FLOOR_AREA_BANDS,
    RASTER_BANDS,
    SECTORS,
    validate_annual_heat_demand,
    validate_density_raster,
    validate_nuts3,
    validate_nuts3_heat_demand,
    validate_scaling_support,
    validate_shapes,
)

if TYPE_CHECKING:
    snakemake: Any


def shape_totals(
    demand: pd.DataFrame, year: int, settings: dict[str, Any], shape_ids: pd.Index
) -> pd.DataFrame:
    """Select district-heating end uses and convert TWh to MWh by sector."""
    selected = demand.loc[
        (demand.index.get_level_values("year") == year)
        & demand.index.get_level_values("end_use").isin(settings["end_uses"])
    ]
    categories = selected.groupby(level="cat_name").sum()
    assert set(settings["categories"]) <= set(categories.index)
    totals = pd.DataFrame(0.0, index=shape_ids, columns=SECTORS)
    for category, sector in settings["categories"].items():
        totals[sector] += categories.loc[category].reindex(shape_ids).mul(1e6)
    return totals


sys.stderr = open(snakemake.log[0], "w")
year = int(snakemake.wildcards.year)
validate_density_raster(
    snakemake.input.floor_area,
    snakemake.params.raster,
    ("m2/ha",) * 3,
    FLOOR_AREA_BANDS,
)
shapes = validate_shapes(snakemake.input.shapes)
nuts3 = validate_nuts3(snakemake.input.nuts3)
demand = validate_annual_heat_demand(snakemake.input.annual_demand, shapes.shape_id)
totals = shape_totals(demand, year, snakemake.params.heat_demand, shapes.shape_id)

with rasterio.open(snakemake.input.floor_area) as floor_area:
    shapes = shapes.to_crs(floor_area.crs)
    nuts3 = nuts3.to_crs(floor_area.crs)
    intersections = gpd.overlay(
        shapes[["shape_id", "geometry"]],
        nuts3[["nuts3_id", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    intersections = intersections.loc[intersections.geometry.area.gt(0)].copy()
    for band, sector in enumerate(SECTORS, 1):
        intersections[sector] = intersections.geometry.map(
            lambda geometry: raster_sum(floor_area, geometry, band)
        )
        support = intersections.groupby("shape_id")[sector].sum().reindex(totals.index)
        validate_scaling_support(totals[sector].to_numpy(), support.to_numpy())
        intersections[f"{sector}_mwh"] = (
            intersections[sector]
            / intersections.shape_id.map(support)
            * intersections.shape_id.map(totals[sector])
        )

    nuts_totals = (
        intersections.groupby("nuts3_id")[[f"{sector}_mwh" for sector in SECTORS]]
        .sum()
        .reindex(nuts3.nuts3_id, fill_value=0)
    )
    assert np.allclose(nuts_totals.sum(), totals.sum())
    table = nuts_totals.reset_index()
    table.insert(0, "year", year)
    table["total_mwh"] = table.residential_mwh + table.non_residential_mwh
    Path(snakemake.output.nuts3).parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(snakemake.output.nuts3, index=False)

    scope = scope_geometry(shapes, floor_area.crs)
    geometries = nuts3.geometry.intersection(scope)
    for band, sector in enumerate(SECTORS, 1):
        support = geometries.map(
            lambda geometry: raster_sum(floor_area, geometry, band)
        )
        validate_scaling_support(
            nuts_totals[f"{sector}_mwh"].to_numpy(), support.to_numpy()
        )
    output, base_window = create_output(
        snakemake.output.raster,
        floor_area,
        shapes.total_bounds,
        snakemake.params.raster,
    )
    with output:
        for band, sector in enumerate(SECTORS, 1):
            for nuts3_id, geometry in zip(nuts3.nuts3_id, geometries, strict=True):
                write_scaled(
                    output,
                    band,
                    floor_area,
                    base_window,
                    geometry,
                    nuts_totals.loc[nuts3_id, f"{sector}_mwh"],
                    band,
                )
        finish_raster(
            output,
            RASTER_BANDS,
            ("MWh/ha",) * 3,
            {
                "demand_year": year,
                "floor_area_reference_year": snakemake.params.floor_area_reference_year,
                "energy": "useful",
                "regionalisation": "floor_area_density",
            },
        )

validate_nuts3_heat_demand(snakemake.output.nuts3, year)
validate_density_raster(
    snakemake.output.raster, snakemake.params.raster, ("MWh/ha",) * 3
)
