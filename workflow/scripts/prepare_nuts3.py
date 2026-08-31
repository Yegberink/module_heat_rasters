"""Select official NUTS-3 regions overlapping a user shape case."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
from _schemas import validate_nuts3, validate_shapes

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
shapes = validate_shapes(snakemake.input.shapes)
nuts3 = gpd.read_file(snakemake.input.nuts3)
shapes = shapes.to_crs(nuts3.crs)
scope = shapes.geometry.union_all()
nuts3 = nuts3.loc[nuts3.intersects(scope), ["NUTS_ID", "geometry"]]
nuts3 = nuts3.loc[nuts3.geometry.intersection(scope).area.gt(0)].rename(
    columns={"NUTS_ID": "nuts3_id"}
)
Path(snakemake.output.regions).parent.mkdir(parents=True, exist_ok=True)
nuts3.to_parquet(snakemake.output.regions, index=False)
validate_nuts3(snakemake.output.regions)
