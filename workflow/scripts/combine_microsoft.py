"""Combine canonical Microsoft tile partitions into one stable table."""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from _microsoft import MICROSOFT_COLUMNS, MICROSOFT_SCHEMA
from _schemas import validate_microsoft_partition

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
partitions = sorted(Path(snakemake.input.partitions).glob("*.parquet"))
for partition in partitions:
    validate_microsoft_partition(partition)
Path(snakemake.output.table).parent.mkdir(parents=True, exist_ok=True)
if partitions:
    columns = ", ".join(MICROSOFT_COLUMNS)
    source = Path(snakemake.input.partitions) / "*.parquet"
    duckdb.connect().execute(
        f"""COPY (SELECT {columns} FROM read_parquet('{source}') ORDER BY region_id, id)
        TO '{snakemake.output.table}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"""
    )
else:
    pq.write_table(pa.Table.from_batches([], schema=MICROSOFT_SCHEMA), snakemake.output.table)
validate_microsoft_partition(snakemake.output.table)
