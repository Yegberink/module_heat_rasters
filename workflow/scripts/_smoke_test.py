"""Temporary synthetic smoke test for the regionalisation scripts."""

import runpy
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from shapely.geometry import box

scripts = Path(__file__).parent
sys.path.insert(0, str(scripts))
root = Path(tempfile.mkdtemp(prefix="district-heating-"))
shapes_path = root / "shapes.parquet"
nuts_source = root / "nuts.geojson"
nuts_path = root / "nuts.parquet"
census_path = root / "census.tsv.gz"
floor_table = root / "floor.parquet"
floor_raster = root / "floor.tif"
annual_path = root / "annual.parquet"
heat_table = root / "heat.parquet"
heat_raster = root / "heat.tif"
logs = [root / f"{name}.log" for name in ("prepare", "nuts_floor", "floor", "heat")]

shapes = gpd.GeoDataFrame(
    {
        "shape_id": ["left", "right"],
        "country_id": ["BEL", "NLD"],
        "shape_class": ["land", "land"],
    },
    geometry=[box(0, 0, 400, 400), box(400, 0, 800, 400)],
    crs="EPSG:3035",
)
shapes.to_parquet(shapes_path, index=False)
gpd.GeoDataFrame(
    {"NUTS_ID": ["AA001", "BB001"]},
    geometry=[box(0, 0, 400, 400), box(400, 0, 800, 400)],
    crs="EPSG:3035",
).to_file(nuts_source, driver="GeoJSON")

profile = {
    "driver": "GTiff",
    "width": 8,
    "height": 4,
    "count": 1,
    "dtype": "float32",
    "crs": "EPSG:3035",
    "transform": Affine(100, 0, 0, 0, -100, 400),
    "nodata": 0.0,
}
rasters = []
for name, value in (("gfa_res", 1), ("gfa_nonres", 2), ("heat_res", 3), ("heat_nonres", 4)):
    path = root / f"{name}.tif"
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(np.full((4, 8), value, dtype="float32"), 1)
    rasters.append(path)

rows = []
areas = ["SQM_LT30", "SQM30-39", "SQM40-49", "SQM50-59", "SQM60-79", "SQM80-99", "SQM100-119", "SQM120-149", "SQM_GE150"]
for geo in ("AA001", "BB001"):
    for area in areas:
        rows.append((f"A,{area},TOTAL,TOTAL,NR,{geo}", "10" if area == "SQM60-79" else "0"))
pd.DataFrame(rows, columns=["freq,area,n_room,building,unit,geo\\TIME_PERIOD", "2021 "]).to_csv(census_path, sep="\t", index=False)

index = pd.MultiIndex.from_tuples(
    [(2023, "space_heat", "household"), (2023, "hot_water", "household"), (2023, "space_heat", "commercial")],
    names=["year", "end_use", "cat_name"],
)
pd.DataFrame([[0.001, 0.002], [0.0005, 0.001], [0.0002, 0.0004]], index=index, columns=["left", "right"]).to_parquet(annual_path)

source_grid = {"crs": "EPSG:3035", "cell_size_m": 100, "bounds_m": [0, 0, 800, 400], "width": 8, "height": 4, "dtype": "float32", "nodata": 0.0}
raster_settings = {"cell_size_m": 100, "dtype": "float32", "nodata": 0.0, "compression": "deflate", "block_size": 16}
floor_settings = {"reference_year": 2021, "useful_to_gross_ratio": 1.2, "floor_space_m2": {area: value for area, value in zip(areas, [25, 35, 45, 55, 70, 90, 110, 135, 180], strict=True)}, "rooms": {str(i): i for i in range(1, 9)} | {"GE9": 10}, "floor_area_per_room_m2": 20}

def execute(script, **values):
    globals()["snakemake"] = SimpleNamespace(**values)
    runpy.run_path(scripts / script, init_globals={"snakemake": globals()["snakemake"]})

execute("prepare_nuts3.py", input=SimpleNamespace(shapes=str(shapes_path), nuts3=str(nuts_source)), output=SimpleNamespace(regions=str(nuts_path)), log=[str(logs[0])])
execute("create_nuts3_floor_area.py", input=SimpleNamespace(shapes=str(shapes_path), nuts3=str(nuts_path), census=str(census_path), residential_proxy=str(rasters[0]), non_residential_proxy=str(rasters[1])), output=SimpleNamespace(table=str(floor_table)), params=SimpleNamespace(floor_area=floor_settings, source_grid=source_grid), log=[str(logs[1])])
execute("create_floor_area.py", input=SimpleNamespace(shapes=str(shapes_path), nuts3=str(nuts_path), totals=str(floor_table), residential=str(rasters[0]), non_residential=str(rasters[1])), output=SimpleNamespace(raster=str(floor_raster)), params=SimpleNamespace(raster=raster_settings, source_grid=source_grid), log=[str(logs[2])])
execute("create_heat_demand.py", input=SimpleNamespace(shapes=str(shapes_path), nuts3=str(nuts_path), annual_demand=str(annual_path), residential_proxy=str(rasters[2]), non_residential_proxy=str(rasters[3])), output=SimpleNamespace(raster=str(heat_raster), nuts3=str(heat_table)), params=SimpleNamespace(heat_demand={"end_uses": ["space_heat", "hot_water"], "categories": {"household": "residential", "commercial": "non_residential"}}, raster=raster_settings, source_grid=source_grid), wildcards=SimpleNamespace(year="2023"), log=[str(logs[3])])

with rasterio.open(floor_raster) as raster:
    assert np.allclose([raster.read(1).sum(), raster.read(2).sum()], [1680, 64])
with rasterio.open(heat_raster) as raster:
    assert np.allclose([raster.read(1).sum(), raster.read(2).sum()], [4500, 600])
print(root)
