from __future__ import annotations

from typing import Any


def append_event(event_log: list[dict[str, Any]], event_type: str, **payload: Any) -> dict[str, Any]:
    entry = {"type": event_type, **payload}
    event_log.append(entry)
    return entry

