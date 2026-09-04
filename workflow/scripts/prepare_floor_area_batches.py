"""Prepare balanced batches for control-region floor-area processing."""

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from _eubucco import assign_region_batches
from _schemas import (
    validate_eubucco_plan,
    validate_eubucco_stats,
    validate_floor_area_batches,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
eubucco = validate_eubucco_plan(snakemake.input.plan)
stats = validate_eubucco_stats(snakemake.input.stats)
plan = {
    "schema_version": 1,
    "batches": assign_region_batches(
        eubucco["regions"], stats, snakemake.params.batch_count
    ),
}
Path(snakemake.output.manifest).parent.mkdir(parents=True, exist_ok=True)
with open(snakemake.output.manifest, "w") as stream:
    json.dump(plan, stream, indent=2)
validate_floor_area_batches(snakemake.output.manifest, eubucco["regions"])
