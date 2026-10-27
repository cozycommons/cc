from copy import deepcopy

import pytest
from fastapi import HTTPException

from floor_planner.agent_operations import apply_operations, scene_schema


def rectangle(element_id='rect-1', **changes):
    return {'id': element_id, 'type': 'rectangle', 'x': 10, 'y': 20, 'width': 30, 'height': 40, 'rotation': 0, **changes}


def scene():
    return {'version': 2, 'units': 'inches', 'rooms': [{'name': 'Kitchen'}], 'elements': [rectangle()], 'viewport': {'x': 2, 'y': 3, 'zoom': 1}, 'source': {'note': 'Measured reference'}}


def test_sequential_batch_preserves_unrelated_geometry_metadata_and_input():
    original = scene()
    before = deepcopy(original)
    result = apply_operations(original, [
        {'op': 'add', 'element': rectangle('new', x=50)},
        {'op': 'update', 'id': 'new', 'changes': {'width': 55, 'rotation': 90, 'label': 'Desk'}},
        {'op': 'delete', 'id': 'rect-1'},
    ])
    assert result['elements'] == [rectangle('new', x=50, width=55, rotation=90, label='Desk')]
    assert {key: value for key, value in result.items() if key != 'elements'} == {key: value for key, value in original.items() if key != 'elements'}
    assert original == before


@pytest.mark.parametrize('operations', [
    [], [{'op': 'delete', 'id': 'rect-1'}] * 101,
    [{'op': 'add', 'element': rectangle()}],
    [{'op': 'delete', 'id': 'unknown'}],
    [{'op': 'update', 'id': 'rect-1', 'changes': {}}],
    [{'op': 'update', 'id': 'rect-1', 'changes': {'id': 'other'}}],
    [{'op': 'update', 'id': 'rect-1', 'changes': {'type': 'wall'}}],
    [{'op': 'update', 'id': 'rect-1', 'changes': {'visibility': 'public'}}],
    [{'op': 'update', 'id': 'rect-1', 'changes': {'width': -1}}],
    [{'op': 'update', 'id': 'rect-1', 'changes': {'x': float('nan')}}],
    [{'op': 'add', 'element': {'id': 'bad', 'type': 'rectangle'}}],
    [{'op': 'add', 'element': {'id': 'bad', 'type': []}}],
    [{'op': 'rename', 'title': 'New name'}],
    [{'op': 'delete', 'id': 'rect-1', 'unexpected': True}],
])
def test_invalid_batch_has_no_partial_mutation(operations):
    original = scene()
    before = deepcopy(original)
    with pytest.raises(HTTPException) as failure:
        apply_operations(original, operations)
    assert failure.value.status_code == 422
    assert original == before


def test_later_failure_does_not_apply_earlier_changes():
    original = scene()
    with pytest.raises(HTTPException):
        apply_operations(original, [{'op': 'update', 'id': 'rect-1', 'changes': {'x': 100}}, {'op': 'delete', 'id': 'missing'}])
    assert original['elements'][0]['x'] == 10


def test_scene_limits_still_apply_after_edits():
    original = scene()
    original['elements'] = [rectangle(str(index)) for index in range(10000)]
    with pytest.raises(HTTPException) as failure:
        apply_operations(original, [{'op': 'add', 'element': rectangle('overflow')}])
    assert failure.value.status_code == 422
    assert len(original['elements']) == 10000


def test_schema_examples_can_be_applied_and_leave_no_elements():
    original = scene()
    original['elements'] = []
    assert apply_operations(original, scene_schema()['example_operations'])['elements'] == []
