"""Pure calculations for residential space-heating spatial support.

The support blends gross residential floor-area and population shares before
multiplying by independently centred compactness and construction-age factors.

The equivalent-square method supports lightweight EUBUCCO, while full EUBUCCO
provides observed footprint perimeter. Hotmaps elasticities and age multipliers
follow Müller et al. (2019); the exact values used are configured assumptions.

Source: https://doi.org/10.3390/en12244789
"""

import numpy as np


def _return(values: np.ndarray):
    """Return a scalar when scalar inputs produced a zero-dimensional array."""
    return values.item() if values.ndim == 0 else values


def surface_to_volume_ratio(
    footprint_area_m2, height_m, footprint_perimeter_m=None, method="equivalent_square"
):
    """Return ``P/A + 2/H`` for valid extruded buildings, otherwise NaN.

    ``equivalent_square`` approximates perimeter as ``4 * sqrt(A)``.
    ``footprint_perimeter`` uses observed perimeter supplied by the caller.
    """
    area, height = np.broadcast_arrays(
        np.asarray(footprint_area_m2, dtype=float), np.asarray(height_m, dtype=float)
    )
    if method == "equivalent_square":
        perimeter = 4 * np.sqrt(np.where(area > 0, area, np.nan))
    elif method == "footprint_perimeter":
        if footprint_perimeter_m is None:
            raise ValueError("footprint_perimeter_m is required")
        area, height, perimeter = np.broadcast_arrays(
            area, height, np.asarray(footprint_perimeter_m, dtype=float)
        )
    else:
        raise ValueError(f"Unknown surface-volume method: {method}")
    valid = (
        np.isfinite(area)
        & np.isfinite(height)
        & np.isfinite(perimeter)
        & (area > 0)
        & (height > 0)
        & (perimeter > 0)
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(valid, perimeter / area + 2 / height, np.nan)
    ratio = np.where(np.isfinite(ratio), ratio, np.nan)
    return _return(ratio)


def surface_volume_power(surface_volume_ratio, elasticity: float):
    """Apply the compactness elasticity while preserving missing values."""
    ratio = np.asarray(surface_volume_ratio, dtype=float)
    values = np.where(
        np.isfinite(ratio) & (ratio > 0), np.power(ratio, elasticity), np.nan
    )
    return _return(values)


def cell_surface_volume_factor(floor_area, weighted_factor):
    """Average building compactness by floor area, neutral in empty cells."""
    floor_area = np.asarray(floor_area, dtype=float)
    return np.divide(
        weighted_factor, floor_area, out=np.ones_like(floor_area), where=floor_area > 0
    )


def space_heat_weight(floor_area_m2, f_sv=1.0, f_age=1.0):
    """Combine corrected floor area and dimensionless heat-support factors."""
    return np.asarray(floor_area_m2) * f_sv * f_age


def weight_from_support(
    floor_area,
    population,
    valid_area,
    weighted_power,
    reference,
    total,
    population_total,
    share,
    age,
):
    """Apply the original heat formula to cached additive building statistics.

    F - V retains neutral support from missing compactness and Microsoft.
    Population is normalised over the complete region, even for scoped cells.
    """
    blended = floor_area
    if total > 0 and share > 0:
        blended = (
            1 - share
        ) * floor_area + share * total * population / population_total
    corrected = weighted_power / reference + (floor_area - valid_area)
    return space_heat_weight(
        blended, cell_surface_volume_factor(floor_area, corrected), age
    )
