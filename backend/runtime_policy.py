"""Fail-closed backend capabilities for the owned local Commons sandboxes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping


LOCAL_SUPABASE_URL = "http://127.0.0.1:54321"
TRIPS_LOCAL_SUPABASE_URL = "http://127.0.0.1:55321"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _enabled(environment: Mapping[str, str], name: str) -> bool:
    return environment.get(name, "").strip().lower() in _TRUE_VALUES


@dataclass(frozen=True)
class RuntimePolicy:
    """Capabilities fixed once from the backend's startup environment."""

    is_dice_sandbox: bool
    scheduler_enabled: bool
    allow_cache_warmup: bool
    allow_external_side_effects: bool
    is_trips_sandbox: bool = False

    def require_safe_supabase_url(self, supabase_url: str | None) -> None:
        if self.is_dice_sandbox and supabase_url != LOCAL_SUPABASE_URL:
            raise RuntimeError(
                f"DICE_LOCAL_HARNESS requires SUPABASE_URL={LOCAL_SUPABASE_URL}; "
                f"got {supabase_url!r}"
            )
        if self.is_trips_sandbox and supabase_url != TRIPS_LOCAL_SUPABASE_URL:
            raise RuntimeError(
                f"COZY_TRIPS_LOCAL requires SUPABASE_URL={TRIPS_LOCAL_SUPABASE_URL}; "
                f"got {supabase_url!r}"
            )


def initialize_runtime_policy(
    environment: Mapping[str, str],
    load_environment: Callable[[], object],
) -> RuntimePolicy:
    """Load normal configuration, then freeze the runtime's capabilities."""
    is_dice_sandbox = _enabled(environment, "DICE_LOCAL_HARNESS")
    is_trips_sandbox = _enabled(environment, "COZY_TRIPS_LOCAL")
    if is_dice_sandbox and is_trips_sandbox:
        raise RuntimeError("Choose one local harness; Dice and Trips own different databases.")
    is_local = is_dice_sandbox or is_trips_sandbox
    if not is_local:
        load_environment()

    return RuntimePolicy(
        is_dice_sandbox=is_dice_sandbox,
        is_trips_sandbox=is_trips_sandbox,
        scheduler_enabled=(
            not is_local and _enabled(environment, "ENABLE_SCHEDULER")
        ),
        allow_cache_warmup=not is_local,
        allow_external_side_effects=not is_local,
    )
