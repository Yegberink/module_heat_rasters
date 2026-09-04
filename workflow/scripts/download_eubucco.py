"""Download the pinned Europe-wide EUBUCCO building table.

Transfers use a ``.part`` suffix and curl continuation so interrupted runs can
resume safely.

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
destination = directory / "eubucco_lat_lon.parquet"
partial = destination.with_suffix(".parquet.part")
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
        snakemake.params.sources["eubucco_buildings"].format(
            version=plan["eubucco_version"]
        ),
    ],
    check=True,
)
partial.replace(destination)
