"""Plan EUBUCCO-first building acquisition for one shape case."""

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from _eubucco import EUBUCCO_SCHEMA, map_regions, needs_eubucco_metadata
from _microsoft import MICROSOFT_SCHEMA, intersecting_quadkeys
from _schemas import (
    validate_eubucco_nuts,
    validate_eubucco_plan,
    validate_eubucco_stats,
    validate_microsoft_index,
    validate_microsoft_partition,
    validate_nuts3,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
regions = validate_nuts3(snakemake.input.regions)
target_countries = set(regions.country_id)
use_eubucco = needs_eubucco_metadata(
    target_countries,
    snakemake.params.microsoft,
    snakemake.params.eubucco_countries,
)
metadata = [snakemake.output.eubucco_nuts, snakemake.output.eubucco_stats]

if use_eubucco:
    urls = [
        snakemake.params.sources["eubucco_nuts"],
        snakemake.params.sources["eubucco_stats"],
    ]
    for url, output in zip(urls, metadata, strict=True):
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "curl",
                "-fL",
                "--retry",
                "3",
                "--output",
                output,
                url.format(version=snakemake.params.eubucco_version),
            ],
            check=True,
        )
    eubucco_regions = validate_eubucco_nuts(metadata[0]).to_crs(regions.crs)
    stats = validate_eubucco_stats(metadata[1])
    mapping = map_regions(regions, eubucco_regions, stats.region_id)
else:
    mapping = {
        region_id: {"region_ids": [], "nuts2_ids": []}
        for region_id in regions.region_id
    }
    Path(metadata[0]).parent.mkdir(parents=True, exist_ok=True)
    gpd.GeoDataFrame(
        {"region_id": pd.Series(dtype=str)}, geometry=[], crs="EPSG:3035"
    ).to_parquet(metadata[0], index=False)
    gpd.GeoDataFrame(
        {
            "region_id": pd.Series(dtype=str),
            "country": pd.Series(dtype=str),
            "n": pd.Series(dtype=float),
            "floor_area_type_residential": pd.Series(dtype=float),
            "n_floors_0_2": pd.Series(dtype=float),
            "n_floors_2_4": pd.Series(dtype=float),
            "n_floors_4_7": pd.Series(dtype=float),
            "n_floors_7_inf": pd.Series(dtype=float),
            "floor_area_subtype_commercial": pd.Series(dtype=float),
            "floor_area_subtype_public": pd.Series(dtype=float),
        },
        geometry=[],
        crs="EPSG:3035",
    ).to_parquet(metadata[1], index=False)
    stats = validate_eubucco_stats(metadata[1])

stats = stats.set_index("region_id")
region_plan = {}
needs_microsoft = False
for row in regions.to_crs(4326).itertuples():
    eubucco = mapping[row.region_id]
    selected = stats.reindex(eubucco["region_ids"])
    residential = selected.floor_area_type_residential.sum() > 0
    commercial = (
        selected.floor_area_subtype_commercial.sum()
        + selected.floor_area_subtype_public.sum()
        > 0
    )
    microsoft = not residential or not commercial
    if microsoft:
        assert row.country_id in snakemake.params.microsoft["countries"]
    needs_microsoft |= microsoft
    region_plan[row.region_id] = {
        "eubucco_region_ids": eubucco["region_ids"],
        "eubucco_nuts2_ids": eubucco["nuts2_ids"],
        "residential_source": "eubucco" if residential else "microsoft",
        "commercial_source": "eubucco" if commercial else "microsoft",
        "microsoft_quadkeys": intersecting_quadkeys(row.geometry) if microsoft else [],
    }

Path(snakemake.output.microsoft_index).parent.mkdir(parents=True, exist_ok=True)
if needs_microsoft:
    subprocess.run(
        [
            "curl",
            "-fL",
            "--retry",
            "3",
            "--output",
            snakemake.output.microsoft_index,
            snakemake.params.sources["microsoft_index"].format(
                release=snakemake.params.microsoft["release"]
            ),
        ],
        check=True,
    )
else:
    pd.DataFrame(columns=["Location", "QuadKey", "Url"]).to_csv(
        snakemake.output.microsoft_index, index=False
    )
validate_microsoft_index(snakemake.output.microsoft_index)

plan = {
    "schema_version": 1,
    "eubucco_version": snakemake.params.eubucco_version,
    "microsoft_release": snakemake.params.microsoft["release"],
    "crs": regions.crs.to_string(),
    "regions": region_plan,
}
Path(snakemake.output.manifest).parent.mkdir(parents=True, exist_ok=True)
with open(snakemake.output.manifest, "w") as stream:
    json.dump(plan, stream, indent=2)
pq.write_table(pa.Table.from_batches([], schema=EUBUCCO_SCHEMA), snakemake.output.empty_eubucco)
pq.write_table(pa.Table.from_batches([], schema=MICROSOFT_SCHEMA), snakemake.output.empty_microsoft)
validate_microsoft_partition(snakemake.output.empty_microsoft)
validate_eubucco_plan(snakemake.output.manifest)
