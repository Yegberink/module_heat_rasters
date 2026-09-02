We recommend consulting the following before using this module:
- `config/config.yaml`: a generic example configuration of this module.
- `workflow/internal/config.schema.yaml`: a schematic overview of all the configuration options of this module.
- `INTERFACE.yaml`: lists module input and output files, and their default locations.
- `tests/integration/Snakefile`: an example of how to call this module from another workflow.

`floor_area.eubucco.source_strategy` defaults to `auto`, which compares the
required regional EUBUCCO transfer with the Europe-wide lightweight parquet.
Set it to `regional` or `lightweight` to force either route. In automatic mode,
regional extraction is selected only when its estimated size is at most
`regional_max_fraction` of the lightweight file size.

This data module is part of the [Modelblocks](https://www.modelblocks.org/) project.
Please consult the [Modelblocks documentation](https://modelblocks.readthedocs.io/) for more details.
