"""Aggregate cached complete-region compactness sums without rereading buildings."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
from _schemas import (
    validate_eubucco_plan,
    validate_floor_area_batches,
    validate_support_batch,
    validate_sv_statistics,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
plan = validate_eubucco_plan(snakemake.input.plan)
batches = validate_floor_area_batches(snakemake.input.batches, plan["regions"])[
    "batches"
]
summary = pd.concat(
    [
        validate_support_batch(path, batches[Path(path).name])
        for path in snakemake.input.support
    ],
    ignore_index=True,
)
statistics = summary.groupby("country_id")[
    ["valid_floor_area_m2", "weighted_sv_power"]
].sum()
statistics["sv_power_reference"] = statistics.weighted_sv_power.div(
    statistics.valid_floor_area_m2
).where(statistics.valid_floor_area_m2.gt(0), 1.0)
Path(snakemake.output.table).parent.mkdir(parents=True, exist_ok=True)
statistics.reset_index().to_parquet(snakemake.output.table, index=False)
validate_sv_statistics(snakemake.output.table, summary.country_id.unique())
