"""Regionalise NUTS-3 heated gross floor area to hectares."""

import sys
from typing import TYPE_CHECKING, Any

import rasterio
from _raster import (
    create_output,
    finish_raster,
    raster_sum,
    scope_geometry,
    write_scaled,
)
from _schemas import (
    RASTER_BANDS,
    SECTORS,
    validate_density_raster,
    validate_floor_area_table,
    validate_nuts3,
    validate_reference_rasters,
    validate_scaling_support,
    validate_shapes,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
paths = [snakemake.input.residential, snakemake.input.non_residential]
validate_reference_rasters(paths, snakemake.params.source_grid)
shapes = validate_shapes(snakemake.input.shapes)
nuts3 = validate_nuts3(snakemake.input.nuts3)
totals = validate_floor_area_table(snakemake.input.totals, nuts3.nuts3_id)

with (
    rasterio.open(snakemake.input.residential) as residential,
    rasterio.open(snakemake.input.non_residential) as non_residential,
):
    proxies = (residential, non_residential)
    nuts3 = nuts3.to_crs(residential.crs)
    scope = scope_geometry(shapes, residential.crs)
    geometries = nuts3.geometry.intersection(scope)
    proxy_sums = [
        [raster_sum(proxy, geometry) for geometry in geometries] for proxy in proxies
    ]
    for sector, sums in zip(SECTORS, proxy_sums, strict=True):
        validate_scaling_support(totals[f"{sector}_m2"].to_numpy(), sums)

    output, base_window = create_output(
        snakemake.output.raster,
        residential,
        shapes.to_crs(residential.crs).total_bounds,
        snakemake.params.raster,
    )
    with output:
        for band, (sector, proxy) in enumerate(zip(SECTORS, proxies, strict=True), 1):
            for nuts3_id, geometry in zip(nuts3.nuts3_id, geometries, strict=True):
                write_scaled(
                    output,
                    band,
                    proxy,
                    base_window,
                    geometry,
                    totals.loc[nuts3_id, f"{sector}_m2"],
                )
        finish_raster(
            output,
            RASTER_BANDS,
            ("m2/ha",) * 3,
            {
                "residential_reference_year": 2021,
                "non_residential_reference_year": 2015,
                "regionalisation": "Muller_et_al_2019_composite_indicators",
            },
        )

validate_density_raster(
    snakemake.output.raster, snakemake.params.raster, ("m2/ha",) * 3
)
