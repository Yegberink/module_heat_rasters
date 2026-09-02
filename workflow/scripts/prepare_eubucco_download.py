"""Plan the smallest suitable EUBUCCO v0.2 acquisition for a shape case.

EUBUCCO uses NUTS 2016 region identifiers, whereas this workflow operates on a
current NUTS-3 layer. Metadata polygons provide an explicit spatial crosswalk.
For the resulting legacy regions, the script compares the projected compressed
bytes of relevant NUTS-2 footprint files with the size of the Europe-wide
lightweight centroid file. The configured strategy and all decision inputs are
stored in a validated JSON manifest for reproducibility.

Sources:
    EUBUCCO access formats: https://docs.eubucco.com/v0.2/data-access/website/
    EUBUCCO metadata files: https://docs.eubucco.com/v0.2/data-format/metadata/
"""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow.fs as fs
from _eubucco import choose_strategy, map_regions, parquet_bytes
from _schemas import (
    validate_eubucco_nuts,
    validate_eubucco_plan,
    validate_eubucco_stats,
    validate_nuts3,
)

if TYPE_CHECKING:
    snakemake: Any


sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.settings
sources = snakemake.params.sources
nuts3 = validate_nuts3(snakemake.input.nuts3).to_crs("EPSG:3035")

# Small metadata tables are required to relate current NUTS-3 polygons to the
# legacy regional partitions used by EUBUCCO 0.2.
for url, output in [
    (sources["eubucco_nuts"], snakemake.output.eubucco_nuts),
    (sources["eubucco_stats"], snakemake.output.eubucco_stats),
]:
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "3",
            "--output",
            output,
            url.format(version=settings["version"]),
        ],
        check=True,
    )
regions = validate_eubucco_nuts(snakemake.output.eubucco_nuts).to_crs("EPSG:3035")
stats = validate_eubucco_stats(snakemake.output.eubucco_stats)
mapping = map_regions(nuts3, regions, stats.region_id)
nuts2_ids = sorted(
    {nuts2 for region in mapping.values() for nuts2 in region["nuts2_ids"]}
)
filesystem = fs.S3FileSystem(
    anonymous=True, endpoint_override=sources["eubucco_endpoint"]
)

# Estimate projected Parquet bytes from remote metadata. This avoids
# downloading either large building representation merely to choose between them.
paths = [
    sources["eubucco_buildings"].format(
        version=settings["version"], nuts2=nuts2
    )
    for nuts2 in nuts2_ids
]
with ThreadPoolExecutor(max_workers=8) as executor:
    regional_bytes = sum(executor.map(lambda path: parquet_bytes(filesystem, path), paths))
lightweight_path = sources["eubucco_lightweight_path"].format(
    version=settings["version"]
)
lightweight_bytes = filesystem.get_file_info(lightweight_path).size

# Record both the decision and its inputs so acquisition is reproducible.
plan = {
    "schema_version": 1,
    "eubucco_version": settings["version"],
    "requested_strategy": settings["source_strategy"],
    "selected_strategy": choose_strategy(
        settings["source_strategy"],
        regional_bytes,
        lightweight_bytes,
        settings["regional_max_fraction"],
    ),
    "regional_max_fraction": settings["regional_max_fraction"],
    "regional_estimated_bytes": regional_bytes,
    "lightweight_bytes": lightweight_bytes,
    "regions": mapping,
}
Path(snakemake.output.manifest).parent.mkdir(parents=True, exist_ok=True)
with open(snakemake.output.manifest, "w") as stream:
    json.dump(plan, stream, indent=2)
validate_eubucco_plan(snakemake.output.manifest)
