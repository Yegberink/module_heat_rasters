"""Regionalise floor-area totals with EUBUCCO-first building support.

Each complete control region and sector uses one source. EUBUCCO floor area is
preferred; Microsoft footprint area is the fallback weight. The requested
shape receives only the share represented by building centroids and population
cell centres inside it.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import rasterio
import shapely
from _eubucco import EUBUCCO_COLUMNS, eubucco_batch_filter
from _floor_area import (
    clipped_grid,
    microsoft_floor_area_support,
    output_profile,
    point_grid,
    points_within_scope,
    population_grid,
    select_building_sectors,
)
from _microsoft import low_coverage_quadkeys
from _raster import write_raster
from _schemas import (
    SUPPORT_BANDS,
    SUPPORT_UNITS,
    validate_eubucco_plan,
    validate_floor_area_batches,
    validate_floor_area_totals,
    validate_microsoft_tile_statistics,
    validate_nuts3,
    validate_population_raster,
    validate_region_support,
    validate_scope,
    validate_support_batch,
)
from _space_heat_weight import surface_to_volume_ratio, surface_volume_power

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
eubucco_settings = snakemake.params.eubucco
microsoft_settings = snakemake.params.microsoft
plan = validate_eubucco_plan(snakemake.input.plan)
batch_plan = validate_floor_area_batches(snakemake.input.batches, plan["regions"])
batch_regions = batch_plan["batches"][snakemake.wildcards.batch]
regions = (
    validate_nuts3(snakemake.input.nuts3).set_index("region_id").loc[batch_regions]
)
scope = validate_scope(snakemake.input.scope).geometry.item()
shapely.prepare(scope)
totals = validate_floor_area_totals(snakemake.input.totals, plan["regions"]).set_index(
    "region_id"
)
planned_quadkeys = {
    key for region in plan["regions"].values() for key in region["microsoft_quadkeys"]
}
statistics = validate_microsoft_tile_statistics(
    snakemake.input.microsoft_statistics, planned_quadkeys
)
low_quadkeys = low_coverage_quadkeys(
    statistics, microsoft_settings["minimum_building_count"]
)
validate_population_raster(
    snakemake.input.population, snakemake.params.population["resolution"]
)
population_source = rasterio.open(snakemake.input.population)

legacy_ids = sorted(
    {
        legacy
        for region_id in batch_regions
        for legacy in plan["regions"][region_id]["eubucco_region_ids"]
    }
)
eubucco = (
    ds.dataset(snakemake.input.eubucco, format="parquet")
    .to_table(
        columns=EUBUCCO_COLUMNS[1:],
        filter=eubucco_batch_filter(legacy_ids, regions.total_bounds),
    )
    .to_pandas(categories=["region_id", "type", "subtype"])
)
eubucco = gpd.GeoDataFrame(
    eubucco, geometry=gpd.points_from_xy(eubucco.x, eubucco.y, crs=regions.crs)
)
eubucco["floor_area_m2"] = eubucco.footprint_area_m2 * eubucco.floors

microsoft = (
    ds.dataset(snakemake.input.microsoft, format="parquet")
    .to_table(filter=ds.field("region_id").isin(batch_regions))
    .to_pandas()
)
microsoft = gpd.GeoDataFrame(
    microsoft, geometry=gpd.points_from_xy(microsoft.x, microsoft.y, crs=regions.crs)
)
output_directory = Path(snakemake.output.partials)
output_directory.mkdir(parents=True, exist_ok=True)
summary_rows = []

for region_id, region in regions.iterrows():
    clipped = region.geometry.intersection(scope)
    region_totals = totals.loc[region_id]
    legacy = plan["regions"][region_id]["eubucco_region_ids"]
    selected = eubucco.loc[
        eubucco.region_id.isin(legacy) & eubucco.geometry.within(region.geometry)
    ]
    residential, commercial = select_building_sectors(
        selected,
        eubucco_settings["residential_type"],
        eubucco_settings["commercial_subtypes"],
    )
    fallback = microsoft.loc[microsoft.region_id.eq(region_id)]
    full_profile = output_profile(
        region.geometry.bounds, snakemake.params.raster, regions.crs
    )
    region_low_quadkeys = low_quadkeys & set(
        plan["regions"][region_id]["microsoft_quadkeys"]
    )
    population = population_grid(
        population_source,
        full_profile,
        region.geometry,
        snakemake.params.population_resampling,
        region_totals.population,
    )

    if plan["regions"][region_id]["residential_source"] == "eubucco":
        support = residential.floor_area_m2.sum()
        assert support > 0
        residential = residential.copy()
        residential["floor_area_m2"] *= region_totals.residential_total_m2 / support
        residential_proxy = np.zeros_like(population)
    else:
        residential, residential_proxy = microsoft_floor_area_support(
            full_profile,
            fallback,
            population,
            region_totals.residential_total_m2,
            region_totals.population,
            region_low_quadkeys,
        )

    if plan["regions"][region_id]["commercial_source"] == "eubucco":
        assert not commercial.empty
        commercial_proxy = np.zeros_like(population)
    else:
        assert np.isfinite(region_totals.commercial_fallback_m2)
        commercial, commercial_proxy = microsoft_floor_area_support(
            full_profile,
            fallback,
            population,
            region_totals.commercial_fallback_m2,
            region_totals.population,
            region_low_quadkeys,
        )

    # Keep additive compactness statistics before country centring. Missing
    # observations and Microsoft support contribute to F but not V or Q.
    if plan["regions"][region_id]["residential_source"] == "eubucco":
        settings = snakemake.params.surface_volume
        ratio = surface_to_volume_ratio(
            residential.footprint_area_m2,
            residential.height_m,
            residential.footprint_perimeter_m,
            method=settings["method"],
        )
        power = surface_volume_power(ratio, settings["elasticity"])
        valid = np.isfinite(power)
        residential["valid_area"] = np.where(valid, residential.floor_area_m2, 0.0)
        residential["weighted_power"] = np.where(
            valid, residential.floor_area_m2 * power, 0.0
        )
    else:
        residential["valid_area"] = 0.0
        residential["weighted_power"] = 0.0

    full_floor = (
        point_grid(full_profile, residential, residential.floor_area_m2)
        + residential_proxy
    )
    full_valid = point_grid(full_profile, residential, residential.valid_area)
    full_power = point_grid(full_profile, residential, residential.weighted_power)
    profile = output_profile(clipped.bounds, snakemake.params.raster, regions.crs)
    inside = residential.loc[points_within_scope(residential, scope)]
    commercial_inside = commercial.loc[points_within_scope(commercial, scope)]
    floor = (
        point_grid(profile, inside, inside.floor_area_m2)
        + clipped_grid(residential_proxy, full_profile, profile, clipped),
        point_grid(profile, commercial_inside, commercial_inside.floor_area_m2)
        + clipped_grid(commercial_proxy, full_profile, profile, clipped),
    )
    scoped = (
        clipped_grid(population, full_profile, profile, clipped),
        point_grid(profile, inside, inside.valid_area),
        point_grid(profile, inside, inside.weighted_power),
    )
    tags = {
        "region_id": region_id,
        "residential_source": plan["regions"][region_id]["residential_source"],
        "commercial_source": plan["regions"][region_id]["commercial_source"],
        "surface_volume_method": snakemake.params.surface_volume["method"],
        "surface_volume_elasticity": snakemake.params.surface_volume["elasticity"],
    }
    for kind, values, grid in (
        ("floor_area", floor, profile),
        (
            "residential_full",
            (full_floor, population, full_valid, full_power),
            full_profile,
        ),
        ("residential_scoped", scoped, profile),
    ):
        write_raster(
            output_directory / region_id / f"{kind}.tif",
            grid,
            values,
            SUPPORT_BANDS[kind],
            SUPPORT_UNITS[kind],
            tags,
        )
    summary_rows.append(
        {
            "region_id": region_id,
            "country_id": region.country_id,
            "residential_source": tags["residential_source"],
            "commercial_source": tags["commercial_source"],
            "population": region_totals.population,
            "residential_floor_area_m2": region_totals.residential_total_m2,
            "commercial_floor_area_m2": commercial.floor_area_m2.sum()
            + commercial_proxy.sum(),
            "valid_floor_area_m2": residential.valid_area.sum(),
            "weighted_sv_power": residential.weighted_power.sum(),
        }
    )
    validate_region_support(
        output_directory / region_id,
        snakemake.params.raster,
        pd.Series(summary_rows[-1], name=region_id),
    )

pd.DataFrame(summary_rows).to_parquet(output_directory / "summary.parquet", index=False)
validate_support_batch(output_directory, batch_regions)
population_source.close()
