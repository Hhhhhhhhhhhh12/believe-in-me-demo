from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .state import CardRef

HEAVENLY_TRUTH_VALUES: dict[str, int] = {
    "Segen": 1,
    "Aufklärer": 1,
    "Reliquie": 1,
    "Heiliges Heer": 3,
}
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOLS_DE_PATH = ROOT / "data" / "pools_de.json"
DEFAULT_CARDS_NORMALIZED_DE_PATH = ROOT / "data" / "cards_normalized_de.json"


def make_heavenly_card(
    *,
    card_id: str,
    name: str,
    category: str,
    metadata: dict[str, Any] | None = None,
) -> CardRef:
    if category not in HEAVENLY_TRUTH_VALUES:
        raise ValueError(f"Unsupported heavenly card category: {category}.")

    return CardRef(
        card_id=card_id,
        name=name,
        category=category,
        truth_value=HEAVENLY_TRUTH_VALUES[category],
        metadata=dict(metadata or {}),
    )


def make_truth_card(
    value: int,
    *,
    card_id: str | None = None,
    name: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> CardRef:
    if value <= 0:
        raise ValueError(f"Truth card value must be positive, got {value}.")

    return CardRef(
        card_id=card_id or f"truth-{value}",
        name=name or f"Wahrheit {value}",
        category="Wahrheit",
        truth_value=value,
        metadata=dict(metadata or {}),
    )


def build_default_body_part_draw_pile() -> list[CardRef]:
    return [
        CardRef(
            card_id=card["card_id"],
            name=card["name"],
            category=card["category"],
            metadata={
                "alignment": card.get("alignment"),
                "attribute": card.get("attribute"),
                "source_row": card.get("source_row"),
            },
        )
        for card in _load_body_part_cards()
    ]


def build_default_heavenly_draw_pile() -> list[CardRef]:
    return [
        make_heavenly_card(
            card_id=card["card_id"],
            name=card["name"],
            category=card["category"],
            metadata={
                "alignment": card.get("alignment"),
                "rules_text": card.get("rules_text"),
                "cost_believers": card.get("cost_believers"),
                "source_row": card.get("source_row"),
            },
        )
        for card in _load_heavenly_cards()
    ]


def build_default_commandment_draw_pile() -> list[CardRef]:
    return [
        CardRef(
            card_id=card["card_id"],
            name=card["name"],
            category=card["category"],
            metadata={
                "alignment": card.get("alignment"),
                "rules_text": card.get("rules_text"),
                "cost_believers": card.get("cost_believers"),
                "source_row": card.get("source_row"),
            },
        )
        for card in _load_commandment_cards()
    ]


def build_default_phenomenon_draw_pile() -> list[CardRef]:
    return [
        CardRef(
            card_id=card["card_id"],
            name=card["name"],
            category=card["category"],
            metadata={
                "alignment": card.get("alignment"),
                "source_row": card.get("source_row"),
            },
        )
        for card in _load_phenomenon_cards()
    ]


def build_default_monument_draw_pile() -> list[CardRef]:
    return [
        CardRef(
            card_id=card["card_id"],
            name=card["name"],
            category=card["category"],
            metadata={
                "alignment": card.get("alignment"),
                "monument_part": _extract_monument_part(card.get("card_id")),
                "source_row": card.get("source_row"),
            },
        )
        for card in _load_monument_cards()
    ]


def get_non_hand_card_metadata(card_id: str) -> dict[str, Any] | None:
    for card in _load_non_hand_cards():
        if isinstance(card, dict) and card.get("card_id") == card_id:
            return dict(card)
    return None


@lru_cache(maxsize=1)
def _load_non_hand_cards() -> tuple[dict[str, Any], ...]:
    payload = json.loads(DEFAULT_POOLS_DE_PATH.read_text(encoding="utf-8"))
    cards = payload.get("non_hand_cards", [])
    if not isinstance(cards, list):
        raise ValueError("Expected non_hand_cards in pools_de.json to be a list.")
    return tuple(card for card in cards if isinstance(card, dict))


@lru_cache(maxsize=1)
def _load_body_part_cards() -> tuple[dict[str, Any], ...]:
    non_hand_body_parts = tuple(
        card
        for card in _load_non_hand_cards()
        if isinstance(card, dict) and str(card.get("category", "")).startswith("Körperteil")
    )
    if non_hand_body_parts:
        return non_hand_body_parts

    payload = json.loads(DEFAULT_CARDS_NORMALIZED_DE_PATH.read_text(encoding="utf-8"))
    cards = payload.get("cards", [])
    if not isinstance(cards, list):
        raise ValueError("Expected cards_normalized_de.json to expose cards as a list.")

    return tuple(
        card
        for card in cards
        if isinstance(card, dict) and str(card.get("category", "")).startswith("Körperteil")
    )


@lru_cache(maxsize=1)
def _load_heavenly_cards() -> tuple[dict[str, Any], ...]:
    payload = json.loads(DEFAULT_CARDS_NORMALIZED_DE_PATH.read_text(encoding="utf-8"))
    cards = payload.get("cards", [])
    if not isinstance(cards, list):
        raise ValueError("Expected cards_normalized_de.json to expose cards as a list.")

    return tuple(
        card
        for card in cards
        if isinstance(card, dict)
        and str(card.get("category", "")) in HEAVENLY_TRUTH_VALUES
        and card.get("playable") is True
    )


@lru_cache(maxsize=1)
def _load_commandment_cards() -> tuple[dict[str, Any], ...]:
    payload = json.loads(DEFAULT_CARDS_NORMALIZED_DE_PATH.read_text(encoding="utf-8"))
    cards = payload.get("cards", [])
    if not isinstance(cards, list):
        raise ValueError("Expected cards_normalized_de.json to expose cards as a list.")

    return tuple(
        card
        for card in cards
        if isinstance(card, dict)
        and str(card.get("category", "")) == "Gebote"
        and card.get("playable") is True
    )


@lru_cache(maxsize=1)
def _load_phenomenon_cards() -> tuple[dict[str, Any], ...]:
    payload = json.loads(DEFAULT_CARDS_NORMALIZED_DE_PATH.read_text(encoding="utf-8"))
    cards = payload.get("cards", [])
    if not isinstance(cards, list):
        raise ValueError("Expected cards_normalized_de.json to expose cards as a list.")

    return tuple(
        card
        for card in cards
        if isinstance(card, dict) and card.get("category") == "Phänomene"
    )


@lru_cache(maxsize=1)
def _load_monument_cards() -> tuple[dict[str, Any], ...]:
    payload = json.loads(DEFAULT_CARDS_NORMALIZED_DE_PATH.read_text(encoding="utf-8"))
    cards = payload.get("cards", [])
    if not isinstance(cards, list):
        raise ValueError("Expected cards_normalized_de.json to expose cards as a list.")

    return tuple(
        card
        for card in cards
        if isinstance(card, dict) and card.get("category") == "Monument"
    )


def _extract_monument_part(card_id: Any) -> int | None:
    if not isinstance(card_id, str):
        return None
    match = re.search(r"-(\d{2})__Monument__", card_id)
    if match is None:
        return None
    parsed = int(match.group(1))
    return parsed if parsed in {1, 2, 3} else None
