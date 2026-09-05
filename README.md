# Floor-area and residential space-heating support rasters

This module develops floor-area rasters and a separate support raster for
spatial energy-system analysis.

<!-- Place an attractive image of module outputs here -->
<p align="center">
  <img src="./figures/module.png" width="75%">
</p>


## About
<!-- Please do not modify this templated section -->

This is a modular `snakemake` workflow created as part of the [Modelblocks project](https://www.modelblocks.org/). It can be imported directly into any `snakemake` workflow.

For more information, please consult the Modelblocks [documentation](https://modelblocks.readthedocs.io/en/latest/),
the [integration example](./tests/integration/Snakefile),
and the `snakemake` [documentation](https://snakemake.readthedocs.io/en/stable/snakefiles/modularization.html).

## Overview
<!-- Please describe the processing stages of this module here -->

Data processing steps:

1. Reconstruct NUTS-3 residential floor-area totals from Eurostat where available.
2. Allocate totals with EUBUCCO buildings, falling back by complete region and sector to only the required Microsoft level-nine footprint tiles.
3. Estimate totals outside Eurostat coverage from configurable reference-country or explicit dwelling/floor assumptions.
4. Reconstruct the residential floor support independently, apply
   country-centred building compactness and NUTS-3 construction-age corrections,
   and rasterise the result to the same 100 m grid.

The outputs have deliberately different meanings:

- `floor_area.tif` contains reconstructed physical residential and
  commercial/public gross floor area in `m2/ha`.
- `residential_space_heat_weight.tif` contains area-like spatial support in
  `weighted_m2/ha`. It is not heat demand in MWh and is not normalised within
  NUTS-3. A downstream workflow must normalise it over all shapes or cells in a
  country before multiplying it by the authoritative national household
  space-heating total.

EUBUCCO's lightweight table has no footprint perimeter, so compactness uses the
configured `equivalent_square` approximation and records that method in raster
metadata. Missing/invalid height and missing observed Eurostat age data are
neutral corrections of one. Microsoft fallback regions receive no compactness
correction. HDD is represented in the configuration and helper API but disabled.

## Configuration
<!-- Please describe how to configure this module below -->

Please consult the configuration [README](./config/README.md) and the [configuration example](./config/config.yaml) for a general overview on the configuration options of this module.

## Input / output structure
<!-- Please describe input / output file placement below -->

Please consult the [interface file](./INTERFACE.yaml) for more information.

Final TIFFs are saved in `results/{shapes}/rasters/` and diagnostic plots in
`results/{shapes}/visualiation/`. For `working_EU`, the floor-area result is
`results/working_EU/rasters/floor_area.tif`.

## Development
<!-- Please do not modify this templated section -->

We use [`pixi`](https://pixi.sh/) as our package manager for development.
Once installed, run the following to clone this repository and install all dependencies.

```shell
git clone git@github.com:modelblocks-org/module_heat_rasters.git
cd module_heat_rasters
pixi install --all
```

Please be aware that this is a multi-environment project (see [pixi.toml](./pixi.toml) for details).
- `default`: used for development and integration testing.
Because it contains `Snakemake`, `conda` and `pytest` as dependencies it **should not be used** in `Snakemake` rules.
- `module`: contains minimal dependencies used in `Snakemake` rules.
If modified, be sure to export it to `Snakemake` so it can be recreated by module users:

```shell
# create module.yaml and conda-spec pin files in workflow/envs/
pixi run export-snakemake-env module
```


## Testing
<!-- Please do not modify this templated section -->

For testing, simply run:

```shell
pixi run test-integration
```

To test a minimal example of a workflow using this module:

```shell
pixi shell    # activate this project's environment
cd tests/integration/  # navigate to the integration example
snakemake --use-conda --cores 2  # run the workflow!
```

## References
<!-- Please provide thorough referencing below -->

This module is based on the following research and datasets:

* Müller, A., Hummel, M., Kranzl, L., Fallahnejad, M., & Büchele, R. (2019). [Open Source Data for Gross Floor Area and Heat Demand Density on the Hectare Level for EU 28](https://doi.org/10.3390/en12244789). *Energies*, 12(24), 4789.
* [EUBUCCO v0.2](https://docs.eubucco.com/v0.2/).
* [Microsoft Global ML Building Footprints](https://github.com/microsoft/GlobalMLBuildingFootprints), CDLA Permissive 2.0.
* Eurostat Census 2021 [`cens_21dwop_r3`](https://ec.europa.eu/eurostat/databrowser/view/cens_21dwop_r3/default/table), conventional dwellings by construction period and NUTS-3 region.

## Contributors ✨

Thanks goes to these wonderful people, sorted alphabetically ([emoji key](https://allcontributors.org/en/reference/emoji-key/)):

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

This project follows the [all-contributors](https://github.com/all-contributors/all-contributors) specification. Contributions of any kind welcome!
