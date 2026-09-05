"""Unit and synthetic integration tests for residential heat support."""

import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import yaml

sys.path.insert(0, str(Path(__file__).parents[1] / "workflow" / "scripts"))

from _eubucco import canonical_from_lightweight  # noqa: E402
from _space_heat_weight import (  # noqa: E402
    age_factor_from_counts,
    normalised_factor,
    space_heat_weight,
    surface_to_volume_ratio,
    surface_volume_power,
    weighted_reference,
)


def test_configured_hotmaps_parameters():
    """Default compactness elasticity and age factors remain explicit."""
    config = yaml.safe_load(
        (Path(__file__).parents[1] / "config" / "config.yaml").read_text()
    )["space_heat_weight"]
    assert config["surface_volume"] == {
        "elasticity": 0.33,
        "method": "equivalent_square",
    }
    assert config["age"]["multipliers"] == {
        "before_1991": 1.25,
        "1991_2000": 1.0,
        "after_2000": 0.8,
    }


def test_canonical_eubucco_retains_height():
    """Canonical conversion preserves observed lightweight-table height."""
    class IdentityTransformer:
        def transform(self, x, y):
            return x, y

    source = pa.RecordBatch.from_pydict(
        {
            "id": ["building"],
            "region_id": ["NL001"],
            "type": ["residential"],
            "subtype": ["residential"],
            "floors": [3.0],
            "footprint_area": [100.0],
            "height": [12.5],
            "lon": [5.0],
            "lat": [52.0],
        }
    )
    canonical = canonical_from_lightweight(source, IdentityTransformer())
    assert canonical.column("height_m").to_pylist() == [12.5]


def test_surface_to_volume_ratio():
    """Equivalent-square and observed-perimeter formulas equal P/A + 2/H."""
    assert np.isclose(surface_to_volume_ratio(100, 10), 4 * np.sqrt(100) / 100 + 2 / 10)
    assert np.isclose(
        surface_to_volume_ratio(100, 10, 50, method="footprint_perimeter"),
        50 / 100 + 2 / 10,
    )
    assert surface_to_volume_ratio(100, 20) < surface_to_volume_ratio(100, 10)


def test_missing_height_is_neutral():
    """Missing and invalid heights remain missing S/V and receive factor one."""
    ratios = surface_to_volume_ratio([100, 100, 100], [np.nan, 0, -1])
    assert np.isnan(ratios).all()
    assert np.array_equal(
        normalised_factor(surface_volume_power(ratios, 0.33), 1.0), np.ones(3)
    )


def test_surface_volume_normalisation():
    """Valid compactness corrections have floor-area-weighted mean one."""
    floor_area = np.array([100.0, 300.0])
    power = surface_volume_power(surface_to_volume_ratio([100, 100], [5, 30]), 0.33)
    factors = normalised_factor(power, weighted_reference(floor_area, power))
    assert np.isclose(np.average(factors, weights=floor_area), 1.0)


def test_age_factors_and_missing_age():
    """Canonical old/reference/new stocks and mixtures are count weighted."""
    multipliers = {"before_1991": 1.25, "1991_2000": 1.0, "after_2000": 0.8}
    assert age_factor_from_counts({"before_1991": 100}, multipliers) == 1.25
    assert age_factor_from_counts({"1991_2000": 100}, multipliers) == 1.0
    assert age_factor_from_counts({"after_2000": 100}, multipliers) == 0.8
    assert age_factor_from_counts(
        {"before_1991": 20, "1991_2000": 30, "after_2000": 50}, multipliers
    ) == (20 * 1.25 + 30 + 50 * 0.8) / 100
    assert np.isnan(age_factor_from_counts({}, multipliers))
    assert normalised_factor(np.nan, 1.1) == 1.0


def test_disabled_corrections_equal_floor_area():
    """All-neutral factors reproduce corrected floor area exactly."""
    floor_area = np.array([100.0, 250.0])
    assert np.array_equal(space_heat_weight(floor_area, 1, 1), floor_area)


def test_high_rise_compactness_synthetic_integration():
    """Equal floor stocks favour low-rise support unless elasticity is zero."""
    floor_area = np.array([1_000.0, 1_000.0])
    ratio = surface_to_volume_ratio([100, 100], [5, 50])
    power = surface_volume_power(ratio, 0.33)
    factors = normalised_factor(power, weighted_reference(floor_area, power))
    weights = space_heat_weight(floor_area, factors)
    assert weights[0] > weights[1]

    power_zero = surface_volume_power(ratio, 0)
    zero_factors = normalised_factor(
        power_zero, weighted_reference(floor_area, power_zero)
    )
    assert np.array_equal(space_heat_weight(floor_area, zero_factors), floor_area)


def test_countrywide_age_normalisation_synthetic_integration():
    """Age changes regional weights while country-normalised shares sum to one."""
    floor_area = np.array([1_000.0, 1_000.0])
    raw_age = np.array([1.25, 0.8])
    age = normalised_factor(raw_age, weighted_reference(floor_area, raw_age))
    weights = space_heat_weight(floor_area, f_age=age)
    assert weights[0] > weights[1]
    assert not np.array_equal(weights, floor_area)
    assert np.isclose((weights / weights.sum()).sum(), 1.0)
