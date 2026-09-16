# Floor-area and residential space-heating support rasters

This module jointly produces floor-area rasters and residential space-heating
support for spatial energy-system analysis.

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
2. Allocate totals with EUBUCCO buildings, falling back by complete region and sector to Microsoft level-nine footprints and replacing sparse Microsoft tiles with GHS-POP support.
3. Estimate totals outside Eurostat coverage from configurable reference-country or explicit dwelling/floor assumptions.
4. Load each building batch once and save physical floor area together with
   population and additive residential compactness support on the 100 m grid.
5. Aggregate country compactness references from batch summaries, then calculate
   residential heat weights from the saved rasters and construction-age data.
6. Merge both public TIFFs in one `merge_heat_rasters` job. Commercial/public
   floor area has no heat-weight counterpart.

The shared pipeline retains compressed float64 intermediates under
`resources/automatic/{shapes}/heat_rasters/`. Complete-region support preserves
normalisation and diagnostics; scoped support preserves building-centroid and
population-cell-centre clipping. Changing age factors or the population blend
reuses these intermediates. Changing compactness settings rebuilds support.

Workflow code is grouped by processing stage:

- `download.py` downloads sources and validates them once using `_schemas.py`.
  User shapes and EUBUCCO metadata are checked when first ingested by `prepare.py`.
  Downstream jobs trust generated files; they do not rescan them for validation.
- `prepare.py` contains separately scheduled functions for shapes, regions,
  source planning, batch planning, floor-area totals, age factors and compactness
  references. Sharing a script does not serialize these jobs.
- `process_eubucco.py` and `process_microsoft.py` each convert and combine their
  source in one job, using temporary partitions for bounded memory.
- `calculate_floor_area.py` and `weighted_floor_area.py` run per balanced batch.
  Downloads and regional batches retain their independent parallel jobs.
- `sources.smk` defines acquisition and source preparation; `floor_area.smk`
  includes the final merge; `space_heat_weight.smk` defines weighting.

Configuration validation and mathematical preconditions (for example, a
positive denominator when scaling a nonzero total) remain in place.

The outputs have deliberately different meanings:

- `floor_area.tif` contains reconstructed physical residential and
  commercial/public gross floor area in `m2/ha`.
- `residential_space_heat_weight.tif` contains area-like spatial support in
  `weighted_m2/ha`. It is not heat demand in MWh; the floor-area/population blend
  is normalised within NUTS-3 before the heat corrections are applied. A
  downstream workflow must normalise it over all shapes or cells in a
  country before multiplying it by the authoritative national household
  space-heating total.

The configurable lightweight EUBUCCO source uses the `equivalent_square`
compactness approximation. The full source downloads required NUTS-2 footprint
partitions and supports observed `footprint_perimeter`; the selected method is
recorded in raster metadata. Missing/invalid height and missing observed
Eurostat age data are neutral corrections of one. Microsoft fallback regions
receive no compactness correction.

## Configuration
<!-- Please describe how to configure this module below -->

Please consult the configuration [README](./config/README.md) and the [configuration example](./config/config.yaml) for a general overview on the configuration options of this module.

## Input / output structure
<!-- Please describe input / output file placement below -->

Please consult the [interface file](./INTERFACE.yaml) for more information.

Final TIFFs are saved in `results/{shapes}/rasters/` and diagnostic plots in
`results/{shapes}/visualiation/`. For `working_EU`, the floor-area result is
`results/working_EU/rasters/floor_area.tif`.

Import this module and request either public path from the consumer workflow:

```python
module heat_rasters:
    snakefile: "path/to/module_heat_rasters/workflow/Snakefile"
    pathvars:
        resources="resources",
        results="results",
        logs="logs"

use rule * from heat_rasters as heat_rasters_*
```

For example, run `snakemake results/working_EU/rasters/floor_area.tif --cores 4`
after providing `resources/user/working_EU/shapes.parquet`. Requesting either
missing TIFF produces both TIFFs, all three plots, and residential diagnostics.
The module has no `rule all`. With standard Snakemake output semantics, requesting
an already-current TIFF does not restore a manually deleted partner; request
the missing TIFF to rebuild the pair.

The inherited integration tests still reference the template interface and its
placeholder `rule all`; they have not been migrated to this pipeline.

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
