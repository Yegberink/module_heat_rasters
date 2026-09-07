"""Calculate residential heat weights from persistent floor-area intermediates.

Complete-region arrays preserve normalization and diagnostic totals. Scoped
arrays preserve the distinct building-centroid and population-cell clipping.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
from _raster import write_raster
from _schemas import (
    SPACE_HEAT_WEIGHT_BANDS,
    validate_eubucco_plan,
    validate_floor_area_batches,
    validate_nuts3_building_age,
    validate_region_support,
    validate_space_heat_diagnostics,
    validate_space_heat_weight_raster,
    validate_support_batch,
    validate_sv_statistics,
)
from _space_heat_weight import weight_from_support

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
plan = validate_eubucco_plan(snakemake.input.plan)
batches = validate_floor_area_batches(snakemake.input.batches, plan["regions"])
region_ids = batches["batches"][snakemake.wildcards.batch]
summary = validate_support_batch(snakemake.input.support, region_ids).set_index(
    "region_id"
)
age = validate_nuts3_building_age(snakemake.input.age, plan["regions"]).set_index(
    "region_id"
)
statistics = validate_sv_statistics(snakemake.input.sv_statistics).set_index(
    "country_id"
)
output_directory = Path(snakemake.output.partials)
output_directory.mkdir(parents=True, exist_ok=True)
diagnostics = []

for region_id, row in summary.iterrows():
    floor, full, scoped, profile = validate_region_support(
        Path(snakemake.input.support) / region_id, snakemake.params.intermediate, row
    )
    age_row = age.loc[region_id]
    arguments = dict(
        reference=statistics.at[row.country_id, "sv_power_reference"],
        total=row.residential_floor_area_m2,
        population_total=full[1].sum(),
        share=snakemake.params.population_share,
        age=age_row.age_factor,
    )
    full_weights = weight_from_support(*full, **arguments)
    weights = weight_from_support(floor[0], *scoped, **arguments)
    raster_path = output_directory / f"{region_id}.tif"
    write_raster(
        raster_path,
        {**profile, "dtype": snakemake.params.raster["dtype"]},
        (weights,),
        SPACE_HEAT_WEIGHT_BANDS,
        ("weighted_m2/ha",),
        {
            "region_id": region_id,
            "method": "blended_floor_area * surface_volume * age",
            "population_share": snakemake.params.population_share,
        },
    )
    validate_space_heat_weight_raster(raster_path, snakemake.params.raster)
    diagnostics.append(
        {
            "country_id": row.country_id,
            "region_id": region_id,
            "residential_floor_area_m2": row.residential_floor_area_m2,
            "residential_source": row.residential_source,
            "sv_valid_floor_area_fraction": row.valid_floor_area_m2
            / row.residential_floor_area_m2
            if row.residential_floor_area_m2 > 0
            else 0.0,
            "age_data_available": age_row.age_data_available,
            "age_coverage_fraction": age_row.coverage_fraction,
            "raw_age_factor": age_row.age_factor_raw,
            "normalised_age_factor": age_row.age_factor,
            "raw_heat_weight": full_weights.sum(),
        }
    )

path = output_directory / "diagnostics.parquet"
pd.DataFrame(diagnostics).to_parquet(path, index=False)
validate_space_heat_diagnostics(path, region_ids)
