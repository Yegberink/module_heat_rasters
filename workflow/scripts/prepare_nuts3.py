"""Prepare the current NUTS-3 geography for one user-defined shape case.

The script selects official NUTS-3 polygons with positive-area overlap in land
shapes belonging to the same country. This prevents generalized borders from
introducing regions from neighbouring countries.
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
from _schemas import validate_nuts3, validate_nuts3_source

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
shapes = gpd.read_parquet(snakemake.input.shapes)
nuts3 = validate_nuts3_source(snakemake.input.nuts3)
shapes = shapes.to_crs(nuts3.crs)
scope = shapes.geometry.union_all()
nuts3["country_id"] = nuts3.CNTR_CODE.map(
    {code: country for country, code in snakemake.params.country_codes.items()}
)

# Require positive-area overlap: boundary touches do not create usable regions.
nuts3 = nuts3.loc[nuts3.intersects(scope), ["NUTS_ID", "country_id", "geometry"]]
nuts3 = nuts3.loc[nuts3.geometry.intersection(scope).area.gt(0)].rename(
    columns={"NUTS_ID": "nuts3_id"}
)
nuts3.geometry = nuts3.geometry.make_valid()

countries = gpd.overlay(
    nuts3,
    shapes[["country_id", "geometry"]].rename(
        columns={"country_id": "shape_country_id"}
    ),
    how="intersection",
    keep_geom_type=False,
)
countries = countries.loc[countries.country_id.eq(countries.shape_country_id)]
countries["area"] = countries.area
countries = countries.sort_values("area").drop_duplicates("nuts3_id", keep="last")
nuts3 = nuts3.loc[nuts3.nuts3_id.isin(countries.nuts3_id)]
nuts3 = nuts3[["nuts3_id", "country_id", "geometry"]]
Path(snakemake.output.regions).parent.mkdir(parents=True, exist_ok=True)
nuts3.to_parquet(snakemake.output.regions, index=False)
validate_nuts3(snakemake.output.regions)
