"""Prepare residential and commercial/public control-region floor-area totals.

Eurostat residential totals remain authoritative for NUTS-3 regions. Elsewhere,
Microsoft proxy settings provide either a demographic dwelling estimate or a
mean-floors estimate. Population is a control input only, never a spatial weight.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import rioxarray
from _eubucco import read_plan
from _floor_area import (
    census_values,
    dwelling_counts,
    population_sums,
    residential_floor_area,
)
from _microsoft import assumed_floor_area, explicit_sector_shares
from _schemas import (
    validate_eubucco_stats,
    validate_floor_area_totals,
    validate_nuts3,
    validate_nuts3_source,
    validate_population_raster,
)

if TYPE_CHECKING:
    snakemake: Any

sys.stderr = open(snakemake.log[0], "w")
settings = snakemake.params.floor_area
proxies = snakemake.params.proxies
countries = snakemake.params.country_codes
reverse_countries = {code: country for country, code in countries.items()}
regions = validate_nuts3(snakemake.input.nuts3).set_index("region_id")
nuts_source = validate_nuts3_source(snakemake.input.nuts3_source).to_crs(regions.crs)
nuts_source["country_id"] = nuts_source.CNTR_CODE.map(reverse_countries)
nuts_source = nuts_source.set_index("NUTS_ID")
validate_population_raster(snakemake.input.population, settings["ghsl_resolution"])
population_source: Any = rioxarray.open_rasterio(
    snakemake.input.population,
    masked=True,
    chunks={"band": 1, "x": settings["ghsl_chunk_size"], "y": settings["ghsl_chunk_size"]},
    cache=False,
)
population = population_source.squeeze(drop=True).fillna(0)
regional_population = population_sums(population, regions)
raw_census = census_values(snakemake.input.census, settings["reference_year"])
census_area = residential_floor_area(raw_census, settings)
census_dwellings = dwelling_counts(raw_census, settings)
stats = validate_eubucco_stats(snakemake.input.eubucco_stats)
plan = read_plan(snakemake.input.plan)
microsoft_area = (
    pd.read_parquet(snakemake.input.microsoft)
    .groupby("region_id")
    .footprint_area_m2.sum()
    .reindex(regions.index, fill_value=0)
)


def reference_dwelling_parameters(reference_countries):
    """Equal-weight country means for dwelling area and occupancy."""
    values = []
    for country in reference_countries:
        valid = census_area.index.intersection(
            nuts_source.index[nuts_source.country_id.eq(country)]
        )
        valid = valid[census_area.reindex(valid).notna() & census_dwellings.reindex(valid).gt(0)]
        total_area = census_area.loc[valid].sum()
        dwellings = census_dwellings.loc[valid].sum()
        inhabitants = population_sums(population, nuts_source.loc[valid]).sum()
        assert total_area > 0
        assert dwellings > 0
        assert inhabitants > 0
        values.append((total_area / dwellings, inhabitants / dwellings))
    return np.mean(values, axis=0)


def reference_mean_floors(reference_countries):
    """Equal-weight effective storeys from EUBUCCO stock statistics."""
    values = []
    representatives = pd.Series(settings["eubucco"]["floor_bin_representatives"])
    for country in reference_countries:
        selected = stats.loc[stats.country.eq(countries[country])]
        counts = selected[representatives.index].sum()
        assert counts.sum() > 0
        values.append(counts.dot(representatives) / counts.sum())
    return np.mean(values)


def sector_shares(proxy):
    """Return explicit or equal-weight reference-country sector shares."""
    if proxy["method"] == "user_specified":
        return explicit_sector_shares(proxy)
    values = []
    for country in proxy["parameters"]["countries"]:
        selected = stats.loc[stats.country.eq(countries[country])]
        residential = selected.floor_area_type_residential.sum()
        commercial = (
            selected.floor_area_subtype_commercial.sum()
            + selected.floor_area_subtype_public.sum()
        )
        assert residential > 0
        assert commercial > 0
        values.append(residential / (residential + commercial))
    residential = float(np.mean(values))
    return residential, 1 - residential


residential_totals = census_area.reindex(regions.index)
commercial_totals = pd.Series(np.nan, index=regions.index)
for region_id, region in regions.iterrows():
    source = plan["regions"][region_id]
    if "microsoft" not in {source["residential_source"], source["commercial_source"]}:
        continue
    proxy = proxies["microsoft"]["countries"][region.country_id]
    residential_share, commercial_share = sector_shares(proxy["sector_split"])
    floor = proxy["floor_area"]
    parameters = floor["parameters"]
    if pd.isna(residential_totals[region_id]):
        if parameters["estimator"] == "area_per_dwelling":
            if floor["method"] == "reference_countries":
                area, occupancy = reference_dwelling_parameters(parameters["countries"])
            else:
                area = parameters["gross_floor_area_per_dwelling_m2"]
                occupancy = parameters["persons_per_dwelling"]
            resolved = {
                "estimator": "area_per_dwelling",
                "gross_floor_area_per_dwelling_m2": area,
                "persons_per_dwelling": occupancy,
            }
        else:
            mean_floors = (
                reference_mean_floors(parameters["countries"])
                if floor["method"] == "reference_countries"
                else parameters["mean_floors"]
            )
            resolved = {"estimator": "mean_floors", "mean_floors": mean_floors}
        residential_totals[region_id], commercial_totals[region_id] = assumed_floor_area(
            regional_population[region_id],
            microsoft_area[region_id],
            resolved,
            (residential_share, commercial_share),
        )
    else:
        commercial_totals[region_id] = (
            residential_totals[region_id] * commercial_share / residential_share
        )

# EUBUCCO regions with missing Eurostat totals retain the established
# reference-country floor-area-per-person method.
for region_id in residential_totals.index[residential_totals.isna()]:
    region = regions.loc[region_id]
    references = proxies["residential_floor_area"][region.country_id]
    intensities = []
    for country in references:
        valid = census_area.index.intersection(nuts_source.index[nuts_source.country_id.eq(country)])
        valid = valid[census_area.reindex(valid).notna()]
        support = population_sums(population, nuts_source.loc[valid]).sum()
        assert census_area.loc[valid].sum() > 0
        assert support > 0
        intensities.append(census_area.loc[valid].sum() / support)
    residential_totals[region_id] = np.mean(intensities) * regional_population[region_id]

totals = pd.DataFrame(
    {
        "region_id": regions.index,
        "country_id": regions.country_id,
        "population": regional_population,
        "residential_total_m2": residential_totals,
        "commercial_fallback_m2": commercial_totals,
    }
).reset_index(drop=True)
Path(snakemake.output.table).parent.mkdir(parents=True, exist_ok=True)
totals.to_parquet(snakemake.output.table, index=False)
population.close()
validate_floor_area_totals(snakemake.output.table, regions.index)
