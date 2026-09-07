"""Create canonical points from the configured pinned EUBUCCO distribution.

Only buildings assigned to legacy NUTS-3 regions intersecting the requested
case are retained. Lightweight centroids are projected from WGS84; full
EPSG:3035 footprints are reduced to centroids, areas, and perimeters. Batch
processing bounds memory, and every partition uses the strict canonical schema.

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
from _eubucco import canonical_from_full, canonical_from_lightweight, read_plan
from _schemas import validate_eubucco_partition, validate_eubucco_source, validate_nuts3
from pyproj import Transformer

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
plan = read_plan(snakemake.input.plan)
regions = validate_nuts3(snakemake.input.regions)
output = Path(snakemake.output.partitions)
output.mkdir(parents=True, exist_ok=True)

# Limit the Europe-wide table to legacy regions intersecting the requested case.
region_ids = sorted(
    {
        region
        for mapping in plan["regions"].values()
        for region in mapping["eubucco_region_ids"]
        if "eubucco"
        in {mapping["residential_source"], mapping["commercial_source"]}
    }
)
selected = pa.array(region_ids)
if plan["eubucco_source"] == "lightweight":
    sources = [Path(source) for source in snakemake.input.downloads]
    columns = [
        "id", "region_id", "type", "subtype", "floors", "footprint_area",
        "height", "lon", "lat",
    ]
    transformer = Transformer.from_crs(4326, regions.crs, always_xy=True)
    convert = canonical_from_lightweight
else:
    sources = sorted(Path(source) for source in snakemake.input.downloads)
    columns = ["id", "region_id", "type", "subtype", "floors", "height", "geometry"]
    transformer = Transformer.from_crs(3035, regions.crs, always_xy=True)
    convert = canonical_from_full

for source in sources:
    validate_eubucco_source(source, plan["eubucco_source"])
    for index, batch in enumerate(
        pq.ParquetFile(source).iter_batches(batch_size=250_000, columns=columns)
    ):
        filtered = batch.filter(pc.is_in(batch.column("region_id"), selected))
        if not filtered.num_rows:
            continue
        pq.write_table(
            convert(filtered, transformer),
            output / f"{source.stem}-{index}.parquet",
            compression="zstd",
            row_group_size=100_000,
        )
for partition in output.glob("*.parquet"):
    validate_eubucco_partition(partition, plan["eubucco_source"])
