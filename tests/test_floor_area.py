"""Focused tests for floor-area building and scope selection."""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq
import shapely
from shapely.geometry import Polygon

sys.path.insert(0, str(Path(__file__).parents[1] / "workflow/scripts"))

from _eubucco import eubucco_batch_filter  # noqa: E402
from _floor_area import points_within_scope, select_building_sectors  # noqa: E402
from _schemas import validate_scope  # noqa: E402


def test_select_building_sectors_uses_eubucco_type_column():
    """The EUBUCCO column must win over GeoPandas' ``type`` property."""
    buildings = gpd.GeoDataFrame(
        {
            "type": ["residential", "non-residential", "non-residential"],
            "subtype": ["detached", "commercial", "public"],
        },
        geometry=gpd.points_from_xy([0, 1, 2], [0, 1, 2]),
    )

    residential, commercial = select_building_sectors(
        buildings, "residential", ["commercial", "public"]
    )

    assert residential.index.tolist() == [0]
    assert commercial.index.tolist() == [1, 2]


def test_points_within_scope_preserves_strict_boundary_semantics():
    """Prepared XY containment must exclude exterior and boundary points."""
    scope = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)], holes=[[(4, 4), (6, 4), (6, 6), (4, 6)]]
    )
    buildings = gpd.GeoDataFrame(
        {"x_3035": [1, 11, 0, 5, 4], "y_3035": [1, 1, 5, 5, 5]},
        geometry=gpd.points_from_xy([1, 11, 0, 5, 4], [1, 1, 5, 5, 5]),
        crs="EPSG:3035",
    )
    shapely.prepare(scope)

    actual = points_within_scope(buildings, scope)

    assert np.array_equal(actual, buildings.geometry.within(scope))
    assert actual.tolist() == [True, False, False, False, False]


def test_eubucco_batch_filter_keeps_inclusive_bounds_and_legacy_regions(tmp_path):
    """The scan filter must retain boundary coordinates in allowed regions."""
    path = tmp_path / "buildings.parquet"
    pq.write_table(
        pa.table(
            {
                "row": [0, 1, 2, 3, 4],
                "region_id": ["AA001", "AA001", "AA001", "AA001", "BB001"],
                "x_3035": [0.0, 10.0, -0.1, 5.0, 5.0],
                "y_3035": [0.0, 10.0, 5.0, 10.1, 5.0],
            }
        ),
        path,
    )

    selected = ds.dataset(path, format="parquet").to_table(
        filter=eubucco_batch_filter(["AA001"], (0, 0, 10, 10))
    )

    assert selected["row"].to_pylist() == [0, 1]


def test_validate_scope_requires_one_epsg3035_geometry(tmp_path):
    """A one-row EPSG:3035 scope artifact passes its throughput schema."""
    path = tmp_path / "scope.parquet"
    expected = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    gpd.GeoDataFrame(geometry=[expected], crs="EPSG:3035").to_parquet(path, index=False)

    actual = validate_scope(path)

    assert actual.geometry.item().equals(expected)
