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
import pyarrow.dataset as ds
import rasterio
import shapely
from _eubucco import EUBUCCO_COLUMNS, eubucco_batch_filter
from _floor_area import (
    clipped_grid,
    microsoft_floor_area_support,
    output_profile,
    points_within_scope,
    population_grid,
    select_building_sectors,
    write_points,
)
from _microsoft import low_coverage_quadkeys
from _raster import finish_raster
from _schemas import (
    FLOOR_AREA_BANDS,
    validate_density_raster,
    validate_eubucco_plan,
    validate_floor_area_batches,
    validate_floor_area_totals,
    validate_microsoft_tile_statistics,
    validate_nuts3,
    validate_population_raster,
    validate_scope,
)

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
totals = validate_floor_area_totals(snakemake.input.totals).set_index("region_id")
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
    ds.dataset(snakemake.input.microsoft, format="parquet").to_table().to_pandas()
)
microsoft = gpd.GeoDataFrame(
    microsoft, geometry=gpd.points_from_xy(microsoft.x, microsoft.y, crs=regions.crs)
)
output_directory = Path(snakemake.output.partials)
output_directory.mkdir(parents=True, exist_ok=True)

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
    uses_microsoft = "microsoft" in {
        plan["regions"][region_id]["residential_source"],
        plan["regions"][region_id]["commercial_source"],
    }
    population = (
        population_grid(
            population_source,
            full_profile,
            region.geometry,
            "sum",
            region_totals.population,
        )
        if uses_microsoft
        else np.zeros((full_profile["height"], full_profile["width"]), dtype=float)
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

    profile = output_profile(clipped.bounds, snakemake.params.raster, regions.crs)
    path = output_directory / f"{region_id}.tif"
    with rasterio.open(path, "w+", **profile) as output:
        for band, buildings, proxy in (
            (1, residential, residential_proxy),
            (2, commercial, commercial_proxy),
        ):
            inside = buildings.loc[points_within_scope(buildings, scope)]
            write_points(output, band, inside, inside.floor_area_m2)
            output.write(
                output.read(band) + clipped_grid(proxy, full_profile, profile, clipped),
                band,
            )
        finish_raster(
            output,
            FLOOR_AREA_BANDS,
            ("m2/ha",) * 3,
            {
                "region_id": region_id,
                "eubucco_version": eubucco_settings["version"],
                "eubucco_source": eubucco_settings["source"],
                "microsoft_release": plan["microsoft_release"],
                "microsoft_minimum_building_count": microsoft_settings[
                    "minimum_building_count"
                ],
                "residential_source": plan["regions"][region_id]["residential_source"],
                "commercial_source": plan["regions"][region_id]["commercial_source"],
            },
        )
    validate_density_raster(
        path, snakemake.params.raster, ("m2/ha",) * 3, FLOOR_AREA_BANDS
    )

population_source.close()
