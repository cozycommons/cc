"""Fail-closed backend capabilities for the Dice sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping


LOCAL_SUPABASE_URL = "http://127.0.0.1:54321"
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

    def require_safe_supabase_url(self, supabase_url: str | None) -> None:
        if self.is_dice_sandbox and supabase_url != LOCAL_SUPABASE_URL:
            raise RuntimeError(
                f"DICE_LOCAL_HARNESS requires SUPABASE_URL={LOCAL_SUPABASE_URL}; "
                f"got {supabase_url!r}"
            )


def initialize_runtime_policy(
    environment: Mapping[str, str],
    load_environment: Callable[[], object],
) -> RuntimePolicy:
    """Load normal configuration, then freeze the runtime's capabilities."""
    is_dice_sandbox = _enabled(environment, "DICE_LOCAL_HARNESS")
    if not is_dice_sandbox:
        load_environment()

    return RuntimePolicy(
        is_dice_sandbox=is_dice_sandbox,
        scheduler_enabled=(
            not is_dice_sandbox and _enabled(environment, "ENABLE_SCHEDULER")
        ),
        allow_cache_warmup=not is_dice_sandbox,
        allow_external_side_effects=not is_dice_sandbox,
    )
