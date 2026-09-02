"""Create one canonical building table from either EUBUCCO representation.

Only buildings assigned to legacy NUTS-3 regions intersecting the requested
case are retained. Regional footprints yield area and centroid coordinates
geometrically in EPSG:3035; the lightweight table supplies area directly and
has its WGS84 centroids projected to EPSG:3035. Batch processing bounds memory,
and every written Parquet partition is checked against the same strict schema.

Sources:
    EUBUCCO v0.2 schema: https://docs.eubucco.com/v0.2/data-format/schema/
    EUBUCCO data descriptor: https://doi.org/10.1038/s41597-023-02040-2
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from _eubucco import canonical_from_footprints, canonical_from_lightweight, read_plan
from _schemas import (
    validate_eubucco_footprints,
    validate_eubucco_lightweight,
    validate_eubucco_partition,
)
from pyproj import Transformer

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
plan = read_plan(snakemake.input.plan)
downloads = Path(snakemake.input.downloads)
output = Path(snakemake.output.partitions)
output.mkdir(parents=True, exist_ok=True)

# Limit both source strategies to legacy regions intersecting the requested
# current NUTS-3 geography.
region_ids = sorted(
    {region for mapping in plan["regions"].values() for region in mapping["region_ids"]}
)
selected = pa.array(region_ids)
if plan["selected_strategy"] == "regional":
    # Footprint geometry supplies both area and centroid coordinates. Process
    # batches to keep peak memory independent of source-file size.
    sources = sorted(downloads.glob("*.parquet"))
    for source in sources:
        validate_eubucco_footprints(source)
        parquet = pq.ParquetFile(source)
        for index, batch in enumerate(
            parquet.iter_batches(
                batch_size=250_000,
                columns=["id", "region_id", "type", "subtype", "floors", "geometry"],
            )
        ):
            filtered = batch.filter(pc.is_in(batch.column("region_id"), selected))
            table = canonical_from_footprints(filtered)
            if not table.num_rows:
                continue
            pq.write_table(
                table,
                output / f"{source.stem}-{index}.parquet",
                compression="zstd",
                row_group_size=100_000,
            )
else:
    # The lightweight source already stores footprint area and centroid
    # coordinates; only the coordinates need projection to EPSG:3035.
    source = downloads / "eubucco_lat_lon.parquet"
    validate_eubucco_lightweight(source)
    transformer = Transformer.from_crs(4326, 3035, always_xy=True)
    parquet = pq.ParquetFile(source)
    columns = [
        "id",
        "region_id",
        "type",
        "subtype",
        "floors",
        "footprint_area",
        "lon",
        "lat",
    ]
    for index, batch in enumerate(
        parquet.iter_batches(batch_size=250_000, columns=columns)
    ):
        filtered = pa.Table.from_batches(
            [batch.filter(pc.is_in(batch.column("region_id"), selected))]
        )
        if not filtered.num_rows:
            continue
        pq.write_table(
            canonical_from_lightweight(filtered, transformer),
            output / f"part-{index}.parquet",
            compression="zstd",
            row_group_size=100_000,
        )
# Validate the canonical schema after every source-specific transformation.
for partition in output.glob("*.parquet"):
    validate_eubucco_partition(partition)
