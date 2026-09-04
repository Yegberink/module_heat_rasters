"""Merge control-region partials into the final hectare floor-area raster.

Because every partial is aligned to one equal-area grid, residential and
commercial/public bands can be added without reprojection. The total band is
derived after the merge, provenance is stored as raster metadata, and separate
diagnostic maps expose the two allocation layers.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import rasterio
from _eubucco import read_plan
from _floor_area import add_partial, output_profile
from _plots import plot_floor_area
from _raster import finish_raster
from _schemas import FLOOR_AREA_BANDS, validate_density_raster, validate_plot

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.floor_area
plan = read_plan(snakemake.input.plan)
shapes = gpd.read_parquet(snakemake.input.shapes).to_crs(plan["crs"])
profile = output_profile(shapes.total_bounds, snakemake.params.raster, plan["crs"])
Path(snakemake.output.raster).parent.mkdir(parents=True, exist_ok=True)

# Partials share one aligned grid, so their residential and commercial bands
# can be added directly without reprojection or resampling.
partials = {
    path.stem: path
    for batch in snakemake.input.batches
    for path in Path(batch).glob("*.tif")
}
with rasterio.open(snakemake.output.raster, "w+", **profile) as output:
    for region_id in plan["regions"]:
        with rasterio.open(partials[region_id]) as partial:
            add_partial(output, partial)
    finish_raster(
        output,
        FLOOR_AREA_BANDS,
        ("m2/ha",) * 3,
        {
            "census_reference_year": settings["reference_year"],
            "eubucco_version": settings["eubucco"]["version"],
            "microsoft_release": plan["microsoft_release"],
            "ghsl_epoch": settings["ghsl_epoch"],
            "building_assignment": settings["eubucco"]["assignment"],
        },
    )
validate_density_raster(
    snakemake.output.raster, snakemake.params.raster, ("m2/ha",) * 3, FLOOR_AREA_BANDS
)

# Diagnostic maps make the two independently constructed sector bands visible.
plot_floor_area(
    snakemake.output.raster,
    1,
    "Residential floor area",
    snakemake.output.residential_plot,
    snakemake.params.raster["block_size"],
    snakemake.params.raster["plot_max_size"],
)
plot_floor_area(
    snakemake.output.raster,
    2,
    "Commercial and public floor area",
    snakemake.output.commercial_plot,
    snakemake.params.raster["block_size"],
    snakemake.params.raster["plot_max_size"],
)
validate_plot(snakemake.output.residential_plot)
validate_plot(snakemake.output.commercial_plot)
