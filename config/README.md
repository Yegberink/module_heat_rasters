We recommend consulting the following before using this module:
- `config/config.yaml`: a generic example configuration of this module.
- `workflow/internal/config.schema.yaml`: a schematic overview of all the configuration options of this module.
- `INTERFACE.yaml`: lists module input and output files, and their default locations.
- `README.md`: the current module import and output-target example.

This data module is part of the [Modelblocks](https://www.modelblocks.org/) project.
Please consult the [Modelblocks documentation](https://modelblocks.readthedocs.io/) for more details.

`data_proxies.method` selects one method shared by all proxied countries.
`data_proxies.countries` maps each target ISO3 country to one or more reference
countries, averaged with equal weight. With `mean_floors`, EUBUCCO floor bins
provide effective storeys and sector shares, while processed Eurostat totals and
GHS-POP provide residential floor area per inhabitant. Microsoft footprints
preserve the target country's building pattern and are scaled at country level
to that reference-derived residential total.
`buildings_microsoft.minimum_building_count` replaces Microsoft tiles below the
configured raw-feature count with regional GHS-POP floor-area support. A value
of zero disables this coverage fallback.

`space_heat_weight` controls residential space-heating support derived from
the shared floor-area intermediates. Its `population.share` blends normalised
residential floor-area and GHS-POP cell shares within each complete NUTS-3 region. Sum resampling is
reconciled to the validated regional population total after projection.
Population-only cells receive a neutral compactness factor.
`buildings_eubucco.source: lightweight`
uses the Europe-wide centroid
table and requires `surface_volume.method: equivalent_square`. Set the source to
`full` and the method to `footprint_perimeter` to download only the required
NUTS-2 footprint partitions and calculate observed perimeters. EUBUCCO
partitions and Microsoft tiles are persistent update outputs outside the
shape-specific directories, so workflow changes never redownload existing files.
The live
Eurostat `cens_21dwop_r3` source combines 1981--2000, so
`age.cutoff_spanning_bin_multipliers.Y1981-2000` records the explicit equal-decade
blend across the requested 1991 boundary. Missing height and age observations
remain neutral; neither is proxied from another country. The diagnostic
`coverage_fraction` preserves Eurostat's reported known-period sum divided by
its separately reported total; small source inconsistencies can therefore
produce values marginally above one and are not clipped.

`processing.nuts3_batches` sets the maximum number of shared balanced batches
(default `128`). It replaces both `buildings_eubucco.nuts3_batches` and
`space_heat_weight.nuts3_batches`; remove those old keys from consumer configs.
`processing.intermediate_dtype: float64` preserves precision in persistent
support rasters. Final TIFF precision remains controlled by `raster.dtype`.

Each batch retains a regional two-band floor-area TIFF, complete-region
residential support (floor area, population, valid compactness area, and area
multiplied by compactness power), scoped residential support (the last three
bands), and a regional summary table. Commercial/public area is never weighted.
Age and population-blend changes reuse saved support; compactness method or
elasticity changes rebuild it. Downloads and processed building tables retain
their paths; the new `heat_rasters` intermediate directory separates this
pipeline from old independently generated batches.
