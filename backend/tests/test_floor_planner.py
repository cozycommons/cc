import math
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from floor_planner.routes import UpdatePlan, normalize_scene, verified_email


def valid_scene():
    return {
        "version": 2,
        "title": "Plan",
        "units": "inches",
        "rooms": [],
        "elements": [{"id": "wall-1", "type": "wall", "x": 0, "y": 0, "length": 24, "thickness": 4, "rotation": 0}],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }


def test_only_email_confirmation_counts_as_verified():
    assert verified_email(SimpleNamespace(email="Reader@Example.test", email_confirmed_at=None, confirmed_at="phone")) is None
    assert verified_email(SimpleNamespace(email="Reader@Example.test", email_confirmed_at="email", confirmed_at=None)) == "reader@example.test"


def test_scene_validation_rejects_renderer_crashes_and_bad_numbers():
    assert normalize_scene(valid_scene())["elements"][0]["type"] == "wall"
    invalid_scenes = [
        valid_scene() | {"viewport": {}},
        valid_scene() | {"elements": [{"id": "x", "type": "wall", "x": math.nan, "y": 0, "length": 24, "thickness": 4, "rotation": 0}]},
        valid_scene() | {"elements": [valid_scene()["elements"][0], valid_scene()["elements"][0]]},
        valid_scene() | {"elements": [{**valid_scene()["elements"][0], "label": {"crash": True}}]},
        valid_scene() | {"elements": [{"id": "unknown", "type": "circle"}]},
    ]
    for scene in invalid_scenes:
        with pytest.raises(HTTPException):
            normalize_scene(scene)


@pytest.mark.parametrize("field", ["title", "visibility", "scene"])
def test_plan_updates_reject_explicit_null(field):
    with pytest.raises(ValidationError):
        UpdatePlan.model_validate({"expected_revision": 1, field: None})
