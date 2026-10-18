"""Card exclusions for the beginner ruleset (D-110)."""

BEGINNER_EXCLUDED_RELIC_ID = "das-ohrlaeppchen-von-otto-dem-orgelbauer__Reliquie__1"
BEGINNER_EXCLUDED_MONUMENT_PREFIXES = (
    "goldenes-eichhoernchen-der-uebertriebenen-putzigkeit-",
    "die-goldene-gundel-der-wahnsinnigen-wuseligkeit-",
)


def beginner_card_allowed(card_id: str) -> bool:
    return (
        card_id != BEGINNER_EXCLUDED_RELIC_ID
        and not card_id.startswith(BEGINNER_EXCLUDED_MONUMENT_PREFIXES)
        and "__Gebote__" not in card_id
        and "__Heilige Handgranate__" not in card_id
    )


def require_beginner_phenomenon_payload(payload: dict) -> None:
    """Reject removed effect branches, including a Kugelblitz proxy payload."""
    if payload.get("mode") == "shatter_commandment":
        raise ValueError("Commandments are disabled in beginner mode; choose the other effect.")
    nested = payload.get("nested_effect_payload")
    if isinstance(nested, dict):
        require_beginner_phenomenon_payload(nested)
