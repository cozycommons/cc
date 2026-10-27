"""Bounded element edits shared by the MCP tools and their validation tests."""
from copy import deepcopy
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import Field, StringConstraints, TypeAdapter, ValidationError

from .routes import Input, normalize_scene

ElementId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
GEOMETRY_FIELDS = {
    'wall': ('x', 'y', 'length', 'thickness', 'rotation'),
    'opening': ('x', 'y', 'width', 'thickness', 'rotation'),
    'rectangle': ('x', 'y', 'width', 'height', 'rotation'),
    'ellipse': ('x', 'y', 'width', 'height', 'rotation'),
    'furniture': ('x', 'y', 'width', 'height', 'rotation'),
    'line': ('x1', 'y1', 'x2', 'y2'),
    'freehand': ('points',),
}


class AddElement(Input):
    op: Literal['add']
    element: dict


class UpdateElement(Input):
    op: Literal['update']
    id: ElementId
    changes: Annotated[dict, Field(min_length=1)]


class DeleteElement(Input):
    op: Literal['delete']
    id: ElementId


EditOperation = Annotated[AddElement | UpdateElement | DeleteElement, Field(discriminator='op')]
EditOperations = Annotated[list[EditOperation], Field(min_length=1, max_length=100)]
OPERATIONS = TypeAdapter(EditOperations)


def apply_operations(scene: dict, operations: list) -> dict:
    """Return a validated scene without mutating the input or touching plan metadata."""
    try:
        edits = OPERATIONS.validate_python(operations)
    except ValidationError as error:
        raise HTTPException(422, 'Provide 1–100 valid add, update, or delete operations.') from error
    result = deepcopy(scene)
    elements = result['elements']
    for operation in edits:
        if isinstance(operation, AddElement):
            element = deepcopy(operation.element)
            element_id = element.get('id')
            if not isinstance(element_id, str) or not element_id.strip() or len(element_id) > 128:
                raise HTTPException(422, 'New elements need a unique nonblank ID of at most 128 characters.')
            if any(item['id'] == element_id for item in elements):
                raise HTTPException(422, f'Element {element_id} already exists.')
            kind = element.get('type')
            if not isinstance(kind, str) or kind not in GEOMETRY_FIELDS:
                raise HTTPException(422, 'Use a supported element type and its documented fields.')
            fields = set(GEOMETRY_FIELDS.get(kind, ())) | {'id', 'type', 'label', 'kind', 'furnitureType'}
            if element.keys() - fields:
                raise HTTPException(422, 'Use a supported element type and its documented fields.')
            elements.append(element)
        else:
            index = next((index for index, item in enumerate(elements) if item['id'] == operation.id), None)
            if index is None:
                raise HTTPException(422, f'Element {operation.id} does not exist. Read the current plan before editing.')
            if isinstance(operation, DeleteElement):
                elements.pop(index)
            else:
                element = elements[index]
                fields = set(GEOMETRY_FIELDS[element['type']]) | {'label', 'kind', 'furnitureType'}
                if operation.changes.keys() - fields:
                    raise HTTPException(422, 'An update may change only the element’s documented geometry or labels. IDs and types stay fixed.')
                element.update(deepcopy(operation.changes))
    return normalize_scene(result)


def scene_schema() -> dict:
    return {
        'version': 2,
        'units': 'inches',
        'coordinates': 'Positive x goes right, positive y goes down. Rotation is clockwise degrees. Walls, openings, rectangles, ellipses and furniture use center x/y.',
        'elements': {kind: {'required_geometry': list(fields)} for kind, fields in GEOMETRY_FIELDS.items()},
        'optional_fields': {'label': 'Text label', 'kind': 'For openings: door or window. A door opening cuts a gap; it does not create a swing arc.', 'furnitureType': 'For furniture: bed, desk or chair.'},
        'constraints': 'Finite coordinates within ±1,000,000 inches; dimensions greater than zero; unique IDs; at most 10,000 elements and 2 MiB per scene.',
        'editing': 'Read the plan first. Submit 1–100 add/update/delete operations with expected_revision. Operations apply in order and save atomically. On a revision conflict, read again before deciding how to reapply. Scene rooms, viewport, source notes and plan sharing settings are preserved.',
        'example_operations': [
            {'op': 'add', 'element': {'id': 'desk-rectangle', 'type': 'rectangle', 'x': 100, 'y': 120, 'width': 55, 'height': 28, 'rotation': 0, 'label': 'Desk'}},
            {'op': 'update', 'id': 'desk-rectangle', 'changes': {'x': 140, 'rotation': 90}},
            {'op': 'delete', 'id': 'desk-rectangle'},
        ],
    }
