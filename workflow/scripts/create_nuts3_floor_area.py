"""Regionalise one NUTS-3 floor-area control total to hectare cells.

EUBUCCO floor area is footprint area multiplied by floor count and assigned to
the hectare containing the building centroid. Residential building values are
scaled so their complete-region sum matches the census-derived control total;
the requested shape receives only its buildings' resulting share. If a region
has no residential EUBUCCO buildings, the control total is allocated in
proportion to GHS-POP. Observed commercial/public buildings remain unscaled;
their population-based fallback is used only where EUBUCCO has no buildings.

Each partial covers the intersection of one complete NUTS-3 region and the user
shape. Its EPSG:3035 bounds are snapped to the common hectare grid, allowing
lossless addition by ``merge_floor_area.py``.

Sources:
    Floor-area regionalisation: https://doi.org/10.3390/en12244789
    EUBUCCO: https://docs.eubucco.com/v0.2/
    GHS-POP: https://human-settlement.emergency.copernicus.eu/documents/GHSL_Data_Package_2023.pdf
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds
import rasterio
from _eubucco import EUBUCCO_COLUMNS
from _floor_area import (
    gridded_population_sum,
    output_profile,
    write_points,
    write_population,
)
from _raster import finish_raster
from _schemas import (
    FLOOR_AREA_BANDS,
    validate_density_raster,
    validate_floor_area_totals,
    validate_nuts3,
    validate_population_raster,
    validate_shapes,
)
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.floor_area

# Work in the European equal-area CRS so areas and hectare cells are metric.
nuts3 = (
    validate_nuts3(snakemake.input.nuts3).to_crs("EPSG:3035").set_index("nuts3_id")
)
region = nuts3.loc[snakemake.wildcards.nuts3]
scope = (
    validate_shapes(snakemake.input.shapes)
    .to_crs("EPSG:3035")
    .geometry.union_all()
)
clipped = region.geometry.intersection(scope)
totals = (
    validate_floor_area_totals(snakemake.input.totals)
    .set_index("nuts3_id")
    .loc[snakemake.wildcards.nuts3]
)

# Read only legacy EUBUCCO partitions that may overlap this current NUTS-3
# region, then use centroid containment for the final spatial assignment.
table = ds.dataset(snakemake.input.eubucco, format="parquet").to_table(
    columns=EUBUCCO_COLUMNS,
    filter=ds.field("region_id").isin(
        pa.array(snakemake.params.region_ids, type=pa.string())
    ),
)
data = table.to_pandas()
buildings = gpd.GeoDataFrame(
    data,
    geometry=gpd.points_from_xy(data.x_3035, data.y_3035, crs="EPSG:3035"),
)
buildings = buildings.loc[buildings.within(region.geometry)].copy()
buildings["floor_area_m2"] = buildings.footprint_area_m2 * buildings.floors
residential = buildings.loc[
    buildings.type.eq(settings["eubucco"]["residential_type"])
]
commercial = buildings.loc[
    buildings.subtype.isin(settings["eubucco"]["commercial_subtypes"])
]

# Warp population to exactly the same grid as the partial floor-area raster.
# Sum resampling preserves population totals when the cell size changes.
profile = output_profile(clipped.bounds, snakemake.params.raster)
Path(snakemake.output.raster).parent.mkdir(parents=True, exist_ok=True)
validate_population_raster(snakemake.input.population, settings["ghsl_resolution"])
with (
    rasterio.open(snakemake.input.population) as population_source,
    rasterio.open(snakemake.output.raster, "w+", **profile) as output,
    WarpedVRT(
        population_source,
        crs=profile["crs"],
        transform=profile["transform"],
        width=profile["width"],
        height=profile["height"],
        nodata=0,
        resampling=Resampling.sum,
    ) as population_grid,
):
    grid_population = None
    raw_residential = residential.floor_area_m2.sum()
    if raw_residential > 0:
        # Scale all regional residential buildings to the census total, then
        # retain only centroids inside the requested shape for this partial.
        selected = residential.loc[residential.within(scope)]
        write_points(
            output,
            1,
            selected,
            selected.floor_area_m2 * totals.residential_total_m2 / raw_residential,
        )
    else:
        # Regions without residential buildings use population as the proxy.
        grid_population = gridded_population_sum(
            population_source, region.geometry, snakemake.params.raster
        )
        write_population(
            output,
            population_grid,
            1,
            clipped,
            totals.residential_total_m2,
            grid_population,
        )
    if buildings.empty and totals.population > 0:
        # Commercial floor area is only inferred when EUBUCCO has no buildings
        # at all; otherwise its observed commercial/public buildings are used.
        assert np.isfinite(totals.commercial_fallback_m2)
        if grid_population is None:
            grid_population = gridded_population_sum(
                population_source, region.geometry, snakemake.params.raster
            )
        write_population(
            output,
            population_grid,
            2,
            clipped,
            totals.commercial_fallback_m2,
            grid_population,
        )
    else:
        selected = commercial.loc[commercial.within(scope)]
        write_points(output, 2, selected, selected.floor_area_m2)
    finish_raster(
        output,
        FLOOR_AREA_BANDS,
        ("m2/ha",) * 3,
        {
            "nuts3_id": snakemake.wildcards.nuts3,
            "eubucco_version": settings["eubucco"]["version"],
            "building_assignment": settings["eubucco"]["assignment"],
        },
    )
validate_density_raster(
    snakemake.output.raster,
    snakemake.params.raster,
    ("m2/ha",) * 3,
    FLOOR_AREA_BANDS,
)
