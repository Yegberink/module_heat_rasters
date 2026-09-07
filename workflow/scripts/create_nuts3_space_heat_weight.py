"""Create NUTS-3 partial rasters of residential space-heating support.

Building-derived residential floor area is blended with GHS-POP within each
complete NUTS-3 region. Country-centred EUBUCCO compactness and NUTS-3 age
factors are then applied without any regional heat-weight renormalisation.
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
)
from _microsoft import low_coverage_quadkeys
from _schemas import (
    SPACE_HEAT_WEIGHT_BANDS,
    validate_eubucco_plan,
    validate_floor_area_batches,
    validate_floor_area_totals,
    validate_microsoft_tile_statistics,
    validate_nuts3,
    validate_nuts3_building_age,
    validate_population_raster,
    validate_scope,
    validate_space_heat_diagnostics,
    validate_space_heat_weight_raster,
    validate_sv_statistics,
)
from _space_heat_weight import (
    blend_floor_area,
    cell_surface_volume_factor,
    normalised_factor,
    space_heat_weight,
    surface_to_volume_ratio,
    surface_volume_power,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.space_heat_weight
plan = validate_eubucco_plan(snakemake.input.plan)
batches = validate_floor_area_batches(snakemake.input.batches, plan["regions"])
batch_regions = batches["batches"][snakemake.wildcards.batch]
regions = (
    validate_nuts3(snakemake.input.nuts3).set_index("region_id").loc[batch_regions]
)
scope = validate_scope(snakemake.input.scope).geometry.item()
shapely.prepare(scope)
totals = validate_floor_area_totals(snakemake.input.floor_area).set_index("region_id")
planned_quadkeys = {
    key for region in plan["regions"].values() for key in region["microsoft_quadkeys"]
}
statistics = validate_microsoft_tile_statistics(
    snakemake.input.microsoft_statistics, planned_quadkeys
)
low_quadkeys = low_coverage_quadkeys(
    statistics, snakemake.params.microsoft["minimum_building_count"]
)
validate_population_raster(
    snakemake.input.population, snakemake.params.population["resolution"]
)
population_source = rasterio.open(snakemake.input.population)
age = validate_nuts3_building_age(snakemake.input.age).set_index("region_id")
sv_statistics = validate_sv_statistics(snakemake.input.sv_statistics).set_index(
    "country_id"
)
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
microsoft = (
    ds.dataset(snakemake.input.microsoft, format="parquet").to_table().to_pandas()
)
microsoft = gpd.GeoDataFrame(
    microsoft, geometry=gpd.points_from_xy(microsoft.x, microsoft.y, crs=regions.crs)
)
output_directory = Path(snakemake.output.partials)
output_directory.mkdir(parents=True, exist_ok=True)

for region_id, region in regions.iterrows():
    clipped = region.geometry.intersection(scope)
    total = totals.at[region_id, "residential_total_m2"]
    source = plan["regions"][region_id]["residential_source"]
    age_row = age.loc[region_id]
    full_profile = output_profile(
        region.geometry.bounds, snakemake.params.raster, regions.crs, count=1
    )
    full_population = population_grid(
        population_source,
        full_profile,
        region.geometry,
        settings["population"]["resampling"],
        totals.at[region_id, "population"],
    )
    if source == "eubucco":
        legacy = plan["regions"][region_id]["eubucco_region_ids"]
        buildings = eubucco.loc[
            eubucco.region_id.isin(legacy)
            & eubucco.geometry.within(region.geometry)
            & eubucco["type"].eq(snakemake.params.residential_type)
        ].copy()
        buildings["floor_area_m2"] = buildings.footprint_area_m2 * buildings.floors
        support = buildings.floor_area_m2.sum()
        assert support > 0
        buildings["floor_area_m2"] *= total / support
        assert np.isclose(buildings.floor_area_m2.sum(), total)
        ratio = surface_to_volume_ratio(
            buildings.footprint_area_m2,
            buildings.height_m,
            buildings.footprint_perimeter_m,
            method=settings["surface_volume"]["method"],
        )
        power = surface_volume_power(ratio, settings["surface_volume"]["elasticity"])
        valid = np.isfinite(power)
        f_sv = normalised_factor(
            power, sv_statistics.at[region.country_id, "sv_power_reference"]
        )
        sv_fraction = (
            buildings.loc[valid, "floor_area_m2"].sum() / total if total > 0 else 0.0
        )
        proxy = np.zeros_like(full_population)
    else:
        buildings, proxy = microsoft_floor_area_support(
            full_profile,
            microsoft.loc[microsoft.region_id.eq(region_id)],
            full_population,
            total,
            totals.at[region_id, "population"],
            low_quadkeys & set(plan["regions"][region_id]["microsoft_quadkeys"]),
        )
        f_sv = 1.0
        sv_fraction = 0.0
    buildings["f_sv"] = f_sv
    full_floor_area = (
        point_grid(full_profile, buildings, buildings.floor_area_m2) + proxy
    )
    full_sv_weighted = (
        point_grid(full_profile, buildings, buildings.floor_area_m2 * buildings.f_sv)
        + proxy
    )
    blended_full = blend_floor_area(
        full_floor_area, full_population, total, settings["population"]["share"]
    )
    full_weights = space_heat_weight(
        blended_full,
        cell_surface_volume_factor(full_floor_area, full_sv_weighted),
        age_row.age_factor,
    )
    assert np.isfinite(full_weights).all()
    assert (full_weights >= 0).all()

    profile = output_profile(
        clipped.bounds, snakemake.params.raster, regions.crs, count=1
    )
    inside = buildings.loc[points_within_scope(buildings, scope)]
    clipped_proxy = clipped_grid(proxy, full_profile, profile, clipped)
    floor_area = point_grid(profile, inside, inside.floor_area_m2) + clipped_proxy
    sv_weighted = (
        point_grid(profile, inside, inside.floor_area_m2 * inside.f_sv) + clipped_proxy
    )
    population = clipped_grid(full_population, full_profile, profile, clipped)
    if total == 0 or settings["population"]["share"] == 0:
        blended = floor_area
    else:
        blended = (1 - settings["population"]["share"]) * floor_area + settings[
            "population"
        ]["share"] * total * population / full_population.sum()
    weights = space_heat_weight(
        blended, cell_surface_volume_factor(floor_area, sv_weighted), age_row.age_factor
    )
    raster_path = output_directory / f"{region_id}.tif"
    with rasterio.open(raster_path, "w+", **profile) as output:
        output.write(weights.astype(profile["dtype"]), 1)
        output.set_band_description(1, SPACE_HEAT_WEIGHT_BANDS[0])
        output.set_band_unit(1, "weighted_m2/ha")
        output.update_tags(
            region_id=region_id,
            method="blended_floor_area * surface_volume * age",
            population_share=settings["population"]["share"],
            population_resampling=settings["population"]["resampling"],
            microsoft_minimum_building_count=snakemake.params.microsoft[
                "minimum_building_count"
            ],
            surface_volume_method=settings["surface_volume"]["method"],
        )
    validate_space_heat_weight_raster(raster_path, snakemake.params.raster)

    diagnostic = pd.DataFrame(
        [
            {
                "country_id": region.country_id,
                "region_id": region_id,
                "residential_floor_area_m2": total,
                "residential_source": source,
                "sv_valid_floor_area_fraction": sv_fraction,
                "age_data_available": age_row.age_data_available,
                "age_coverage_fraction": age_row.coverage_fraction,
                "raw_age_factor": age_row.age_factor_raw,
                "normalised_age_factor": age_row.age_factor,
                "raw_heat_weight": full_weights.sum(),
            }
        ]
    )
    diagnostic_path = output_directory / f"{region_id}.parquet"
    diagnostic.to_parquet(diagnostic_path, index=False)
    validate_space_heat_diagnostics(diagnostic_path, [region_id])

population_source.close()
