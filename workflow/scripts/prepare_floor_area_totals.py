"""Prepare residential and commercial/public control-region floor-area totals.

Eurostat residential totals remain authoritative. Countries without totals use
reference-country floor area per inhabitant, while Microsoft footprint area and
reference-country mean floors distribute that total over their actual buildings.
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import rioxarray
from _eubucco import read_plan
from _floor_area import census_values, population_sums, residential_floor_area
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
eurostat = snakemake.params.eurostat
population_settings = snakemake.params.population
eubucco = snakemake.params.eubucco
proxies = snakemake.params.proxies
countries = snakemake.params.country_codes
reverse_countries = {code: country for country, code in countries.items()}
regions = validate_nuts3(snakemake.input.nuts3).set_index("region_id")
nuts_source = validate_nuts3_source(snakemake.input.nuts3_source).to_crs(regions.crs)
nuts_source["country_id"] = nuts_source.CNTR_CODE.map(reverse_countries)
nuts_source = nuts_source.set_index("NUTS_ID")
validate_population_raster(snakemake.input.population, population_settings["resolution"])
population_source: Any = rioxarray.open_rasterio(
    snakemake.input.population,
    masked=True,
    chunks={
        "band": 1,
        "x": population_settings["chunk_size"],
        "y": population_settings["chunk_size"],
    },
    cache=False,
)
population = population_source.squeeze(drop=True).fillna(0)
regional_population = population_sums(population, regions)
raw_census = census_values(snakemake.input.census, eurostat["reference_year"])
census_area = residential_floor_area(raw_census, eurostat)
stats = validate_eubucco_stats(snakemake.input.eubucco_stats)
plan = read_plan(snakemake.input.plan)
microsoft_area = (
    pd.read_parquet(snakemake.input.microsoft)
    .groupby("region_id")
    .footprint_area_m2.sum()
    .reindex(regions.index, fill_value=0)
)


def reference_mean_floors(reference_countries):
    """Equal-weight effective storeys from EUBUCCO stock statistics."""
    values = []
    representatives = pd.Series(eubucco["floor_bin_representatives"])
    for country in reference_countries:
        selected = stats.loc[stats.country.eq(countries[country])]
        counts = selected[representatives.index].sum()
        assert counts.sum() > 0
        values.append(counts.dot(representatives) / counts.sum())
    return np.mean(values)


def reference_sector_shares(reference_countries):
    """Return equal-weight reference-country residential and commercial shares."""
    values = []
    for country in reference_countries:
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


def reference_floor_area_per_inhabitant(reference_countries):
    """Return the equal-weight processed Eurostat floor area per inhabitant."""
    values = []
    for country in reference_countries:
        valid = census_area.index.intersection(
            nuts_source.index[nuts_source.country_id.eq(country)]
        )
        valid = valid[census_area.reindex(valid).notna()]
        inhabitants = population_sums(population, nuts_source.loc[valid]).sum()
        assert census_area.loc[valid].sum() > 0
        assert inhabitants > 0
        values.append(census_area.loc[valid].sum() / inhabitants)
    return np.mean(values)


residential_totals = census_area.reindex(regions.index)
commercial_totals = pd.Series(np.nan, index=regions.index)
for region_id, region in regions.iterrows():
    source = plan["regions"][region_id]
    if "microsoft" not in {source["residential_source"], source["commercial_source"]}:
        continue
    references = proxies["countries"][region.country_id]
    residential_share, commercial_share = reference_sector_shares(references)
    if pd.isna(residential_totals[region_id]):
        total = microsoft_area[region_id] * reference_mean_floors(references)
        residential_totals[region_id] = total * residential_share
        commercial_totals[region_id] = total * commercial_share
    else:
        commercial_totals[region_id] = (
            residential_totals[region_id] * commercial_share / residential_share
        )

# Scale Microsoft building support for each proxied country to the residential
# Eurostat floor area per inhabitant calculated from its reference countries.
missing_census = census_area.reindex(regions.index).isna()
for country in regions.loc[missing_census].country_id.unique():
    selected = regions.country_id.eq(country) & missing_census
    microsoft = selected & pd.Series(
        {
            region_id: plan["regions"][region_id]["residential_source"] == "microsoft"
            for region_id in regions.index
        }
    )
    if microsoft.any():
        target = (
            reference_floor_area_per_inhabitant(proxies["countries"][country])
            * regional_population.loc[microsoft].sum()
        )
        scale = target / residential_totals.loc[microsoft].sum()
        residential_totals.loc[microsoft] *= scale
        commercial_totals.loc[microsoft] *= scale

# EUBUCCO-backed regions use the same shared reference-country intensity.
for region_id in residential_totals.index[residential_totals.isna()]:
    region = regions.loc[region_id]
    residential_totals[region_id] = (
        reference_floor_area_per_inhabitant(proxies["countries"][region.country_id])
        * regional_population[region_id]
    )

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
