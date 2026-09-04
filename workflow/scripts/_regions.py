"""Control-region geography shared by preparation scripts."""

import geopandas as gpd
from shapely.geometry import box


def processing_crs(shapes: gpd.GeoDataFrame) -> str:
    """Choose European LAEA only when the complete WGS84 scope lies in Europe."""
    europe = box(-35, 24, 45, 72)
    return (
        "EPSG:3035"
        if europe.covers(shapes.to_crs(4326).geometry.union_all())
        else "ESRI:54009"
    )
