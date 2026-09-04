"""Tests for the FHIR-to-graph converter's observation rendering.

Focuses on _render_observation and its handling of component arrays
(e.g., Blood Pressure panels with systolic/diastolic components).
"""

from __future__ import annotations

import sys
from pathlib import Path

# The converter lives in scripts/, not in the package. Add it to sys.path.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from convert_fhir_to_graph import _render_observation  # noqa: E402

# ---------------------------------------------------------------------------
# _render_observation — top-level value
# ---------------------------------------------------------------------------


def test_render_observation_value_quantity() -> None:
    """Observation with a top-level valueQuantity renders the value."""
    resource = {
        "code": {"coding": [{"display": "Heart Rate"}]},
        "valueQuantity": {"value": 72, "unit": "/min"},
        "effectiveDateTime": "2024-01-15",
        "category": [{"coding": [{"display": "vital-signs"}]}],
    }
    display, props = _render_observation(resource)

    assert display == "Heart Rate = 72 /min"
    assert props["effectiveDateTime"] == "2024-01-15"
    assert props["category"] == "vital-signs"
    assert "components" not in props


def test_render_observation_value_codeable_concept() -> None:
    """Observation with a valueCodeableConcept renders the concept."""
    resource = {
        "code": {"coding": [{"display": "Tobacco Use"}]},
        "valueCodeableConcept": {"coding": [{"display": "Never smoker"}]},
        "effectiveDateTime": "2024-02-01",
    }
    display, props = _render_observation(resource)

    assert display == "Tobacco Use = Never smoker"
    assert "components" not in props


# ---------------------------------------------------------------------------
# _render_observation — component values (BP panels)
# ---------------------------------------------------------------------------


def test_render_observation_bp_panel_with_components() -> None:
    """BP panel with component array renders component values in display."""
    resource = {
        "code": {"coding": [{"display": "Blood Pressure Panel"}]},
        "effectiveDateTime": "2024-01-15",
        "category": [{"coding": [{"display": "vital-signs"}]}],
        "component": [
            {
                "code": {"coding": [{"display": "Systolic Blood Pressure"}]},
                "valueQuantity": {"value": 140, "unit": "mmHg"},
            },
            {
                "code": {"coding": [{"display": "Diastolic Blood Pressure"}]},
                "valueQuantity": {"value": 90, "unit": "mmHg"},
            },
        ],
    }
    display, props = _render_observation(resource)

    # Display should include component values since there's no top-level value
    assert "Blood Pressure Panel:" in display
    assert "Systolic Blood Pressure 140 mmHg" in display
    assert "Diastolic Blood Pressure 90 mmHg" in display

    # Components stored in properties
    assert "components" in props
    assert len(props["components"]) == 2
    assert props["components"][0] == {
        "name": "Systolic Blood Pressure",
        "value": 140,
        "unit": "mmHg",
    }
    assert props["components"][1] == {
        "name": "Diastolic Blood Pressure",
        "value": 90,
        "unit": "mmHg",
    }


def test_render_observation_component_with_top_level_value() -> None:
    """When both top-level value and components exist, display uses top-level."""
    resource = {
        "code": {"coding": [{"display": "Blood Pressure Panel"}]},
        "valueQuantity": {"value": 120, "unit": "mmHg"},
        "effectiveDateTime": "2024-01-15",
        "component": [
            {
                "code": {"coding": [{"display": "Systolic Blood Pressure"}]},
                "valueQuantity": {"value": 120, "unit": "mmHg"},
            },
        ],
    }
    display, props = _render_observation(resource)

    # Top-level value takes precedence for display
    assert display == "Blood Pressure Panel = 120 mmHg"
    # Components still stored in properties
    assert "components" in props
    assert len(props["components"]) == 1


def test_render_observation_component_without_value_quantity_skipped() -> None:
    """Components without valueQuantity are excluded from the list."""
    resource = {
        "code": {"coding": [{"display": "Lab Panel"}]},
        "effectiveDateTime": "2024-01-15",
        "component": [
            {
                "code": {"coding": [{"display": "Result A"}]},
                "valueQuantity": {"value": 5.5, "unit": "mg/dL"},
            },
            {
                "code": {"coding": [{"display": "Result B"}]},
                # No valueQuantity — should be skipped
                "valueCodeableConcept": {"coding": [{"display": "Normal"}]},
            },
        ],
    }
    display, props = _render_observation(resource)

    assert "components" in props
    assert len(props["components"]) == 1
    assert props["components"][0]["name"] == "Result A"


def test_render_observation_empty_component_array() -> None:
    """Empty component array produces no components in properties."""
    resource = {
        "code": {"coding": [{"display": "Observation"}]},
        "effectiveDateTime": "2024-01-15",
        "component": [],
    }
    display, props = _render_observation(resource)

    assert display == "Observation"
    assert "components" not in props


def test_render_observation_no_value_no_components() -> None:
    """Observation with no value and no components renders just the code."""
    resource = {
        "code": {"coding": [{"display": "Unknown Observation"}]},
        "effectiveDateTime": "2024-01-15",
    }
    display, props = _render_observation(resource)

    assert display == "Unknown Observation"
    assert "components" not in props
