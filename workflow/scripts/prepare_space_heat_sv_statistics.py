"""Stream EUBUCCO by NUTS-3 region to prepare country S/V normalisers.

Only residential buildings with valid observed height contribute. Their floor
area is first calibrated to the same complete-region Eurostat control used by
the floor-area raster, then used to centre the compactness power by country.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import shapely
from _eubucco import EUBUCCO_COLUMNS, eubucco_batch_filter
from _schemas import (
    validate_eubucco_plan,
    validate_floor_area_totals,
    validate_nuts3,
    validate_sv_statistics,
)
from _space_heat_weight import surface_to_volume_ratio, surface_volume_power

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.settings
if settings["surface_volume"]["method"] != "equivalent_square":
    raise ValueError("The lightweight EUBUCCO v0.2 table has no footprint perimeter")
regions = validate_nuts3(snakemake.input.nuts3).set_index("region_id")
totals = validate_floor_area_totals(snakemake.input.floor_area, regions.index).set_index(
    "region_id"
)
plan = validate_eubucco_plan(snakemake.input.plan)
dataset = ds.dataset(snakemake.input.eubucco, format="parquet")
statistics = {
    country: {"valid_floor_area_m2": 0.0, "weighted_sv_power": 0.0}
    for country in sorted(regions.country_id.unique())
}

for region_id, region in regions.iterrows():
    if plan["regions"][region_id]["residential_source"] != "eubucco":
        continue
    legacy = plan["regions"][region_id]["eubucco_region_ids"]
    buildings = dataset.to_table(
        columns=EUBUCCO_COLUMNS[1:],
        filter=eubucco_batch_filter(legacy, region.geometry.bounds),
    ).to_pandas(categories=["region_id", "type", "subtype"])
    buildings = buildings.loc[
        buildings.type.eq(snakemake.params.residential_type)
        & shapely.contains_xy(region.geometry, buildings.x, buildings.y)
    ]
    raw_floor_area = buildings.footprint_area_m2 * buildings.floors
    scale = totals.at[region_id, "residential_total_m2"] / raw_floor_area.sum()
    floor_area = raw_floor_area * scale
    assert np.isclose(floor_area.sum(), totals.at[region_id, "residential_total_m2"])
    ratio = surface_to_volume_ratio(
        buildings.footprint_area_m2,
        buildings.height_m,
        method=settings["surface_volume"]["method"],
    )
    power = surface_volume_power(ratio, settings["surface_volume"]["elasticity"])
    valid = np.isfinite(power)
    country = statistics[region.country_id]
    country["valid_floor_area_m2"] += floor_area[valid].sum()
    country["weighted_sv_power"] += (floor_area[valid] * power[valid]).sum()

rows = []
for country_id, values in statistics.items():
    reference = (
        values["weighted_sv_power"] / values["valid_floor_area_m2"]
        if values["valid_floor_area_m2"] > 0
        else 1.0
    )
    rows.append({"country_id": country_id, **values, "sv_power_reference": reference})
output = pd.DataFrame(rows)
Path(snakemake.output.table).parent.mkdir(parents=True, exist_ok=True)
output.to_parquet(snakemake.output.table, index=False)
validate_sv_statistics(snakemake.output.table, regions.country_id.unique())
