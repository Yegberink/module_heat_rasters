"""Estimate NUTS-3 heated gross floor area from the 2021 Census."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import rasterio
from _raster import raster_sum, scope_geometry
from _schemas import (
    validate_floor_area_table,
    validate_nuts3,
    validate_reference_rasters,
    validate_scaling_support,
    validate_shapes,
)

if TYPE_CHECKING:
    snakemake: Any


def census_values(path: str, year: int) -> pd.DataFrame:
    """Read the Eurostat TSV and expose its series-key dimensions."""
    data = pd.read_csv(path, sep="\t", dtype=str)
    series_key = data.columns[0]
    dimensions = series_key.removesuffix("\\TIME_PERIOD").split(",")
    year_column = next(column for column in data if column.strip() == str(year))
    data[dimensions] = data.pop(series_key).str.split(",", expand=True)
    data["value"] = pd.to_numeric(
        data.pop(year_column).str.strip().str.split().str[0], errors="coerce"
    ).fillna(0)
    return data


def residential_floor_area(data: pd.DataFrame, settings: dict[str, Any]) -> pd.Series:
    """Estimate useful floor space from dwelling-size or room-count classes."""
    common = data.loc[
        data.freq.eq("A") & data.building.eq("TOTAL") & data.unit.eq("NR")
    ]
    area = (
        common.loc[
            common.n_room.eq("TOTAL") & common.area.isin(settings["floor_space_m2"])
        ]
        .pivot_table(index="geo", columns="area", values="value", aggfunc="sum")
        .mul(pd.Series(settings["floor_space_m2"]))
        .sum(axis=1)
    )
    rooms = (
        common.loc[common.area.eq("TOTAL") & common.n_room.isin(settings["rooms"])]
        .pivot_table(index="geo", columns="n_room", values="value", aggfunc="sum")
        .mul(pd.Series(settings["rooms"]))
        .sum(axis=1)
        .mul(settings["floor_area_per_room_m2"])
    )
    return area.where(area.gt(0), rooms).mul(settings["useful_to_gross_ratio"])


sys.stderr = open(snakemake.log[0], "w")
paths = [snakemake.input.residential_proxy, snakemake.input.non_residential_proxy]
validate_reference_rasters(paths, snakemake.params.source_grid)
shapes = validate_shapes(snakemake.input.shapes)
nuts3 = validate_nuts3(snakemake.input.nuts3)
residential = residential_floor_area(
    census_values(
        snakemake.input.census, snakemake.params.floor_area["reference_year"]
    ),
    snakemake.params.floor_area,
).reindex(nuts3.nuts3_id)
assert residential.notna().all()

with (
    rasterio.open(snakemake.input.residential_proxy) as residential_proxy,
    rasterio.open(snakemake.input.non_residential_proxy) as non_residential_proxy,
):
    nuts3 = nuts3.to_crs(residential_proxy.crs)
    scope = scope_geometry(shapes, residential_proxy.crs)
    clipped = nuts3.geometry.intersection(scope)
    full_proxy = nuts3.geometry.map(
        lambda geometry: raster_sum(residential_proxy, geometry)
    )
    clipped_proxy = clipped.map(
        lambda geometry: raster_sum(residential_proxy, geometry)
    )
    validate_scaling_support(residential.to_numpy(), full_proxy.to_numpy())
    table = pd.DataFrame(
        {
            "nuts3_id": nuts3.nuts3_id,
            "residential_m2": residential.to_numpy()
            * clipped_proxy.to_numpy()
            / full_proxy.to_numpy(),
            "non_residential_m2": clipped.map(
                lambda geometry: raster_sum(non_residential_proxy, geometry)
            ),
        }
    )

table["total_m2"] = table.residential_m2 + table.non_residential_m2
Path(snakemake.output.table).parent.mkdir(parents=True, exist_ok=True)
table.to_parquet(snakemake.output.table, index=False)
validate_floor_area_table(snakemake.output.table, nuts3.nuts3_id)
