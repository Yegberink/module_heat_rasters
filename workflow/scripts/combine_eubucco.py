"""Combine canonical EUBUCCO batches into one deterministic local table.

All partitions are validated, externally sorted by region and building ID, and
written with fixed compression and row-group settings. Sorting makes results
independent of source-file and batch iteration order. A valid empty table is
written when the selected geography contains no EUBUCCO buildings.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from _eubucco import EUBUCCO_COLUMNS, EUBUCCO_SCHEMA
from _schemas import validate_eubucco_partition

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")

# Validate every intermediate partition before exposing them as one stable table.
partitions = sorted(Path(snakemake.input.partitions).glob("*.parquet"))
for partition in partitions:
    validate_eubucco_partition(partition)
Path(snakemake.output.table).parent.mkdir(parents=True, exist_ok=True)
if partitions:
    # DuckDB performs the external sort without loading all buildings into memory.
    columns = ", ".join(EUBUCCO_COLUMNS)
    source = Path(snakemake.input.partitions) / "*.parquet"
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute(
        f"""
        COPY (SELECT {columns} FROM read_parquet('{source}') ORDER BY region_id, id)
        TO '{snakemake.output.table}'
        (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)
        """
    )
else:
    # Preserve the canonical schema when the requested area contains no buildings.
    pq.write_table(pa.Table.from_batches([], schema=EUBUCCO_SCHEMA), snakemake.output.table)
validate_eubucco_partition(snakemake.output.table)
