"""Small numerical regressions for heat weights derived from cached support."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "heat_support", Path(__file__).parents[1] / "workflow/scripts/_space_heat_weight.py"
)
heat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(heat)


@pytest.mark.parametrize("share", [0.0, 0.5, 1.0])
def test_cached_compactness_preserves_building_corrections(share):
    """Missing observations stay neutral and population-only cells retain support."""
    area = np.array([40.0, 60.0, 100.0])
    cells = np.array([0, 0, 1])
    powers = np.array([2.0, np.nan, 4.0])
    population = np.array([10.0, 20.0, 30.0])
    reference = (40 * 2 + 100 * 4) / 140
    floor = np.bincount(cells, weights=area, minlength=3)
    valid = np.bincount(
        cells, weights=np.where(np.isfinite(powers), area, 0), minlength=3
    )
    weighted = np.bincount(cells, weights=area * np.nan_to_num(powers), minlength=3)
    corrected = np.bincount(
        cells,
        weights=area * np.where(np.isfinite(powers), powers / reference, 1),
        minlength=3,
    )
    factor = np.divide(corrected, floor, out=np.ones(3), where=floor > 0)
    expected = ((1 - share) * floor + share * 200 * population / 60) * factor * 1.1
    actual = heat.weight_from_support(
        floor, population, valid, weighted, reference, 200, 60, share, 1.1
    )
    np.testing.assert_allclose(actual, expected, rtol=1e-14)


def test_scoped_microsoft_support_uses_complete_region_population():
    """Clipped support is not renormalised; Microsoft compactness remains neutral."""
    actual = heat.weight_from_support(
        np.array([20.0, 0.0]),
        np.array([5.0, 10.0]),
        np.zeros(2),
        np.zeros(2),
        reference=1.0,
        total=200.0,
        population_total=100.0,
        share=0.5,
        age=1.0,
    )
    np.testing.assert_allclose(actual, [15.0, 10.0])


def test_zero_floor_area_needs_no_population_normalization():
    """A zero control total yields zero weights without dividing by zero."""
    zeros = np.zeros(2)
    actual = heat.weight_from_support(
        zeros, zeros, zeros, zeros, 1.0, 0.0, 0.0, 0.5, 1.0
    )
    np.testing.assert_array_equal(actual, zeros)
