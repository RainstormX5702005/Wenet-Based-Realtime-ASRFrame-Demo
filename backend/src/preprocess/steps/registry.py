"""Step registration helpers used by pipeline contract checks."""

from __future__ import annotations

from typing import Iterable

REGISTERED_STEP_TYPES: set[type] = set()


def register_step(step_type: type) -> type:
    """Registers a preprocess step type for runtime validation."""

    REGISTERED_STEP_TYPES.add(step_type)
    return step_type


def is_registered(step: object) -> bool:
    """Returns True when a step instance is of a registered type."""

    return any(isinstance(step, registered) for registered in REGISTERED_STEP_TYPES)


def registered_types() -> Iterable[type]:
    """Returns snapshot of registry types."""

    return tuple(REGISTERED_STEP_TYPES)
