"""Strict, dependency-free validation for the public project-input contract."""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Mapping


class InputContractError(ValueError):
    """Raised when project_input does not satisfy the published JSON contract."""


_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "project-input.schema.json"


def _load_schema() -> dict[str, Any]:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(schema, dict):
        raise InputContractError("project input schema must be an object")
    return schema


def _resolve_ref(root: Mapping[str, Any], reference: str) -> Mapping[str, Any]:
    if not reference.startswith("#/"):
        raise InputContractError(f"unsupported schema reference: {reference}")
    node: Any = root
    for part in reference[2:].split("/"):
        if not isinstance(node, Mapping):
            raise InputContractError(f"invalid schema reference: {reference}")
        node = node.get(part.replace("~1", "/").replace("~0", "~"))
    if not isinstance(node, Mapping):
        raise InputContractError(f"invalid schema reference: {reference}")
    return node


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    raise InputContractError(f"unsupported schema type: {expected}")


def _validate_node(
    value: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
    *,
    allow_missing_required: bool = False,
) -> None:
    reference = schema.get("$ref")
    if isinstance(reference, str):
        _validate_node(
            value,
            _resolve_ref(root, reference),
            root,
            path,
            allow_missing_required=allow_missing_required,
        )
        return

    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not all(isinstance(item, str) for item in types) or not any(
            _type_matches(value, item) for item in types
        ):
            raise InputContractError(f"{path} must be {expected}")

    if "const" in schema and value != schema["const"]:
        raise InputContractError(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        raise InputContractError(f"{path} must be one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise InputContractError(f"{path} is too short")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            raise InputContractError(f"{path} does not match required pattern")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise InputContractError(f"{path} must be finite")
        if "minimum" in schema and value < schema["minimum"]:
            raise InputContractError(f"{path} must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise InputContractError(f"{path} must be <= {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            raise InputContractError(f"{path} must be > {schema['exclusiveMinimum']}")

    if isinstance(value, Mapping):
        raw_properties = schema.get("properties", {})
        properties = raw_properties if isinstance(raw_properties, Mapping) else {}
        additional = schema.get("additionalProperties", True)
        if additional is False:
            unknown = sorted(name for name in value if name not in properties)
            if unknown:
                names = ", ".join(f"{path}.{name}" for name in unknown)
                raise InputContractError(f"unknown field(s): {names}")
        required = [] if allow_missing_required else schema.get("required", [])
        missing = sorted(name for name in required if name not in value)
        if missing:
            names = ", ".join(f"{path}.{name}" for name in missing)
            raise InputContractError(f"missing field(s): {names}")
        for name, child in value.items():
            child_path = f"{path}.{name}"
            if name in properties:
                _validate_node(
                    child,
                    properties[name],
                    root,
                    child_path,
                    allow_missing_required=(
                        True if name == "overrides" else allow_missing_required
                    ),
                )
            elif isinstance(additional, Mapping):
                _validate_node(
                    child,
                    additional,
                    root,
                    child_path,
                    allow_missing_required=allow_missing_required,
                )

    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise InputContractError(f"{path} has too few items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise InputContractError(f"{path} has too many items")
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                _validate_node(
                    item,
                    items,
                    root,
                    f"{path}[{index}]",
                    allow_missing_required=allow_missing_required,
                )


def validate_project_input(value: Mapping[str, Any]) -> None:
    """Reject unknown or structurally invalid project fields before calculation."""

    if not isinstance(value, Mapping):
        raise InputContractError("project_input must be an object")
    schema = _load_schema()
    _validate_node(value, schema, schema, "$")


def validate_project_fragment(value: Mapping[str, Any], *, label: str) -> None:
    """Validate a partial user/default layer without allowing unknown fields."""

    if not isinstance(value, Mapping):
        raise InputContractError(f"{label} must be an object")
    schema = _load_schema()
    _validate_node(
        value,
        schema,
        schema,
        f"$.{label}",
        allow_missing_required=True,
    )
