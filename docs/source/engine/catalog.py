from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CATALOG_FILES = (
    "data/cards_normalized_de.json",
    "data/pools_de.json",
)


def get_card_record(card_id: str) -> dict[str, Any] | None:
    return _load_card_catalog().get(card_id)


def get_card_alignment(card_id: str) -> str | None:
    record = get_card_record(card_id)
    if record is None:
        return None
    alignment = record.get("alignment")
    return alignment if isinstance(alignment, str) else None
@lru_cache(maxsize=1)
def _load_card_catalog() -> dict[str, dict[str, Any]]:
    return {
        record["card_id"]: record
        for record in _load_card_records()
        if isinstance(record.get("card_id"), str)
    }


@lru_cache(maxsize=1)
def _load_card_records() -> tuple[dict[str, Any], ...]:
    root_dir = Path(__file__).resolve().parent.parent
    merged_records: list[dict[str, Any]] = []
    seen_card_ids: set[str] = set()

    for relative_path in CATALOG_FILES:
        path = root_dir / relative_path
        if not path.exists():
            continue

        payload = json.loads(path.read_text())
        raw_records = payload.get("cards") if isinstance(payload, dict) else payload
        if not isinstance(raw_records, list):
            continue

        for record in raw_records:
            if not isinstance(record, dict):
                continue
            card_id = record.get("card_id")
            if not isinstance(card_id, str) or card_id in seen_card_ids:
                continue
            seen_card_ids.add(card_id)
            merged_records.append(record)

    return tuple(merged_records)
