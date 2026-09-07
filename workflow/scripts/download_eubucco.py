"""Download one pinned EUBUCCO building file.

Transfers use a ``.part`` suffix and curl continuation so interrupted runs can
resume safely.

Source:
    EUBUCCO v0.2 downloads: https://eubucco.com/files/
"""

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
destination = Path(snakemake.output.table)
if destination.exists():
    sys.exit()
destination.parent.mkdir(parents=True, exist_ok=True)
partial = destination.with_suffix(".parquet.part")
subprocess.run(
    [
        "curl", "-fL", "--retry", "3", "--continue-at", "-",
        "--output", partial, snakemake.params.url,
    ],
    check=True,
    stderr=sys.stderr,
)
partial.replace(destination)
