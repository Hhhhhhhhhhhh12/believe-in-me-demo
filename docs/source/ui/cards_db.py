from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ui.beginner_mode import beginner_phenomenon_rules


DEFAULT_CONFIG_RELATIVE_PATH = Path("scripts/config.json")
DEFAULT_CARDS_RELATIVE_PATH = Path("data/cards_normalized_de.json")
DEFAULT_CARD_ASSETS_RELATIVE_PATH = Path("data/card_assets.json")
TEXT_FIELD_CANDIDATES = (
    "rules_text_kurz",
    "rules_text_short",
    "short_rules_text",
    "rules_text",
    "maintext",
    "text",
    "effect_text",
)


def _resolve_path(root_dir: Path, raw_path: str | None, fallback: Path) -> Path:
    if raw_path is None or not str(raw_path).strip():
        return (root_dir / fallback).resolve()
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    return (root_dir / candidate).resolve()


def resolve_cards_path(
    *,
    root_dir: Path,
    config_path: str | None = None,
    cards_path: str | None = None,
) -> Path:
    if cards_path is not None:
        return _resolve_path(root_dir, cards_path, DEFAULT_CARDS_RELATIVE_PATH)

    resolved_config_path = _resolve_path(root_dir, config_path, DEFAULT_CONFIG_RELATIVE_PATH)
    if resolved_config_path.exists():
        payload = json.loads(resolved_config_path.read_text(encoding="utf-8"))
        normalized_cfg = payload.get("normalize") if isinstance(payload, dict) else None
        output_cfg = normalized_cfg.get("output") if isinstance(normalized_cfg, dict) else None
        configured_cards_path = output_cfg.get("de") if isinstance(output_cfg, dict) else None
        if isinstance(configured_cards_path, str) and configured_cards_path.strip():
            return _resolve_path(root_dir, configured_cards_path, DEFAULT_CARDS_RELATIVE_PATH)

    return (root_dir / DEFAULT_CARDS_RELATIVE_PATH).resolve()


@dataclass(slots=True)
class CardsDB:
    cards_path: Path
    records_by_id: dict[str, dict[str, Any]]
    display_records_by_id: dict[str, dict[str, Any]] | None = None
    card_assets_path: Path | None = None
    assets_by_id: dict[str, dict[str, Any]] | None = None
    truth_assets_by_value: dict[int, dict[str, Any]] | None = None
    asset_language: str = "de"
    beginner_mode: bool = False

    @classmethod
    def load(
        cls,
        *,
        root_dir: Path,
        config_path: str | None = None,
        cards_path: str | None = None,
        card_assets_path: str | None = None,
        asset_language: str = "de",
    ) -> CardsDB:
        resolved_cards_path = resolve_cards_path(
            root_dir=root_dir,
            config_path=config_path,
            cards_path=cards_path,
        )
        payload = json.loads(resolved_cards_path.read_text(encoding="utf-8"))
        raw_records = payload.get("cards") if isinstance(payload, dict) else payload
        if not isinstance(raw_records, list):
            raise ValueError(f"Expected {resolved_cards_path} to contain a cards list.")

        records_by_id: dict[str, dict[str, Any]] = {}
        for record in raw_records:
            if not isinstance(record, dict):
                continue
            card_id = record.get("card_id")
            if isinstance(card_id, str) and card_id not in records_by_id:
                records_by_id[card_id] = record

        normalized_asset_language = _normalize_asset_language(asset_language)
        display_records_by_id: dict[str, dict[str, Any]] = {}
        if normalized_asset_language == "en":
            display_records_by_id = _load_display_records_by_source_row(
                resolved_cards_path=resolved_cards_path,
                records_by_id=records_by_id,
            )

        resolved_card_assets_path = _resolve_path(
            root_dir,
            card_assets_path,
            DEFAULT_CARD_ASSETS_RELATIVE_PATH,
        )
        assets_by_id: dict[str, dict[str, Any]] = {}
        if resolved_card_assets_path.exists():
            asset_payload = json.loads(resolved_card_assets_path.read_text(encoding="utf-8"))
            raw_assets = asset_payload.get("cards") if isinstance(asset_payload, dict) else {}
            if not isinstance(raw_assets, dict):
                raise ValueError(f"Expected {resolved_card_assets_path} to contain a cards object.")
            for card_id, asset_record in raw_assets.items():
                if isinstance(card_id, str) and isinstance(asset_record, dict):
                    assets_by_id[card_id] = dict(asset_record)

        truth_assets_by_value: dict[int, dict[str, Any]] = {}
        for card_id, asset_record in sorted(
            assets_by_id.items(),
            key=lambda item: int(item[1].get("source_page") or 0),
        ):
            record = records_by_id.get(card_id)
            if not isinstance(record, dict) or record.get("category") != "Wahrheit":
                continue
            raw_truth_value = record.get("truth_value")
            if not isinstance(raw_truth_value, int):
                continue
            current_asset = truth_assets_by_value.get(raw_truth_value)
            current_id = str((current_asset or {}).get("card_id") or "")
            is_monument_extra = card_id.startswith("monument-zusatz-wahrheit")
            current_is_monument_extra = current_id.startswith("monument-zusatz-wahrheit")
            if current_asset is None or (current_is_monument_extra and not is_monument_extra):
                truth_assets_by_value[raw_truth_value] = dict(asset_record) | {"card_id": card_id}

        return cls(
            cards_path=resolved_cards_path,
            records_by_id=records_by_id,
            card_assets_path=resolved_card_assets_path if resolved_card_assets_path.exists() else None,
            display_records_by_id=display_records_by_id,
            assets_by_id=assets_by_id,
            truth_assets_by_value=truth_assets_by_value,
            asset_language=normalized_asset_language,
        )

    def lookup(self, card_id: str) -> dict[str, Any] | None:
        record = self.records_by_id.get(card_id)
        return dict(record) if isinstance(record, dict) else None

    def display_lookup(self, card_id: str) -> dict[str, Any] | None:
        display_records = self.display_records_by_id if isinstance(self.display_records_by_id, dict) else {}
        record = display_records.get(card_id) or self.records_by_id.get(card_id)
        if not isinstance(record, dict):
            return None
        display_record = dict(record)
        asset = (self.assets_by_id or {}).get(card_id) or {}
        printed_name = asset.get("display_name_en") if self.asset_language == "en" else None
        if isinstance(printed_name, str) and printed_name.strip():
            # Printed names are bound to stable card IDs, independent of sheet row order.
            display_record["name"] = printed_name.strip()
        return display_record

    def set_asset_language(self, asset_language: str | None) -> None:
        """Switch card art and localized card copy without rebuilding game state."""
        normalized = _normalize_asset_language(asset_language)
        self.asset_language = normalized
        self.display_records_by_id = (
            _load_display_records_by_source_row(
                resolved_cards_path=self.cards_path,
                records_by_id=self.records_by_id,
            )
            if normalized == "en"
            else {}
        )

    def get_name(self, card_id: str, *, fallback: str | None = None) -> str:
        record = self.display_lookup(card_id)
        if isinstance(record, dict) and isinstance(record.get("name"), str) and record["name"].strip():
            return str(record["name"])
        return fallback or card_id

    def get_category(self, card_id: str, *, fallback: str | None = None) -> str:
        record = self.lookup(card_id)
        if isinstance(record, dict) and isinstance(record.get("category"), str) and record["category"].strip():
            return str(record["category"])
        return fallback or "-"

    def get_rules_text(self, card_id: str, *, fallback: str | None = None) -> str:
        if self.beginner_mode:
            beginner_rules = beginner_phenomenon_rules(card_id, language=self.asset_language)
            if beginner_rules:
                return beginner_rules
        record = self.display_lookup(card_id)
        if isinstance(record, dict):
            for field_name in TEXT_FIELD_CANDIDATES:
                raw_value = record.get(field_name)
                if isinstance(raw_value, str) and raw_value.strip():
                    return " ".join(raw_value.split())
        if isinstance(fallback, str) and fallback.strip():
            return " ".join(fallback.split())
        return "-"

    def get_asset(
        self,
        card_id: str,
        *,
        category: str | None = None,
        truth_value: int | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(self.assets_by_id, dict):
            return None
        record = self.assets_by_id.get(card_id)
        if isinstance(record, dict):
            asset = _localize_asset_record(record, asset_language=self.asset_language)
            card_record = self.records_by_id.get(card_id)
            resolved_category = category
            if resolved_category is None and isinstance(card_record, dict):
                raw_category = card_record.get("category")
                resolved_category = raw_category if isinstance(raw_category, str) else None
            landscape_categories = {"Phänomene", "Heilige Handgranate", "Monument", "Monumente"}
            landscape_id_markers = ("__Phänomene__", "__Heilige Handgranate__", "__Monument__")
            if resolved_category in landscape_categories or any(marker in card_id for marker in landscape_id_markers):
                asset.setdefault("orientation", "landscape")
                asset.setdefault("display_rotation", "clockwise")
            return asset
        if category == "Wahrheit" and isinstance(truth_value, int) and isinstance(self.truth_assets_by_value, dict):
            truth_asset = self.truth_assets_by_value.get(truth_value)
            return (
                _localize_asset_record(truth_asset, asset_language=self.asset_language)
                if isinstance(truth_asset, dict)
                else None
            )
        return None


def _normalize_asset_language(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"en", "eng", "english"}:
        return "en"
    return "de"


def _load_display_records_by_source_row(
    *,
    resolved_cards_path: Path,
    records_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    en_path = resolved_cards_path.with_name("cards_normalized_en.json")
    if not en_path.exists():
        return {}
    payload = json.loads(en_path.read_text(encoding="utf-8"))
    raw_records = payload.get("cards") if isinstance(payload, dict) else payload
    if not isinstance(raw_records, list):
        return {}
    en_by_source_row: dict[int, dict[str, Any]] = {}
    en_by_id: dict[str, dict[str, Any]] = {}
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        card_id = record.get("card_id")
        if isinstance(card_id, str) and card_id not in en_by_id:
            en_by_id[card_id] = record
        source_row = record.get("source_row")
        if isinstance(source_row, int) and source_row not in en_by_source_row:
            en_by_source_row[source_row] = record

    display_records: dict[str, dict[str, Any]] = {}
    for card_id, record in records_by_id.items():
        exact_record = en_by_id.get(card_id)
        if isinstance(exact_record, dict):
            display_records[card_id] = exact_record
            continue
        source_row = record.get("source_row")
        source_match = en_by_source_row.get(source_row) if isinstance(source_row, int) else None
        if isinstance(source_match, dict):
            display_records[card_id] = source_match
    return display_records


def _localize_asset_record(record: dict[str, Any], *, asset_language: str) -> dict[str, Any]:
    asset = dict(record)
    if _normalize_asset_language(asset_language) != "en":
        return asset

    front_en = asset.get("front_en")
    if isinstance(front_en, str) and front_en.strip():
        asset["front"] = front_en
        asset["language"] = "en"
        printed_name = asset.get("display_name_en")
        if isinstance(printed_name, str) and printed_name.strip():
            asset["alt"] = printed_name.strip()
        source_pdf_en = asset.get("source_pdf_en")
        source_page_en = asset.get("source_page_en")
        if isinstance(source_pdf_en, str) and source_pdf_en.strip():
            asset["source_pdf"] = source_pdf_en
        if isinstance(source_page_en, int):
            asset["source_page"] = source_page_en
    return asset
