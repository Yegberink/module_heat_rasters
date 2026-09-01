"""Create Census- and EUBUCCO-based hectare floor-area grids."""

import math
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as fs
import rasterio
import rioxarray
from _plots import plot_floor_area
from _schemas import (
    FLOOR_AREA_BANDS,
    validate_census,
    validate_density_raster,
    validate_eubucco_buildings,
    validate_eubucco_nuts,
    validate_eubucco_stats,
    validate_nuts3,
    validate_nuts3_source,
    validate_plot,
    validate_population_raster,
    validate_scaling_support,
    validate_shapes,
)
from affine import Affine
from gregor.aggregate import aggregate_point_to_polygon, aggregate_raster_to_polygon
from rasterio.enums import Resampling
from rasterio.features import geometry_mask, geometry_window
from rasterio.vrt import WarpedVRT
from rasterio.windows import Window
from shapely import box

if TYPE_CHECKING:
    snakemake: Any


def census_values(path: str, year: int) -> pd.DataFrame:
    """Read one Eurostat year while preserving unavailable observations."""
    data = validate_census(path, year)
    series_key = data.columns[0]
    dimensions = series_key.removesuffix("\\TIME_PERIOD").split(",")
    year_column = next(column for column in data if column.strip() == str(year))
    data[dimensions] = data.pop(series_key).str.split(",", expand=True)
    data["value"] = pd.to_numeric(
        data.pop(year_column).str.strip().str.split().str[0], errors="coerce"
    )
    return data


def residential_floor_area(data: pd.DataFrame, settings: dict[str, Any]) -> pd.Series:
    """Calculate NUTS-3 gross floor area from dwelling or room classes."""
    common = data.loc[
        data.freq.eq("A") & data.building.eq("TOTAL") & data.unit.eq("NR")
    ]
    area = (
        common.loc[
            common.n_room.eq("TOTAL") & common.area.isin(settings["floor_space_m2"])
        ]
        .pivot_table(index="geo", columns="area", values="value", aggfunc="sum")
        .mul(pd.Series(settings["floor_space_m2"]))
        .sum(axis=1, min_count=1)
    )
    rooms = (
        common.loc[common.area.eq("TOTAL") & common.n_room.isin(settings["rooms"])]
        .pivot_table(index="geo", columns="n_room", values="value", aggfunc="sum")
        .mul(pd.Series(settings["rooms"]))
        .sum(axis=1, min_count=1)
        .mul(settings["floor_area_per_room_m2"])
    )
    return area.where(area.gt(0), rooms).mul(settings["useful_to_gross_ratio"])


def population_sums(population, polygons: gpd.GeoDataFrame) -> pd.Series:
    """Aggregate a population raster to polygons through bounded Gregor calls."""
    values = []
    for geometry in polygons.geometry:
        projected = gpd.GeoSeries([geometry], crs=polygons.crs).to_crs(
            population.rio.crs
        )
        window = population.rio.clip_box(*projected.total_bounds)
        values.append(
            aggregate_raster_to_polygon(window, projected, stats="sum")["sum"].iloc[0]
        )
    return pd.Series(values, index=polygons.index, dtype=float)


def point_total(points: gpd.GeoDataFrame, geometry) -> float:
    """Aggregate point floor area to one NUTS-3 polygon with Gregor."""
    if points.empty:
        return 0.0
    polygon = gpd.GeoSeries(
        [geometry], index=pd.Index(["region"], name="nuts3_id"), crs=points.crs
    )
    return float(
        aggregate_point_to_polygon(
            points[["floor_area_m2", "geometry"]], polygon
        ).floor_area_m2.iloc[0]
    )


class Eubucco:
    """Stream building rows intersecting one current NUTS-3 region."""

    def __init__(self, regions, covered_regions, endpoint, path, version):
        """Prepare the EUBUCCO partition index and anonymous filesystem."""
        self.regions = regions.loc[
            regions.region_id.str.len().eq(5) & regions.region_id.isin(covered_regions)
        ].set_index("region_id")
        self.filesystem = fs.S3FileSystem(anonymous=True, endpoint_override=endpoint)
        self.path = path
        self.version = version

    def buildings(self, geometry) -> gpd.GeoDataFrame:
        """Load buildings whose centroids fall inside one current region."""
        candidates = self.regions.loc[self.regions.intersects(geometry)]
        region_ids = candidates.index[
            candidates.geometry.intersection(geometry).area.gt(0)
        ]
        tables = []
        for nuts2, ids in pd.Series(region_ids, index=region_ids).groupby(
            region_ids.str[:4]
        ):
            dataset = ds.dataset(
                self.path.format(version=self.version, nuts2=nuts2),
                filesystem=self.filesystem,
                format="parquet",
            )
            tables.append(
                dataset.to_table(
                    columns=["id", "type", "subtype", "floors", "geometry"],
                    filter=ds.field("region_id").isin(ids.tolist()),
                )
            )
        if tables:
            table = pa.concat_tables(tables)
            table = table.set_column(
                table.schema.get_field_index("floors"),
                "floors",
                pc.cast(table["floors"], pa.float64()),
            )
            attributes = table.drop_columns("geometry").to_pandas()
            buildings = gpd.GeoDataFrame(
                attributes,
                geometry=gpd.GeoSeries.from_wkb(pc.cast(table["geometry"], "binary")),
                crs="EPSG:3035",
            )
        else:
            buildings = gpd.GeoDataFrame(
                columns=["id", "type", "subtype", "floors", "geometry"],
                geometry="geometry",
                crs="EPSG:3035",
            )
        validate_eubucco_buildings(buildings)
        buildings["floor_area_m2"] = buildings.area * buildings.floors
        buildings.geometry = buildings.centroid
        return buildings.loc[buildings.within(geometry)]


def output_profile(bounds, settings):
    """Return an EPSG:3035 profile aligned to the 100 m European grid."""
    cell = settings["cell_size_m"]
    left = math.floor(bounds[0] / cell) * cell
    bottom = math.floor(bounds[1] / cell) * cell
    right = math.ceil(bounds[2] / cell) * cell
    top = math.ceil(bounds[3] / cell) * cell
    return {
        "driver": "GTiff",
        "width": round((right - left) / cell),
        "height": round((top - bottom) / cell),
        "count": 3,
        "dtype": settings["dtype"],
        "crs": "EPSG:3035",
        "transform": Affine(cell, 0, left, 0, -cell, top),
        "nodata": settings["nodata"],
        "compress": settings["compression"],
        "tiled": True,
        "blockxsize": settings["block_size"],
        "blockysize": settings["block_size"],
    }


def write_points(output, band, points, values) -> None:
    """Aggregate centroid values to occupied hectares with Gregor and write them."""
    if points.empty:
        return
    rows, columns = rasterio.transform.rowcol(
        output.transform, points.geometry.x, points.geometry.y
    )
    rows, columns = np.asarray(rows), np.asarray(columns)
    inside = (
        (rows >= 0) & (rows < output.height) & (columns >= 0) & (columns < output.width)
    )
    rows, columns = rows[inside], columns[inside]
    values = np.asarray(values)[inside]
    if not len(values):
        return
    cell_ids = rows * output.width + columns
    unique_ids = np.unique(cell_ids)
    cell_rows, cell_columns = unique_ids // output.width, unique_ids % output.width
    left = output.transform.c + cell_columns * output.transform.a
    top = output.transform.f + cell_rows * output.transform.e
    cells = gpd.GeoDataFrame(
        geometry=box(left, top + output.transform.e, left + output.transform.a, top),
        index=pd.Index(unique_ids, name="cell_id"),
        crs=output.crs,
    )
    selected = points.loc[inside, ["geometry"]].copy()
    selected.geometry = gpd.points_from_xy(
        output.transform.c + columns * output.transform.a + output.transform.a / 2,
        output.transform.f + rows * output.transform.e + output.transform.e / 2,
        crs=output.crs,
    )
    selected["floor_area_m2"] = values
    aggregated = aggregate_point_to_polygon(selected, cells)
    assert np.isclose(aggregated.floor_area_m2.sum(), values.sum())
    window = Window.from_slices(
        (cell_rows.min(), cell_rows.max() + 1),
        (cell_columns.min(), cell_columns.max() + 1),
    )
    raster = output.read(band, window=window)
    raster[cell_rows - int(window.row_off), cell_columns - int(window.col_off)] += (
        aggregated.floor_area_m2.to_numpy()
    )
    output.write(raster, band, window=window)


def write_population(output, population, band, geometry, total, support) -> None:
    """Allocate a regional total to output cells with GHS-POP weights."""
    if total == 0:
        return
    validate_scaling_support(np.array([total]), np.array([support]))
    window = geometry_window(output, [geometry])
    weights = population.read(1, window=window, masked=True).filled(0)
    inside = geometry_mask(
        [geometry], weights.shape, output.window_transform(window), invert=True
    )
    values = output.read(band, window=window)
    values[inside] += weights[inside] * total / support
    output.write(values, band, window=window)


def gridded_population_sum(source, geometry, settings) -> float:
    """Sum population on the aligned hectare grid over a complete region."""
    profile = output_profile(geometry.bounds, settings)
    with WarpedVRT(
        source,
        crs=profile["crs"],
        transform=profile["transform"],
        width=profile["width"],
        height=profile["height"],
        nodata=0,
        resampling=Resampling.sum,
    ) as population:
        values = population.read(1, masked=True).filled(0)
        inside = geometry_mask(
            [geometry], values.shape, population.transform, invert=True
        )
    return float(values[inside].sum(dtype="float64"))


def main() -> None:
    """Build the three-band raster and its two sector plots."""
    sys.stderr = open(snakemake.log[0], "w")
    settings = snakemake.params.floor_area
    countries = snakemake.params.country_codes
    reverse_countries = {code: country for country, code in countries.items()}
    shapes = validate_shapes(snakemake.input.shapes).to_crs("EPSG:3035")
    nuts3 = (
        validate_nuts3(snakemake.input.nuts3).to_crs("EPSG:3035").set_index("nuts3_id")
    )
    nuts3_source = validate_nuts3_source(snakemake.input.nuts3_source).to_crs(
        "EPSG:3035"
    )
    nuts3_source["country_id"] = nuts3_source.CNTR_CODE.map(reverse_countries)
    nuts3_source = nuts3_source.set_index("NUTS_ID")
    population_path = snakemake.input.population
    validate_population_raster(population_path, settings["ghsl_resolution"])
    population = (
        rioxarray.open_rasterio(
            population_path,
            masked=True,
            chunks={
                "band": 1,
                "x": settings["ghsl_chunk_size"],
                "y": settings["ghsl_chunk_size"],
            },
            cache=False,
        )
        .squeeze(drop=True)
        .fillna(0)
    )
    regional_population = population_sums(population, nuts3)
    census = residential_floor_area(
        census_values(snakemake.input.census, settings["reference_year"]), settings
    )
    eubucco_regions = validate_eubucco_nuts(snakemake.input.eubucco_nuts)
    eubucco_stats = validate_eubucco_stats(snakemake.input.eubucco_stats)
    eubucco = Eubucco(
        eubucco_regions,
        eubucco_stats.region_id,
        snakemake.params.eubucco["eubucco_endpoint"],
        snakemake.params.eubucco["eubucco_buildings"],
        settings["eubucco"]["version"],
    )
    population_cache = {}
    residential_intensities = {}
    commercial_intensities = {}

    def residential_intensity(country):
        valid = census.index.intersection(
            nuts3_source.index[nuts3_source.country_id.eq(country)]
        )
        valid = valid[census.reindex(valid).notna()]
        support = population_sums(population, nuts3_source.loc[valid]).sum()
        total = census.loc[valid].sum()
        assert total > 0
        assert support > 0
        return total / support

    def commercial_intensity(country):
        code = countries[country]
        stats = eubucco_stats.loc[eubucco_stats.country.eq(code)].set_index("region_id")
        total = (
            stats.floor_area_subtype_commercial.sum()
            + stats.floor_area_subtype_public.sum()
        )
        if country not in population_cache:
            population_cache[country] = population_sums(population, stats).sum()
        assert total > 0
        assert population_cache[country] > 0
        return total / population_cache[country]

    profile = output_profile(shapes.total_bounds, snakemake.params.raster)
    scope = shapes.geometry.union_all()
    Path(snakemake.output.raster).parent.mkdir(parents=True, exist_ok=True)
    with (
        rasterio.open(population_path) as population_source,
        rasterio.open(snakemake.output.raster, "w+", **profile) as output,
        WarpedVRT(
            population_source,
            crs=profile["crs"],
            transform=profile["transform"],
            width=profile["width"],
            height=profile["height"],
            nodata=0,
            resampling=Resampling.sum,
        ) as population_grid,
    ):
        for nuts3_id, region in nuts3.iterrows():
            geometry = region.geometry
            clipped = geometry.intersection(scope)
            buildings = eubucco.buildings(geometry)
            residential = buildings.loc[
                buildings.type.eq(settings["eubucco"]["residential_type"])
            ]
            commercial = buildings.loc[
                buildings.subtype.isin(settings["eubucco"]["commercial_subtypes"])
            ]
            grid_population = None
            residential_total = census.get(nuts3_id, np.nan)
            if pd.isna(residential_total):
                references = snakemake.params.proxies["residential_floor_area"][
                    region.country_id
                ]
                for country in references:
                    if country not in residential_intensities:
                        residential_intensities[country] = residential_intensity(
                            country
                        )
                residential_total = (
                    np.mean(
                        [residential_intensities[country] for country in references]
                    )
                    * regional_population[nuts3_id]
                )
            raw_residential = point_total(residential, geometry)
            if raw_residential > 0:
                selected = residential.loc[residential.within(scope)]
                write_points(
                    output,
                    1,
                    selected,
                    selected.floor_area_m2 * residential_total / raw_residential,
                )
            else:
                grid_population = gridded_population_sum(
                    population_source, geometry, snakemake.params.raster
                )
                write_population(
                    output,
                    population_grid,
                    1,
                    clipped,
                    residential_total,
                    grid_population,
                )

            if buildings.empty and regional_population[nuts3_id] > 0:
                references = snakemake.params.proxies["commercial_floor_area"][
                    region.country_id
                ]
                for country in references:
                    if country not in commercial_intensities:
                        commercial_intensities[country] = commercial_intensity(country)
                commercial_total = (
                    np.mean([commercial_intensities[country] for country in references])
                    * regional_population[nuts3_id]
                )
                if grid_population is None:
                    grid_population = gridded_population_sum(
                        population_source, geometry, snakemake.params.raster
                    )
                write_population(
                    output,
                    population_grid,
                    2,
                    clipped,
                    commercial_total,
                    grid_population,
                )
            else:
                selected = commercial.loc[commercial.within(scope)]
                write_points(output, 2, selected, selected.floor_area_m2)

        for _, window in output.block_windows(1):
            output.write(
                output.read(1, window=window) + output.read(2, window=window),
                3,
                window=window,
            )
        for band, description in enumerate(FLOOR_AREA_BANDS, 1):
            output.set_band_description(band, description)
            output.set_band_unit(band, "m2/ha")
        output.update_tags(
            census_reference_year=settings["reference_year"],
            eubucco_version=settings["eubucco"]["version"],
            ghsl_epoch=settings["ghsl_epoch"],
            building_assignment=settings["eubucco"]["assignment"],
        )
    population.close()

    validate_density_raster(
        snakemake.output.raster,
        snakemake.params.raster,
        ("m2/ha",) * 3,
        FLOOR_AREA_BANDS,
    )
    plot_floor_area(
        snakemake.output.raster,
        1,
        "Residential floor area",
        snakemake.output.residential_plot,
    )
    plot_floor_area(
        snakemake.output.raster,
        2,
        "Commercial and public floor area",
        snakemake.output.commercial_plot,
    )
    validate_plot(snakemake.output.residential_plot)
    validate_plot(snakemake.output.commercial_plot)


main()
