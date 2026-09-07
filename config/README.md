We recommend consulting the following before using this module:
- `config/config.yaml`: a generic example configuration of this module.
- `workflow/internal/config.schema.yaml`: a schematic overview of all the configuration options of this module.
- `INTERFACE.yaml`: lists module input and output files, and their default locations.
- `tests/integration/Snakefile`: an example of how to call this module from another workflow.

This data module is part of the [Modelblocks](https://www.modelblocks.org/) project.
Please consult the [Modelblocks documentation](https://modelblocks.readthedocs.io/) for more details.

`data_proxies.method` selects one method shared by all proxied countries.
`data_proxies.countries` maps each target ISO3 country to one or more reference
countries, averaged with equal weight. With `mean_floors`, EUBUCCO floor bins
provide effective storeys and sector shares, while processed Eurostat totals and
GHS-POP provide residential floor area per inhabitant. Microsoft footprints
preserve the target country's building pattern and are scaled at country level
to that reference-derived residential total.

`space_heat_weight` controls the additive residential space-heating support
workflow. `buildings_eubucco.source: lightweight` uses the Europe-wide centroid
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
