"""Prepare the current NUTS-3 geography for one user-defined shape case.

The script selects official NUTS-3 polygons with positive-area overlap in land
shapes belonging to the same country. This prevents generalized borders from
introducing regions from neighbouring countries.
Countries outside the NUTS geography receive one shape-based region so their
configured floor-area proxies remain reachable.
The complete NUTS geometry is retained because regional census totals and
building-stock totals refer to administrative regions, not clipped fragments.
Clipping occurs only when the final hectare rasters are written.

Source:
    Eurostat GISCO NUTS: https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd
from _regions import processing_crs
from _schemas import validate_nuts3, validate_nuts3_source, validate_shapes

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
shapes = validate_shapes(snakemake.input.shapes)
nuts3 = validate_nuts3_source(snakemake.input.nuts3)
working_crs = processing_crs(shapes)
shapes = shapes.to_crs(nuts3.crs)
scope = shapes.geometry.union_all()
nuts3["country_id"] = nuts3.CNTR_CODE.map(
    {code: country for country, code in snakemake.params.country_codes.items()}
)
# Require positive-area overlap: boundary touches do not create usable regions.
nuts3 = nuts3.loc[nuts3.intersects(scope), ["NUTS_ID", "country_id", "geometry"]]
nuts3 = nuts3.loc[nuts3.geometry.intersection(scope).area.gt(0)].rename(
    columns={"NUTS_ID": "region_id"}
)
nuts3.geometry = nuts3.geometry.make_valid()

matches = gpd.overlay(
    nuts3,
    shapes[["shape_id", "country_id", "geometry"]].rename(
        columns={"country_id": "shape_country_id"}
    ),
    how="intersection",
    keep_geom_type=False,
)
matches = matches.loc[matches.country_id.eq(matches.shape_country_id)]
matched_shapes = set(matches.shape_id)
matches["area"] = matches.area
matches = matches.sort_values("area").drop_duplicates("region_id", keep="last")
nuts3 = nuts3.loc[nuts3.region_id.isin(matches.region_id)]

# NUTS omissions and countries outside Europe use the user shapes as control
# regions. Their assumption-based totals remain tied to the supplied geography.
fallback = shapes.loc[~shapes.shape_id.isin(matched_shapes)].dissolve(
    ["country_id", "shape_id"], as_index=False
)
fallback["region_id"] = "shape-" + fallback.shape_id
nuts3 = gpd.GeoDataFrame(
    pd.concat(
        [
            nuts3[["region_id", "country_id", "geometry"]],
            fallback[["region_id", "country_id", "geometry"]],
        ],
        ignore_index=True,
    ),
    crs=nuts3.crs,
).to_crs(working_crs)
Path(snakemake.output.regions).parent.mkdir(parents=True, exist_ok=True)
nuts3.to_parquet(snakemake.output.regions, index=False)
validate_nuts3(snakemake.output.regions, shapes.country_id)
