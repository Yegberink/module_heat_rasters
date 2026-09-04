We recommend consulting the following before using this module:
- `config/config.yaml`: a generic example configuration of this module.
- `workflow/internal/config.schema.yaml`: a schematic overview of all the configuration options of this module.
- `INTERFACE.yaml`: lists module input and output files, and their default locations.
- `tests/integration/Snakefile`: an example of how to call this module from another workflow.

This data module is part of the [Modelblocks](https://www.modelblocks.org/) project.
Please consult the [Modelblocks documentation](https://modelblocks.readthedocs.io/) for more details.

`data_proxies.microsoft.countries` is keyed by the target ISO3 country. Each
country independently selects a `floor_area` method and a `sector_split` method.
`reference_countries` branches require only ISO3 references; `user_specified`
branches require only the metrics belonging to the selected estimator. The
example configuration documents both forms. Population is used to estimate
dwelling counts for `area_per_dwelling`, but Microsoft footprints—not
population—always provide the fallback spatial weights.

When `mean_floors` uses reference countries, the configured EUBUCCO floor-bin
representatives convert published regional bin counts into an effective mean
without downloading the reference countries' building files.
