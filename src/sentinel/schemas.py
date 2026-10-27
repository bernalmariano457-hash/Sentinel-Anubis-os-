from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError, SchemaError

from sentinel import SentinelError

_SCHEMA_FILES: dict[str, str] = {
    "operator": "operator.v1.json",
    "custody-entry": "custody-entry.v1.json",
    "artifact-manifest": "artifact-manifest.v1.json",
    "package-manifest": "package-manifest.v1.json",
    "operation": "operation.v1.json",
    "timeline-event": "timeline-event.v1.json",
}

_SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "schemas"


class SentinelSchemaError(SentinelError):


class SchemaValidationError(SentinelSchemaError):

    def __init__(self, schema_name: str, errors: list[ValidationError]) -> None:
        self.schema_name = schema_name
        self.errors = errors
        lines = [f"{e.json_path}: {e.message}" for e in errors]
        super().__init__(
            f"entity does not match schema {schema_name!r}:\n  "
            + "\n  ".join(lines)
        )


class SchemaNotFoundError(SentinelSchemaError):


class SchemaLoadError(SentinelSchemaError):


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:

    if name not in _SCHEMA_FILES:
        raise SchemaNotFoundError(
            f"unknown schema {name!r}; registered: {sorted(_SCHEMA_FILES)}"
        )
    path = _SCHEMAS_DIR / _SCHEMA_FILES[name]
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise SchemaLoadError(f"schema file not found: {path}") from e
    except OSError as e:
        raise SchemaLoadError(f"cannot read {path}: {e}") from e
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SchemaLoadError(f"invalid JSON in {path}: {e}") from e
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        raise SchemaLoadError(f"invalid JSON Schema in {path}: {e}") from e
    return schema


@lru_cache(maxsize=None)
def _get_validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        load_schema(name),
        format_checker=FormatChecker(),
    )


def validate(instance: Any, schema_name: str) -> None:

    validator = _get_validator(schema_name)
    errors = sorted(validator.iter_errors(
        instance), key=lambda e: list(e.path))
    if errors:
        raise SchemaValidationError(schema_name, errors)


def is_valid(instance: Any, schema_name: str) -> bool:

    try:
        validate(instance, schema_name)
    except SchemaValidationError:
        return False
    return True


def validate_or_raise(instance: Any, schema_name: str) -> None:
    validate(instance, schema_name)


def registered_schemas() -> tuple[str, ...]:
    return tuple(sorted(_SCHEMA_FILES))


def schema_path(name: str) -> Path:
    if name not in _SCHEMA_FILES:
        raise SchemaNotFoundError(f"unknown schema {name!r}")
    return _SCHEMAS_DIR / _SCHEMA_FILES[name]


__all__ = [
    "SchemaLoadError",
    "SchemaNotFoundError",
    "SchemaValidationError",
    "SentinelSchemaError",
    "is_valid",
    "load_schema",
    "registered_schemas",
    "schema_path",
    "validate",
    "validate_or_raise",
]
