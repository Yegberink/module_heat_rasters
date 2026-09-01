"""Select official NUTS-3 regions overlapping a user shape case."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
from _schemas import validate_nuts3, validate_nuts3_source, validate_shapes

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
shapes = validate_shapes(snakemake.input.shapes)
nuts3 = validate_nuts3_source(snakemake.input.nuts3)
shapes = shapes.to_crs(nuts3.crs)
scope = shapes.geometry.union_all()
nuts3 = nuts3.loc[nuts3.intersects(scope), ["NUTS_ID", "geometry"]]
nuts3 = nuts3.loc[nuts3.geometry.intersection(scope).area.gt(0)].rename(
    columns={"NUTS_ID": "nuts3_id"}
)
nuts3.geometry = nuts3.geometry.make_valid()
countries = gpd.overlay(
    nuts3, shapes[["country_id", "geometry"]], how="intersection", keep_geom_type=False
)
countries["area"] = countries.area
countries = countries.sort_values("area").drop_duplicates("nuts3_id", keep="last")
nuts3 = nuts3.merge(countries[["nuts3_id", "country_id"]], on="nuts3_id")
nuts3 = nuts3[["nuts3_id", "country_id", "geometry"]]
Path(snakemake.output.regions).parent.mkdir(parents=True, exist_ok=True)
nuts3.to_parquet(snakemake.output.regions, index=False)
validate_nuts3(snakemake.output.regions)
