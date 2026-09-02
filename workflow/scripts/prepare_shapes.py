"""Filter user-provided shapes to the processable land scope."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from _schemas import validate_shape_source, validate_shapes

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
shapes = validate_shape_source(snakemake.input.shapes)
shapes = shapes.loc[shapes.shape_class.eq("land")]
Path(snakemake.output.shapes).parent.mkdir(parents=True, exist_ok=True)
shapes.to_parquet(snakemake.output.shapes, index=False)
validate_shapes(snakemake.output.shapes)
