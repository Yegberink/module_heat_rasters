"""Shared EUBUCCO planning and canonical-table operations.

EUBUCCO v0.2 is available either as EPSG:3035 building footprints partitioned
by NUTS-2 or as one smaller Europe-wide table of centroids and footprint areas.
This module maps the legacy NUTS 2016 regions used by EUBUCCO to the workflow's
current NUTS-3 geography and converts both source representations to one local
schema. Keeping the schema independent of the selected download strategy makes
all downstream floor-area calculations identical.

Sources:
    EUBUCCO data and schema: https://docs.eubucco.com/v0.2/
    EUBUCCO data descriptor: https://doi.org/10.1038/s41597-023-02040-2
"""

import json
from pathlib import Path

import geopandas as gpd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import shapely

EUBUCCO_COLUMNS = [
    "id",
    "region_id",
    "type",
    "subtype",
    "floors",
    "footprint_area_m2",
    "x_3035",
    "y_3035",
]
SOURCE_COLUMNS = ["id", "region_id", "type", "subtype", "floors", "geometry"]
EUBUCCO_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("region_id", pa.string()),
        ("type", pa.string()),
        ("subtype", pa.string()),
        ("floors", pa.float64()),
        ("footprint_area_m2", pa.float64()),
        ("x_3035", pa.float64()),
        ("y_3035", pa.float64()),
    ]
)


def canonical_from_footprints(batch: pa.RecordBatch) -> pa.Table:
    """Convert footprint records to the canonical point schema.

    Footprint area and centroid coordinates are calculated in EUBUCCO's
    EPSG:3035 equal-area CRS. The centroid is subsequently used to assign each
    building to one NUTS-3 region and one hectare cell.
    """
    geometry = shapely.from_wkb(
        batch.column("geometry").to_numpy(zero_copy_only=False)
    )
    centroids = shapely.centroid(geometry)
    return pa.Table.from_arrays(
        [
            batch.column("id"),
            batch.column("region_id"),
            batch.column("type"),
            batch.column("subtype"),
            batch.column("floors"),
            pa.array(shapely.area(geometry)),
            pa.array(shapely.get_x(centroids)),
            pa.array(shapely.get_y(centroids)),
        ],
        schema=EUBUCCO_SCHEMA,
    )


def canonical_from_lightweight(table: pa.Table, transformer) -> pa.Table:
    """Convert lightweight longitude/latitude records to the canonical schema.

    The lightweight table already contains footprint area. Only its WGS84
    centroid coordinates are transformed to EPSG:3035.
    """
    x, y = transformer.transform(
        table["lon"].to_numpy(zero_copy_only=False),
        table["lat"].to_numpy(zero_copy_only=False),
    )
    return pa.Table.from_arrays(
        [
            pc.cast(table["id"], pa.string()),
            pc.cast(table["region_id"], pa.string()),
            pc.cast(table["type"], pa.string()),
            pc.cast(table["subtype"], pa.string()),
            pc.cast(table["floors"], pa.float64()),
            pc.cast(table["footprint_area"], pa.float64()),
            pa.array(x),
            pa.array(y),
        ],
        schema=EUBUCCO_SCHEMA,
    )


def choose_strategy(requested: str, regional: int, lightweight: int, fraction: float):
    """Choose the configured strategy or the cheaper automatic transfer.

    ``regional`` is selected automatically only when its estimated projected
    bytes do not exceed ``fraction * lightweight``. The threshold lets users
    account for the operational advantage of downloading one reusable file.
    """
    if requested == "auto":
        return "regional" if regional <= lightweight * fraction else "lightweight"
    return requested


def parquet_bytes(filesystem, path: str) -> int:
    """Estimate bytes read when projecting the required Parquet columns.

    The estimate adds the file metadata and compressed column-chunk sizes for
    only the source columns used by this workflow. It therefore approximates a
    range-capable object-store read rather than the complete Parquet file size.
    """
    metadata = pq.ParquetFile(path, filesystem=filesystem).metadata
    indices = [
        index
        for index in range(metadata.num_columns)
        if metadata.schema.column(index).path in SOURCE_COLUMNS
    ]
    return metadata.serialized_size + sum(
        metadata.row_group(row).column(column).total_compressed_size
        for row in range(metadata.num_row_groups)
        for column in indices
    )


def map_regions(
    nuts3: gpd.GeoDataFrame,
    eubucco_regions: gpd.GeoDataFrame,
    covered_regions,
) -> dict[str, dict[str, list[str]]]:
    """Map current NUTS-3 polygons to legacy EUBUCCO regions and files.

    A positive-area intersection is required, so regions that merely share a
    boundary are excluded. Each five-character legacy NUTS-3 ID also identifies
    its four-character NUTS-2 download partition.
    """
    legacy = eubucco_regions.loc[
        eubucco_regions.region_id.str.len().eq(5)
        & eubucco_regions.region_id.isin(covered_regions)
    ].set_index("region_id")
    mapping = {}
    for row in nuts3.itertuples():
        positions = legacy.sindex.query(row.geometry, predicate="intersects")
        candidates = legacy.iloc[positions]
        region_ids = sorted(
            candidates.index[
                candidates.geometry.intersection(row.geometry).area.gt(0)
            ].tolist()
        )
        mapping[row.nuts3_id] = {
            "region_ids": region_ids,
            "nuts2_ids": sorted({region_id[:4] for region_id in region_ids}),
        }
    return mapping


def read_plan(path: str | Path) -> dict:
    """Read an EUBUCCO planning manifest."""
    with open(path) as stream:
        return json.load(stream)
