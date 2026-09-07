"""Download one pinned Microsoft building tile."""

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from _schemas import validate_microsoft_index

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
destination = Path(snakemake.output.table)
if destination.exists():
    sys.exit()
links = validate_microsoft_index(snakemake.input.index)
urls = sorted(links.loc[links.QuadKey.eq(snakemake.wildcards.quadkey), "Url"])
destination.parent.mkdir(parents=True, exist_ok=True)
partial = destination.with_suffix(".gz.part")
subprocess.run(
    [
        "curl", "-fL", "--retry", "3", "--continue-at", "-",
        "--output", partial, urls[int(snakemake.wildcards.part)],
    ],
    check=True,
    stderr=sys.stderr,
)
partial.replace(destination)
