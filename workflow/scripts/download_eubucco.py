"""Download the EUBUCCO representation selected by the planning manifest.

Regional mode downloads only required NUTS-2 footprint partitions; lightweight
mode downloads the reusable Europe-wide centroid table. Transfers use a
``.part`` suffix and curl continuation so interrupted runs can resume safely.
Validation is deliberately deferred to ``process_eubucco.py``, which knows the
schema of each representation.

Source:
    EUBUCCO v0.2 downloads: https://eubucco.com/files/
"""

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from _eubucco import read_plan

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
plan = read_plan(snakemake.input.plan)
directory = Path(snakemake.output.downloads)
directory.mkdir(parents=True, exist_ok=True)

# The plan chooses either the relevant NUTS-2 footprint files or the single,
# Europe-wide lightweight point table.
if plan["selected_strategy"] == "regional":
    nuts2_ids = sorted(
        {nuts2 for region in plan["regions"].values() for nuts2 in region["nuts2_ids"]}
    )
    downloads = [
        (
            snakemake.params.sources["eubucco_buildings_url"].format(
                version=plan["eubucco_version"], nuts2=nuts2
            ),
            directory / f"{nuts2}.parquet",
        )
        for nuts2 in nuts2_ids
    ]
else:
    downloads = [
        (
            snakemake.params.sources["eubucco_lightweight"].format(
                version=plan["eubucco_version"]
            ),
            directory / "eubucco_lat_lon.parquet",
        )
    ]
for url, destination in downloads:
    if destination.exists():
        continue
    # Keep incomplete transfers separate and resumable; rename only on success.
    partial = destination.with_suffix(destination.suffix + ".part")
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "3",
            "--continue-at",
            "-",
            "--output",
            partial,
            url,
        ],
        check=True,
    )
    partial.replace(destination)
