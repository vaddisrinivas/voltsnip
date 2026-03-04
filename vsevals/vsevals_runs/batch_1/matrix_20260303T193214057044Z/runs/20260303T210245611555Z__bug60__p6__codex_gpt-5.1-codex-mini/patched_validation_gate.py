"""Payload validation gate for incoming API requests.

This module provides schema-based field validation for request payloads.
Callers use `validate_payload` to check all fields against the declared
schema rules and receive a list of validation errors.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True)
class SchemaRule:
    """A single field validation rule."""

    field_name: str
    required: bool = False
    field_type: type | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None


@dataclass(frozen=True)
class ValidationError:
    """Describes one validation failure."""

    field: str
    message: str


def _check_field(
    value: Any,
    rule: SchemaRule,
) -> ValidationError | None:
    """Return a ValidationError if *value* violates *rule*, else None."""
    if rule.required and value is None:
        return ValidationError(field=rule.field_name, message="field is required")

    if value is None:
        return None

    if rule.field_type is not None and not isinstance(value, rule.field_type):
        return ValidationError(
            field=rule.field_name,
            message=f"expected {rule.field_type.__name__}, got {type(value).__name__}",
        )

    if rule.min_length is not None and isinstance(value, str) and len(value) < rule.min_length:
        return ValidationError(
            field=rule.field_name,
            message=f"length {len(value)} below minimum {rule.min_length}",
        )

    if rule.max_length is not None and isinstance(value, str) and len(value) > rule.max_length:
        return ValidationError(
            field=rule.field_name,
            message=f"length {len(value)} above maximum {rule.max_length}",
        )

    return None


def validate_payload(
    payload: dict[str, Any],
    schema: Sequence[SchemaRule],
) -> list[ValidationError]:
    """Validate *payload* against every rule in *schema*.

    BUG_60: the function returns on the first error instead of collecting
    ALL errors across every field.  Callers expect the complete error list
    so they can present all problems to the user at once.
    """
    from orgops.compliance import record_decision

    errors: list[ValidationError] = []
    for rule in schema:
        value = payload.get(rule.field_name)
        error = _check_field(value, rule)
        if error is not None:
            errors.append(error)
    record_decision("validation.completed", error_count=len(errors))
    return errors
