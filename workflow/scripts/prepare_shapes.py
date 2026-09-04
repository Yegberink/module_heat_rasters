"""Filter user-provided shapes to the processable land scope."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
from _raster import scope_geometry
from _regions import processing_crs
from _schemas import validate_scope, validate_shape_source, validate_shapes

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
shapes = validate_shape_source(snakemake.input.shapes)
shapes = shapes.loc[shapes.shape_class.eq("land")]
Path(snakemake.output.shapes).parent.mkdir(parents=True, exist_ok=True)
shapes.to_parquet(snakemake.output.shapes, index=False)
shapes = validate_shapes(snakemake.output.shapes)
crs = processing_crs(shapes)
scope = gpd.GeoDataFrame(
    geometry=[scope_geometry(shapes, crs)], crs=crs
)
scope.to_parquet(snakemake.output.scope, index=False)
validate_scope(snakemake.output.scope)
