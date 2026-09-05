"""Pure calculations for residential space-heating spatial support.

The support multiplies corrected gross residential floor area by independently
centred compactness and construction-age factors.

The equivalent-square compactness method is an explicit approximation because
the EUBUCCO v0.2 lightweight table contains height and area, but no footprint
perimeter. Hotmaps elasticities and age multipliers follow Müller et al. (2019).
"""

from collections.abc import Mapping

import numpy as np


def _return(values: np.ndarray):
    """Return a scalar when scalar inputs produced a zero-dimensional array."""
    return values.item() if values.ndim == 0 else values


def surface_to_volume_ratio(
    footprint_area_m2,
    height_m,
    footprint_perimeter_m=None,
    method="equivalent_square",
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


def weighted_reference(weights, values) -> float:
    """Return the valid positive-weight mean, or neutral one if none exists."""
    weights, values = np.broadcast_arrays(
        np.asarray(weights, dtype=float), np.asarray(values, dtype=float)
    )
    valid = np.isfinite(weights) & (weights > 0) & np.isfinite(values)
    return (
        float(np.sum(weights[valid] * values[valid]) / np.sum(weights[valid]))
        if np.any(valid)
        else 1.0
    )


def normalised_factor(values, reference: float):
    """Centre valid values on a positive reference; missing values stay neutral."""
    if not np.isfinite(reference) or reference <= 0:
        raise ValueError("reference must be finite and positive")
    values = np.asarray(values, dtype=float)
    factor = np.where(np.isfinite(values), values / reference, 1.0)
    return _return(factor)


def age_factor_from_counts(
    counts: Mapping[str, float], multipliers: Mapping[str, float]
) -> float:
    """Return the dwelling-count-weighted factor for known canonical age groups."""
    known = sum(counts.get(group, 0.0) for group in multipliers)
    return (
        sum(counts.get(group, 0.0) * multiplier for group, multiplier in multipliers.items())
        / known
        if known > 0
        else np.nan
    )


def space_heat_weight(floor_area_m2, f_sv=1.0, f_age=1.0):
    """Combine corrected floor area and dimensionless heat-support factors."""
    return np.asarray(floor_area_m2) * f_sv * f_age
