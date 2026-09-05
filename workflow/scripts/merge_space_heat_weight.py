"""Merge aligned regional residential space-heating support rasters."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import rasterio
from _floor_area import output_profile
from _plots import plot_floor_area
from _schemas import (
    SPACE_HEAT_WEIGHT_BANDS,
    validate_eubucco_plan,
    validate_plot,
    validate_shapes,
    validate_space_heat_diagnostics,
    validate_space_heat_weight_raster,
)
from rasterio.windows import Window

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.space_heat_weight
plan = validate_eubucco_plan(snakemake.input.plan)
shapes = validate_shapes(snakemake.input.shapes).to_crs(plan["crs"])
profile = output_profile(
    shapes.total_bounds, snakemake.params.raster, plan["crs"], count=1
)
Path(snakemake.output.raster).parent.mkdir(parents=True, exist_ok=True)
partials = {
    path.stem: path
    for batch in snakemake.input.batches
    for path in Path(batch).glob("*.tif")
}

with rasterio.open(snakemake.output.raster, "w+", **profile) as output:
    for region_id in plan["regions"]:
        with rasterio.open(partials[region_id]) as partial:
            raw = rasterio.windows.from_bounds(*partial.bounds, output.transform)
            window = Window(
                round(raw.col_off), round(raw.row_off), round(raw.width), round(raw.height)
            )
            output.write(
                output.read(1, window=window) + partial.read(1), 1, window=window
            )
    output.set_band_description(1, SPACE_HEAT_WEIGHT_BANDS[0])
    output.set_band_unit(1, "weighted_m2/ha")
    output.update_tags(
        method="floor_area * surface_volume * age",
        surface_volume_elasticity=settings["surface_volume"]["elasticity"],
        surface_volume_method=settings["surface_volume"]["method"],
        age_source=f"Eurostat {settings['age']['dataset']}",
        age_old_factor=settings["age"]["multipliers"]["before_1991"],
        age_reference_factor=settings["age"]["multipliers"]["1991_2000"],
        age_new_factor=settings["age"]["multipliers"]["after_2000"],
        age_1981_2000_factor=settings["age"]["cutoff_spanning_bin_multipliers"][
            "Y1981-2000"
        ],
        hdd_applied="false",
    )
validate_space_heat_weight_raster(snakemake.output.raster, snakemake.params.raster)

diagnostics = pd.concat(
    [
        pd.read_parquet(path)
        for batch in snakemake.input.batches
        for path in sorted(Path(batch).glob("*.parquet"))
    ],
    ignore_index=True,
).sort_values(["country_id", "region_id"])
diagnostics.to_parquet(snakemake.output.diagnostics, index=False)
validate_space_heat_diagnostics(snakemake.output.diagnostics, plan["regions"])

plot_floor_area(
    snakemake.output.raster,
    1,
    "Residential space-heating support",
    snakemake.output.plot,
    snakemake.params.raster["block_size"],
    snakemake.params.raster["plot_max_size"],
    "Space-heating support (weighted m²/ha)",
)
validate_plot(snakemake.output.plot)
