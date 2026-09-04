"""Regionalise floor-area totals with EUBUCCO-first building support.

Each complete control region and sector uses one source. EUBUCCO floor area is
preferred; Microsoft footprint area is the fallback weight. The requested
shape receives only the share represented by building centroids inside it.
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
    output_profile,
    points_within_scope,
    select_building_sectors,
    write_points,
)
from _raster import finish_raster
from _schemas import (
    FLOOR_AREA_BANDS,
    validate_density_raster,
    validate_eubucco_plan,
    validate_floor_area_batches,
    validate_floor_area_totals,
    validate_nuts3,
    validate_scope,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.floor_area
plan = validate_eubucco_plan(snakemake.input.plan)
batch_plan = validate_floor_area_batches(snakemake.input.batches, plan["regions"])
batch_regions = batch_plan["batches"][snakemake.wildcards.batch]
regions = validate_nuts3(snakemake.input.nuts3).set_index("region_id").loc[batch_regions]
scope = validate_scope(snakemake.input.scope).geometry.item()
shapely.prepare(scope)
totals = validate_floor_area_totals(snakemake.input.totals).set_index("region_id")

legacy_ids = sorted(
    {
        legacy
        for region_id in batch_regions
        for legacy in plan["regions"][region_id]["eubucco_region_ids"]
    }
)
eubucco = ds.dataset(snakemake.input.eubucco, format="parquet").to_table(
    columns=EUBUCCO_COLUMNS[1:],
    filter=eubucco_batch_filter(legacy_ids, regions.total_bounds),
).to_pandas(categories=["region_id", "type", "subtype"])
eubucco = gpd.GeoDataFrame(
    eubucco,
    geometry=gpd.points_from_xy(eubucco.x, eubucco.y, crs=regions.crs),
)
eubucco["floor_area_m2"] = eubucco.footprint_area_m2 * eubucco.floors

microsoft = ds.dataset(snakemake.input.microsoft, format="parquet").to_table().to_pandas()
microsoft = gpd.GeoDataFrame(
    microsoft,
    geometry=gpd.points_from_xy(microsoft.x, microsoft.y, crs=regions.crs),
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
        settings["eubucco"]["residential_type"],
        settings["eubucco"]["commercial_subtypes"],
    )
    fallback = microsoft.loc[microsoft.region_id.eq(region_id)]
    profile = output_profile(clipped.bounds, snakemake.params.raster, regions.crs)
    path = output_directory / f"{region_id}.tif"
    with rasterio.open(path, "w+", **profile) as output:
        if plan["regions"][region_id]["residential_source"] == "eubucco":
            support = residential.floor_area_m2.sum()
            assert support > 0
            inside = residential.loc[points_within_scope(residential, scope)]
            write_points(output, 1, inside, inside.floor_area_m2 * region_totals.residential_total_m2 / support)
        else:
            support = fallback.footprint_area_m2.sum()
            assert support > 0 or region_totals.residential_total_m2 == 0
            inside = fallback.loc[points_within_scope(fallback, scope)]
            write_points(output, 1, inside, inside.footprint_area_m2 * region_totals.residential_total_m2 / support)

        if plan["regions"][region_id]["commercial_source"] == "eubucco":
            assert not commercial.empty
            inside = commercial.loc[points_within_scope(commercial, scope)]
            write_points(output, 2, inside, inside.floor_area_m2)
        else:
            support = fallback.footprint_area_m2.sum()
            assert np.isfinite(region_totals.commercial_fallback_m2)
            assert support > 0 or region_totals.commercial_fallback_m2 == 0
            inside = fallback.loc[points_within_scope(fallback, scope)]
            write_points(output, 2, inside, inside.footprint_area_m2 * region_totals.commercial_fallback_m2 / support)
        finish_raster(
            output,
            FLOOR_AREA_BANDS,
            ("m2/ha",) * 3,
            {
                "region_id": region_id,
                "eubucco_version": settings["eubucco"]["version"],
                "microsoft_release": plan["microsoft_release"],
                "residential_source": plan["regions"][region_id]["residential_source"],
                "commercial_source": plan["regions"][region_id]["commercial_source"],
            },
        )
    validate_density_raster(path, snakemake.params.raster, ("m2/ha",) * 3, FLOOR_AREA_BANDS)
