"""Microsoft Global ML Building Footprints tiling and proxy calculations."""

import math

import pyarrow as pa
from shapely.geometry import box

MICROSOFT_COLUMNS = ["id", "region_id", "footprint_area_m2", "x", "y"]
MICROSOFT_SCHEMA = pa.schema(
    [
        ("id", pa.string()),
        ("region_id", pa.string()),
        ("footprint_area_m2", pa.float64()),
        ("x", pa.float64()),
        ("y", pa.float64()),
    ]
)


def tile_xy(lon: float, lat: float, zoom: int = 9) -> tuple[int, int]:
    """Return the Bing tile containing a WGS84 coordinate."""
    scale = 1 << zoom
    x = int((lon + 180) / 360 * scale)
    latitude = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = int((1 - math.asinh(math.tan(latitude)) / math.pi) / 2 * scale)
    return min(scale - 1, max(0, x)), min(scale - 1, max(0, y))


def quadkey(x: int, y: int, zoom: int = 9) -> str:
    """Encode Bing tile coordinates as a quadkey."""
    return "".join(
        str(((x & (1 << bit)) > 0) + 2 * ((y & (1 << bit)) > 0))
        for bit in range(zoom - 1, -1, -1)
    )

def tile_bounds(x: int, y: int, zoom: int = 9):
    """Return a WGS84 polygon for one Bing tile."""
    scale = 1 << zoom
    west, east = x / scale * 360 - 180, (x + 1) / scale * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / scale))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / scale))))
    return box(west, south, east, north)


def intersecting_quadkeys(geometry, zoom: int = 9) -> list[str]:
    """Return only level-nine Bing tiles intersecting a WGS84 geometry."""
    west, south, east, north = geometry.bounds
    left, top = tile_xy(west, north, zoom)
    right, bottom = tile_xy(east, south, zoom)
    return sorted(
        quadkey(x, y, zoom)
        for x in range(left, right + 1)
        for y in range(top, bottom + 1)
        if tile_bounds(x, y, zoom).intersects(geometry)
    )
