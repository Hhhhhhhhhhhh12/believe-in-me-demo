"""Viewer explanations for the beginner ruleset; original card art stays intact."""

BEGINNER_MODE_HINT_DE = (
    "Anfänger-Modus: Ohne Falschen Propheten, Handgranaten, Gebote und Ottos Ohrläppchen. "
    "Bei jeder Spielerzahl sind alle vier Monumentlinien Hering, Löffel, Oma Hedwig und Zwiebel im Spiel. "
    "Eichhörnchen und Gundel entfallen, weil ihr Abschlussbonus den Propheten benötigt. "
    "Alle anderen Karten bleiben erhalten; bei Phänomenen entfällt nur die Gebotswirkung."
)
BEGINNER_MODE_HINT_EN = (
    "Beginner mode: No False Prophet, Holy Hand Grenades, commandments or Otto's Earlobe. "
    "All four monument lines (Herring, Spoon, Grandma Hedwig and Onion) are in play at every player count. "
    "Squirrel and Gundel are excluded because their completion bonuses require the Prophet. "
    "All other cards remain; only the commandment option on phenomena is unavailable."
)

_RELIC_EFFECT = (
    "Zerstöre 1 Reliquie eines Mitgottes.",
    "Destroy 1 relic belonging to a fellow god.",
)
_PHENOMENON_EFFECTS = {
    "fata-morgana__Phänomene__1": _RELIC_EFFECT,
    "erdbeben__Phänomene__1": _RELIC_EFFECT,
    "vulkanausbruch__Phänomene__1": _RELIC_EFFECT,
    "froschregen__Phänomene__1": (
        "Durchsuche den Monumentstapel und lege 1 nach den normalen Bauregeln passende Karte bei dir an.",
        "Search the monument deck and build 1 card that is legal under the normal building rules.",
    ),
    "kornkreise__Phänomene__1": (
        "Tausche alle eigenen Himmelreich-Handkarten ungesehen mit denen eines Mitgottes.",
        "Blindly swap all your Heavenly Realm hand cards with those of a fellow god.",
    ),
    "sonnenfinsternis__Phänomene__1": (
        "Ein Mitgott gibt dir 3 seiner Himmelreichskarten; er wählt die Karten.",
        "A fellow god gives you 3 of their Heavenly Realm cards; they choose the cards.",
    ),
}


def beginner_phenomenon_effect(card_id: str, *, language: str = "de") -> str:
    effect = _PHENOMENON_EFFECTS.get(card_id)
    if effect is None:
        return ""
    return effect[1] if language == "en" else effect[0]


def beginner_phenomenon_rules(card_id: str, *, language: str = "de") -> str:
    effect = beginner_phenomenon_effect(card_id, language=language)
    if not effect:
        return ""
    if language == "en":
        return "Beginner mode: There are no commandments. Only this effect applies: " + effect
    return "Anfänger-Modus: Es gibt keine Gebote. Es gilt nur diese Wirkung: " + effect
