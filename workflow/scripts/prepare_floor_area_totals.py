"""Prepare NUTS-3 population and gross floor-area control totals.

Residential totals come from Eurostat Census 2021 dwelling floor-space classes,
or from room classes where floor space is unavailable. Missing target regions
use the configured mean gross-floor-area-per-resident intensity of reference
countries. Commercial/public fallback intensities are derived from EUBUCCO
regional statistics and GHS-POP and are prepared only for configured countries.
All conversion factors and proxy-country choices live in ``config/config.yaml``.

The output contains control totals, not spatial densities. They are distributed
over building centroids or population cells by ``create_nuts3_floor_area.py``.

Sources:
    Floor-area method: https://doi.org/10.3390/en12244789
    Census definitions: https://ec.europa.eu/eurostat/cache/metadata/en/cens_21_esms.htm
    GHS-POP R2023A: https://human-settlement.emergency.copernicus.eu/documents/GHSL_Data_Package_2023.pdf
    EUBUCCO: https://doi.org/10.1038/s41597-023-02040-2
"""

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import rioxarray
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
settings = snakemake.params.floor_area
countries = snakemake.params.country_codes
reverse_countries = {code: country for country, code in countries.items()}

# Current NUTS-3 regions are the output geography; the source vintage is kept
# separately because the Eurostat census values use those historical codes.
nuts3 = (
    validate_nuts3(snakemake.input.nuts3).to_crs("EPSG:3035").set_index("nuts3_id")
)
nuts3_source = validate_nuts3_source(snakemake.input.nuts3_source).to_crs(
    "EPSG:3035"
)
nuts3_source["country_id"] = nuts3_source.CNTR_CODE.map(reverse_countries)
nuts3_source = nuts3_source.set_index("NUTS_ID")
validate_population_raster(snakemake.input.population, settings["ghsl_resolution"])

# Chunked access limits each polygon aggregation to the required raster window.
population = (
    rioxarray.open_rasterio(
        snakemake.input.population,
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
stats = validate_eubucco_stats(snakemake.input.eubucco_stats)
population_cache = {}
residential_intensities = {}
commercial_intensities = {}


def residential_intensity(country):
    """Return census gross residential floor area per GHS-POP resident.

    Only source-vintage NUTS-3 regions with a reported census total contribute
    to both numerator and denominator.
    """
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
    """Return EUBUCCO commercial/public floor area per GHS-POP resident.

    Population is cached because it is shared by every target region using the
    same reference country.
    """
    selected = stats.loc[stats.country.eq(countries[country])].set_index("region_id")
    total = (
        selected.floor_area_subtype_commercial.sum()
        + selected.floor_area_subtype_public.sum()
    )
    if country not in population_cache:
        population_cache[country] = population_sums(population, selected).sum()
    assert total > 0
    assert population_cache[country] > 0
    return total / population_cache[country]


residential_totals = census.reindex(nuts3.index)
commercial_fallback = pd.Series(np.nan, index=nuts3.index)

# Fill missing regional values with configured reference-country intensities.
# Commercial fallbacks are prepared only for countries that may need them later.
for nuts3_id, region in nuts3.iterrows():
    if pd.isna(residential_totals[nuts3_id]):
        references = snakemake.params.proxies["residential_floor_area"][
            region.country_id
        ]
        for country in references:
            if country not in residential_intensities:
                residential_intensities[country] = residential_intensity(country)
        residential_totals[nuts3_id] = (
            np.mean([residential_intensities[country] for country in references])
            * regional_population[nuts3_id]
        )
    if region.country_id in snakemake.params.proxies["commercial_floor_area"]:
        references = snakemake.params.proxies["commercial_floor_area"][
            region.country_id
        ]
        for country in references:
            if country not in commercial_intensities:
                commercial_intensities[country] = commercial_intensity(country)
        commercial_fallback[nuts3_id] = (
            np.mean([commercial_intensities[country] for country in references])
            * regional_population[nuts3_id]
        )
totals = pd.DataFrame(
    {
        "nuts3_id": nuts3.index,
        "country_id": nuts3.country_id,
        "population": regional_population,
        "residential_total_m2": residential_totals,
        "commercial_fallback_m2": commercial_fallback,
    }
).reset_index(drop=True)
Path(snakemake.output.table).parent.mkdir(parents=True, exist_ok=True)
totals.to_parquet(snakemake.output.table, index=False)
population.close()
validate_floor_area_totals(snakemake.output.table, nuts3.index)
