"""Stream Microsoft GeoJSONL tiles into validated control-region points."""

import gzip
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pyarrow as pa
import pyarrow.parquet as pq
from _eubucco import read_plan
from _microsoft import (
    MICROSOFT_SCHEMA,
    MICROSOFT_TILE_STATISTICS_SCHEMA,
    tile_statistics,
)
from _schemas import (
    validate_microsoft_feature,
    validate_microsoft_partition,
    validate_microsoft_tile_statistics,
    validate_nuts3,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
plan = read_plan(snakemake.input.plan)
regions = validate_nuts3(snakemake.input.regions).set_index("region_id")
selected = [
    region_id
    for region_id, settings in plan["regions"].items()
    if "microsoft" in {settings["residential_source"], settings["commercial_source"]}
]
targets = regions.loc[selected, ["geometry"]]
output = Path(snakemake.output.partitions)
output.mkdir(parents=True, exist_ok=True)
planned_quadkeys = sorted(
    {
        key
        for region_id in selected
        for key in plan["regions"][region_id]["microsoft_quadkeys"]
    }
)


def write_batch(source, key, batch_number, ids, geometries):
    """Project, assign and persist one bounded GeoJSONL batch."""
    footprints = gpd.GeoDataFrame({"id": ids}, geometry=geometries, crs=4326).to_crs(
        regions.crs
    )
    points = footprints.copy()
    points.geometry = footprints.centroid
    assigned = gpd.sjoin(points, targets, predicate="within", how="inner")
    assigned["fallback"] = assigned.region_id.str.startswith("shape-")
    assigned = assigned.sort_values(
        ["id", "fallback", "region_id"], ascending=[True, False, True]
    ).drop_duplicates("id")
    if assigned.empty:
        return
    area = footprints.geometry.area.reindex(assigned.index)
    table = pa.Table.from_arrays(
        [
            pa.array(assigned.id),
            pa.array([key] * len(assigned)),
            pa.array(assigned.region_id),
            pa.array(area),
            pa.array(assigned.geometry.x),
            pa.array(assigned.geometry.y),
        ],
        schema=MICROSOFT_SCHEMA,
    )
    path = output / f"{source.stem}-{batch_number}.parquet"
    pq.write_table(table, path, compression="zstd", row_group_size=100_000)
    validate_microsoft_partition(path)


source_counts = []
for source in sorted(Path(source) for source in snakemake.input.downloads):
    key = source.name[:9]
    assert key in planned_quadkeys
    ids, geometries = [], []
    raw_count = 0
    batch_number = 0
    with gzip.open(source, "rt") as stream:
        for line_number, line in enumerate(stream):
            raw_count += 1
            feature = json.loads(line)
            ids.append(f"{source.stem}:{line_number}")
            geometries.append(validate_microsoft_feature(feature))
            if len(ids) == 100_000:
                write_batch(source, key, batch_number, ids, geometries)
                ids, geometries = [], []
                batch_number += 1
    if ids:
        write_batch(source, key, batch_number, ids, geometries)
    source_counts.append((key, raw_count))

statistics = tile_statistics(planned_quadkeys, source_counts)
pq.write_table(
    pa.Table.from_pandas(
        statistics, schema=MICROSOFT_TILE_STATISTICS_SCHEMA, preserve_index=False
    ),
    snakemake.output.statistics,
)
validate_microsoft_tile_statistics(snakemake.output.statistics, planned_quadkeys)
