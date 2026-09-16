"""Assemble physical floor area and residential heat support in one output job."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd
import rasterio
from _eubucco import read_plan
from _floor_area import add_partial, output_profile
from _plots import plot_floor_area
from _raster import FLOOR_AREA_BANDS, SPACE_HEAT_WEIGHT_BANDS, finish_raster

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.space_heat_weight
eurostat = snakemake.params.eurostat
population = snakemake.params.population
eubucco = snakemake.params.eubucco
plan = read_plan(snakemake.input.plan)
batches = read_plan(snakemake.input.batches)["batches"]
shapes = gpd.read_parquet(snakemake.input.shapes).to_crs(plan["crs"])
profile = output_profile(shapes.total_bounds, snakemake.params.raster, plan["crs"])
for path in (
    snakemake.output.floor_area,
    snakemake.output.residential_space_heat_weight,
    snakemake.output.diagnostics,
):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
support = {Path(path).name: Path(path) for path in snakemake.input.support}
weights = {Path(path).name: Path(path) for path in snakemake.input.weights}
diagnostics = []
with (
    rasterio.open(snakemake.output.floor_area, "w+", **profile) as floor,
    rasterio.open(
        snakemake.output.residential_space_heat_weight, "w+", **{**profile, "count": 1}
    ) as heat,
):
    for batch, regions in batches.items():
        diagnostics.append(
            pd.read_parquet(Path(weights[batch]) / "diagnostics.parquet")
        )
        for region_id in regions:
            floor_path = support[batch] / region_id / "floor_area.tif"
            heat_path = weights[batch] / f"{region_id}.tif"

            with rasterio.open(floor_path) as partial:
                add_partial(floor, partial)
            with rasterio.open(heat_path) as partial:
                add_partial(heat, partial, (1,))
    finish_raster(
        floor,
        FLOOR_AREA_BANDS,
        ("m2/ha",) * 3,
        {
            "census_reference_year": eurostat["reference_year"],
            "eubucco_version": eubucco["version"],
            "eubucco_source": eubucco["source"],
            "microsoft_release": plan["microsoft_release"],
            "microsoft_minimum_building_count": snakemake.params.microsoft[
                "minimum_building_count"
            ],
            "ghsl_epoch": population["epoch"],
            "building_assignment": eubucco["assignment"],
        },
    )
    heat.set_band_description(1, SPACE_HEAT_WEIGHT_BANDS[0])
    heat.set_band_unit(1, "weighted_m2/ha")
    heat.update_tags(
        method="blended_floor_area * surface_volume * age",
        eubucco_source=plan["eubucco_source"],
        population_source="GHS-POP",
        population_epoch=snakemake.params.population["epoch"],
        population_share=settings["population"]["share"],
        population_resampling=settings["population"]["resampling"],
        microsoft_minimum_building_count=snakemake.params.microsoft[
            "minimum_building_count"
        ],
        surface_volume_elasticity=settings["surface_volume"]["elasticity"],
        surface_volume_method=settings["surface_volume"]["method"],
        age_source=f"Eurostat {settings['age']['dataset']}",
        age_old_factor=settings["age"]["multipliers"]["before_1991"],
        age_reference_factor=settings["age"]["multipliers"]["1991_2000"],
        age_new_factor=settings["age"]["multipliers"]["after_2000"],
        age_1981_2000_factor=settings["age"]["cutoff_spanning_bin_multipliers"][
            "Y1981-2000"
        ],
    )


pd.concat(diagnostics, ignore_index=True).sort_values(
    ["country_id", "region_id"]
).to_parquet(snakemake.output.diagnostics, index=False)


for raster, band, title, path, unit in (
    (
        snakemake.output.floor_area,
        1,
        "Residential floor area",
        snakemake.output.residential_plot,
        "Floor area (m²/ha)",
    ),
    (
        snakemake.output.floor_area,
        2,
        "Commercial and public floor area",
        snakemake.output.commercial_plot,
        "Floor area (m²/ha)",
    ),
    (
        snakemake.output.residential_space_heat_weight,
        1,
        "Residential space-heating support",
        snakemake.output.heat_plot,
        "Space-heating support (weighted m²/ha)",
    ),
):
    plot_floor_area(
        raster,
        band,
        title,
        path,
        snakemake.params.raster["block_size"],
        snakemake.params.raster["plot_max_size"],
        shapes,
        snakemake.params.raster["plot_outline"],
        unit,
    )
