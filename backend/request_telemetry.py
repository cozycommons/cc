from __future__ import annotations

import re
from collections.abc import Mapping


_OPERATION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def dice_live_request_tags(path: str, headers: Mapping[str, str]) -> dict[str, str]:
    if "/dice/live/games/" not in path or not path.endswith("/commands"):
        return {}
    attempt = headers.get("x-dice-live-attempt", "")
    operation_id = headers.get("x-dice-live-operation", "")
    tags: dict[str, str] = {}
    if attempt in {"original", "hedge", "retry"}:
        tags["dice_live_attempt"] = attempt
    if _OPERATION_ID.fullmatch(operation_id):
        tags["dice_live_operation_id"] = operation_id
    return tags
