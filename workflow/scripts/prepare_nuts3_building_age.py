"""Prepare observed and country-centred NUTS-3 residential age factors.

The Eurostat 2021 dwelling construction-period table is used only where a
region reports known-period conventional dwellings. Unknown periods are
excluded. The source's combined 1981--2000 bin uses its explicit configured
multiplier; no missing region borrows another region's age composition.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
from _schemas import (
    validate_building_age_census,
    validate_floor_area_totals,
    validate_nuts3,
    validate_nuts3_building_age,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.settings
regions = validate_nuts3(snakemake.input.nuts3).set_index("region_id")
totals = validate_floor_area_totals(snakemake.input.floor_area, regions.index).set_index(
    "region_id"
)
raw = validate_building_age_census(snakemake.input.census, 2021)
key = raw.columns[0]
dimensions = key.removesuffix("\\TIME_PERIOD").split(",")
year = next(column for column in raw if column.strip() == "2021")
raw[dimensions] = raw.pop(key).str.split(",", expand=True)
raw["value"] = pd.to_numeric(
    raw.pop(year).str.strip().str.split().str[0], errors="coerce"
)
raw = raw.loc[raw.freq.eq("A") & raw.housing.eq("DW") & raw.unit.eq("NR")]

multipliers = settings["multipliers"]
period_multipliers = {
    "Y_LT1919": multipliers["before_1991"],
    "Y1919-1945": multipliers["before_1991"],
    "Y1946-1960": multipliers["before_1991"],
    "Y1961-1980": multipliers["before_1991"],
    "Y1981-2000": settings["cutoff_spanning_bin_multipliers"]["Y1981-2000"],
    "Y2001-2010": multipliers["after_2000"],
    "Y2011-2015": multipliers["after_2000"],
    "Y_GE2016": multipliers["after_2000"],
}
known_rows = raw.loc[raw.y_const.isin(period_multipliers)].copy()
known_rows["weighted"] = known_rows.value * known_rows.y_const.map(period_multipliers)
known = known_rows.groupby("geo").value.sum(min_count=1).reindex(regions.index).fillna(0)
weighted = (
    known_rows.groupby("geo").weighted.sum(min_count=1).reindex(regions.index).fillna(0)
)
total = (
    raw.loc[raw.y_const.eq("TOTAL")]
    .groupby("geo")
    .value.sum(min_count=1)
    .reindex(regions.index)
    .fillna(0)
)
available = known.gt(0)
factor_raw = weighted.div(known).where(available)
coverage = known.div(total).where(total.gt(0), 0)

references = (
    pd.DataFrame(
        {
            "country_id": regions.country_id,
            "floor_area": totals.residential_total_m2,
            "weighted": totals.residential_total_m2 * factor_raw,
        }
    )
    .loc[available]
    .groupby("country_id")[["floor_area", "weighted"]]
    .sum()
)
references = references.weighted.div(references.floor_area)
factor = factor_raw.div(regions.country_id.map(references)).where(available, 1.0)
if not settings["enabled"]:
    factor[:] = 1.0

age = pd.DataFrame(
    {
        "region_id": regions.index,
        "country_id": regions.country_id,
        "age_factor_raw": factor_raw,
        "age_factor": factor,
        "age_data_available": available,
        "known_dwellings": known,
        "total_dwellings": total,
        "coverage_fraction": coverage,
    }
).reset_index(drop=True)
Path(snakemake.output.table).parent.mkdir(parents=True, exist_ok=True)
age.to_parquet(snakemake.output.table, index=False)
validate_nuts3_building_age(snakemake.output.table, regions.index)

valid = age.loc[age.age_data_available].merge(
    totals[["residential_total_m2"]], left_on="region_id", right_index=True
)
assert np.allclose(
    valid.assign(weighted=lambda table: table.age_factor * table.residential_total_m2)
    .groupby("country_id")
    .weighted.sum(),
    valid.groupby("country_id").residential_total_m2.sum(),
)
