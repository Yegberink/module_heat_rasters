"""Download only Microsoft level-nine tiles selected by the source plan."""

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from _eubucco import read_plan
from _schemas import validate_microsoft_index

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
plan = read_plan(snakemake.input.plan)
quadkeys = {
    key
    for region in plan["regions"].values()
    for key in region["microsoft_quadkeys"]
}
links = validate_microsoft_index(snakemake.input.index)
links = links.loc[links.QuadKey.isin(quadkeys)].sort_values(["QuadKey", "Url"])
directory = Path(snakemake.output.downloads)
directory.mkdir(parents=True, exist_ok=True)
for index, row in enumerate(links.itertuples(index=False)):
    destination = directory / f"{row.QuadKey}-{index:05d}.csv.gz"
    partial = destination.with_suffix(".gz.part")
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
            row.Url,
        ],
        check=True,
    )
    partial.replace(destination)
