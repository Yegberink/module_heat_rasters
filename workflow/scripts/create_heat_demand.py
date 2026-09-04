"""Regionalise annual useful heat demand from arbitrary shapes to hectares.

The upstream ``module_euro_building_heat`` supplies annual useful demand in TWh
by shape, end use, and category. Configured end uses and categories are mapped
to residential and non-residential sectors and converted to MWh. Demand is
split through NUTS-3 regions where available and input-shape regions elsewhere,
then allocated to hectares using the same floor-area band.

Outputs are a control-region table and a three-band equal-area raster in MWh/ha.

Sources:
    Upstream demand model: https://github.com/modelblocks-org/module_euro_building_heat
    Hectare heat-density method: https://doi.org/10.3390/en12244789
"""

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
    validate_regional_heat_demand,
    validate_scaling_support,
)

if TYPE_CHECKING:
    snakemake: Any


def shape_totals(
    demand: pd.DataFrame, year: int, settings: dict[str, Any], shape_ids: pd.Index
) -> pd.DataFrame:
    """Select district-heating end uses and aggregate TWh to MWh by sector.

    Category-to-sector assignments and included end uses are configuration, not
    implicit model choices. Multiple source categories may contribute to one
    sector and are summed for each input shape.
    """
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

# Load schema-validated inputs and reduce annual demand to the configured sectors.
validate_density_raster(
    snakemake.input.floor_area,
    snakemake.params.raster,
    ("m2/ha",) * 3,
    FLOOR_AREA_BANDS,
)
shapes = gpd.read_parquet(snakemake.input.shapes)
nuts3 = validate_nuts3(snakemake.input.nuts3)
demand = validate_annual_heat_demand(snakemake.input.annual_demand, shapes.shape_id)
totals = shape_totals(demand, year, snakemake.params.heat_demand, shapes.shape_id)

with rasterio.open(snakemake.input.floor_area) as floor_area:
    shapes = shapes.to_crs(floor_area.crs)
    nuts3 = nuts3.to_crs(floor_area.crs)

    # Split shape demand by the applicable NUTS-3 or shape control regions.
    intersections = gpd.overlay(
        shapes[["shape_id", "geometry"]],
        nuts3[["region_id", "geometry"]],
        how="intersection",
        keep_geom_type=False,
    )
    intersections = intersections.loc[intersections.geometry.area.gt(0)].copy()
    for band, sector in enumerate(SECTORS, 1):
        # Floor area is the allocation weight within each original shape.
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

    # Reaggregate the allocated pieces to complete control-region totals.
    nuts_totals = (
        intersections.groupby("region_id")[[f"{sector}_mwh" for sector in SECTORS]]
        .sum()
        .reindex(nuts3.region_id, fill_value=0)
    )
    assert np.allclose(nuts_totals.sum(), totals.sum())
    table = nuts_totals.reset_index()
    table.insert(0, "year", year)
    table["total_mwh"] = table.residential_mwh + table.non_residential_mwh
    Path(snakemake.output.regions).parent.mkdir(parents=True, exist_ok=True)
    table.to_parquet(snakemake.output.regions, index=False)

    # Allocate each regional total to hectares using the corresponding sector's
    # floor-area density while clipping the result to the requested shape scope.
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
            for region_id, geometry in zip(nuts3.region_id, geometries, strict=True):
                write_scaled(
                    output,
                    band,
                    floor_area,
                    base_window,
                    geometry,
                    nuts_totals.loc[region_id, f"{sector}_mwh"],
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

validate_regional_heat_demand(snakemake.output.regions, year)
validate_density_raster(
    snakemake.output.raster, snakemake.params.raster, ("MWh/ha",) * 3
)
