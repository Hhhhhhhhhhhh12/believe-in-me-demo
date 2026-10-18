from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from engine import contest as bidding
from engine import core
from engine.catalog import get_card_record
from engine.logging import append_event
from engine.state import CardRef, GameState, PlayerState
from ui.cards_db import CardsDB


REPO = Path(__file__).resolve().parents[2]
IDS = {
    "song": "loblied__Segen__1",
    "song_again": "loblied__Segen__3",
    "ash": "die-noch-warme-asche-von-roswitha-der-rothaarigen__Reliquie__1",
    "enrico": "enrico-der-entdecker__Aufklärer__1",
    "army": "irmgard-die-inquisitorin__Heiliges Heer__1",
    "skull": "der-geborstene-schaedel-von-ansgard-dem-aelteren__Reliquie__1",
    "grenade": "heilige-handgranate-der-kalten-rache__Heilige Handgranate__1",
    "yak": "yak-mit-2-koepfen__Phänomene__1",
    "head": "walter__Körperteil Kopf__1",
    "chest": "der-zweifelnde-bestimmer__Körperteil Brust__1",
    "legs": "mit-hausstauballergie__Körperteil Beine__1",
    "squirrels": "eichhoernchenplage__Phänomene__1",
    "earthquake": "erdbeben__Phänomene__1",
    "tornado": "tornado__Phänomene__1",
}
TRUTH_IDS = {
    "p1": {2: "gott-1-wahrheit-2-01__Wahrheit__1", 3: "gott-1-wahrheit-3-01__Wahrheit__1", 4: "gott-1-wahrheit-4__Wahrheit__1", 5: "gott-1-wahrheit-5__Wahrheit__1", 6: "gott-1-wahrheit-6__Wahrheit__1", 7: "gott-1-wahrheit-7__Wahrheit__1"},
    "p2": {3: "gott-2-wahrheit-3-01__Wahrheit__1", 4: "gott-2-wahrheit-4__Wahrheit__1"},
    "p3": {2: "gott-3-wahrheit-2-01__Wahrheit__1", 5: "gott-3-wahrheit-5__Wahrheit__1"},
}
CARD_ART_IDS = IDS | {
    "frauke": "frauke-die-foltermagd__Heiliges Heer__1",
    "henk": "henk-der-hetzer__Aufklärer__1",
} | {f"truth_{pid}_{value}": card_id
     for pid, cards in TRUTH_IDS.items() for value, card_id in cards.items()}
PLAYER_NAMES = {"p1": "Du", "p2": "Frauke", "p3": "Henk"}
STAGES = {
    "intro": (0, "Believe in Me", "Ein Gott wird nicht an einem Tag gemacht."),
    "song": (1, "Ein kleines Wunder", "Spiele das Loblied und gewinne drei Gläubige."),
    "ash": (2, "Die Asche wirkt weiter", "Roswitha hilft deinem Heiligen Heer. Zwei Gläubige kostet das Anlegen."),
    "arrival": (3, "Ungebetener Besuch", "Dein Mitgott hat einen Aufklärer für dich."),
    "blocked": (3, "Enrico hat etwas dagegen", "Kannst du Ansgards Schädel jetzt anlegen?"),
    "army": (4, "Irmgard räumt auf", "Roswitha liegt bereits. Enrico kann ihre Wirkung nicht abschalten."),
    "skull": (4, "Platz für einen neuen Plan", "Ein Reliquienplatz: Der Schädel ersetzt Roswitha für zwei Gläubige."),
    "boost": (4, "Dasselbe Lied. Mehr Wirkung.", "Dieses Loblied passt ebenfalls nicht zu deiner Gesinnung. Der Schädel hilft trotzdem."),
    "combo_done": (4, "Fünf neue Gläubige", "Drei durch das Loblied, zwei durch Ansgards Schädel."),
    "grenade_intro": (5, "Eine spätere Runde", "Vorbereitete Spielsituation: zwei Aktionen, acht freie Gläubige und eine ungeladene Granate."),
    "grenade": (5, "Die kalte Rache", "Jede Ladung braucht eine Aktion und einen Gläubigen. Mehr Geduld, mehr Wirkung."),
    "grenade_done": (5, "Amen.", "Die Granate ist verbraucht. Ihre Wirkung steht in den Herden deiner Mitgötter."),
    "contest_intro": (6, "Kurz vor der Offenbarung", "Vorbereitete Spielsituation: Walter hat Kopf und Brust. Die Beine fehlen noch."),
    "contest": (6, "Ein Yak. Zwei Köpfe.", "Biete verdeckt um seine Macht. Oder passe endgültig. Am Ende zählt die Summe deiner Karten."),
    "claim": (6, "Die Macht gehört dir", "Mit dem Yak setzt ein Mitgott seinen nächsten Zug aus. Am Stechen nimmt er weiter teil."),
    "lost": (6, "Der Yak folgt einem Mitgott", "Ein neuer Versuch beginnt mit denselben Karten."),
    "finale": (6, "Halleluja!", "Walter, der zweifelnde Bestimmer mit Hausstauballergie"),
    "power_done": (6, "Eine Macht für später", "Du hast den Yak gespeichert und auf die Manifestation verzichtet."),
    "overview": (7, "Das ganze Spiel", "Ein Ausschnitt gespielt. Vieles noch zu entdecken."),
}


def card_ref(key: str) -> CardRef:
    card_id = IDS.get(key, key)
    record = get_card_record(card_id)
    if record is None:
        raise ValueError(f"Required demo card is missing: {card_id}")
    return CardRef(
        card_id=card_id, name=record["name"], category=record["category"],
        truth_value=record.get("truth_value"),
        metadata={field: record[field] for field in
                  ("rules_text", "alignment", "attribute", "cost_believers")
                  if record.get(field) is not None},
    )


class DemoSession:
    def __init__(self) -> None:
        self.state = self._base_state()
        self.stage = "intro"
        self.revision = 0
        self.actions = 2
        self.feedback = ""
        self.feedback_message: dict[str, Any] | None = None
        self.contest: bidding.ContestState | None = None
        self.score: bidding.ContestScore | None = None
        self.bid_action: dict[str, str] | None = None
        self.grenade_pending = False
        self.trace: list[dict[str, Any]] = []
        self.match = None

    @staticmethod
    def _base_state() -> GameState:
        return GameState(
            players={pid: PlayerState(pid, alignment="<Sanftmut>", meeples=6)
                     for pid in ("p1", "p2", "p3")},
            player_order=["p1", "p2", "p3"], seed=15,
        )

    def _play(self, key: str, *, player_id: str = "p1", **payload: Any) -> None:
        if self.actions <= 0:
            raise ValueError("Keine Aktion mehr verfügbar.")
        core.take_actions(
            self.state, player_id=player_id, actions_available=1,
            action_intents=[{"action": "play_hand_card", "card_id": IDS[key],
                             "effect_payload": payload}],
        )
        self.actions -= 1

    def _curated_turn(self, label: str, *, player_id: str = "p1") -> None:
        self.state.turn_number += 1
        self.actions = 2
        append_event(self.state.event_log, "demo_prepared_turn", player_id=player_id,
                     label=label, actions_available=2)

    def _prepare_grenade(self) -> None:
        self.state = self._base_state()
        self.state.round_number = 4
        for player in self.state.players.values():
            player.meeples = 8
        self.state.players["p1"].hand_grenade_state.grenade = core.build_hand_grenade_card(IDS["grenade"])
        self.state.players["p2"].hand_cards = [card_ref("song")]
        self.state.players["p3"].hand_cards = [card_ref("song_again")]
        self.actions = 2
        self.grenade_pending = False
        append_event(self.state.event_log, "demo_scene_prepared", scene="grenade", round=4)

    def _prepare_contest(self) -> None:
        self.state = self._base_state()
        self.state.round_number = 8
        own = self.state.players["p1"]
        own.tableau = [card_ref("head"), card_ref("chest")]
        own.body_parts = {"Kopf", "Brust"}
        own.manifested_parts_counts["<Chaos>"] = 2
        own.alignment = "<Chaos>"
        self.state.body_part_draw_pile = [card_ref("legs")]
        yak = card_ref("yak")
        self.state.phenomenon_draw_pile = [yak]
        bidding.register_known_phenomenon_metadata(
            self.state, card_id=yak.card_id, card_name=yak.name,
            card_category=yak.category, card_alignment="<Chaos>",
        )
        for pid, cards in TRUTH_IDS.items():
            player = self.state.players[pid]
            if pid != "p1":
                chest_id = {"p2": "die-beinahe-allwissende__Körperteil Brust__1",
                            "p3": "der-spaerlich-erleuchtete__Körperteil Brust__1"}[pid]
                player.tableau = [card_ref(chest_id)]
                player.body_parts = {"Brust"}
                player.manifested_parts_counts["<Sanftmut>"] = 1
            player.hand_cards = [card_ref(card_id) for value, card_id in cards.items() if pid != "p1" or value in {2, 4, 6}]
        self.contest = bidding.ContestState(
            player_order=["p1", "p2", "p3"], current_player_idx=0,
            start_player_idx=0, current_round=8, contested_card_id=IDS["yak"],
        )
        self.score = None
        self.bid_action = None
        append_event(self.state.event_log, "demo_scene_prepared", scene="contest", round=8)

    def perform(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        # A failed engine command cannot leave a partially changed presentation.
        checkpoint = copy.deepcopy(self.__dict__)
        before = self.stage
        event_start = len(self.state.event_log)
        try:
            self._perform(action, payload or {})
        except (ValueError, KeyError, TypeError):
            self.__dict__.update(checkpoint)
            raise
        self.revision += 1
        events = self.state.event_log if before in {"grenade_intro", "contest_intro", "lost"} else self.state.event_log[event_start:]
        self.trace.append({"step": self.revision, "scene": before, "action": action,
                           "feedback": self.feedback, "feedback_message": self.feedback_message,
                           "events": copy.deepcopy(events)})
        self.trace = self.trace[-100:]
        return self.view()

    def _message(self, key: str, text: str, **values: int) -> None:
        self.feedback = text
        self.feedback_message = {"key": key, "values": values}

    def _perform(self, action: str, payload: dict[str, Any]) -> None:
        self.feedback = ""
        self.feedback_message = None
        self.bid_action = None
        player = self.state.players["p1"]
        if action == "restart":
            old_revision = self.revision
            self.__init__()
            self.revision = old_revision
            return
        if self.stage == "intro" and action == "start_mini":
            from .mini_match import MiniMatch
            self.match = MiniMatch(self.state)
            self.stage = "mini"
            return
        if self.stage == "mini":
            if action == "overview" and self.match.phase == "finished":
                self.stage = "overview"
            else:
                self.match.perform(action, payload)
            return
        if action == "overview" and self.stage in {"finale", "power_done"}:
            self.stage = "overview"
            return
        if self.stage == "intro" and action == "start":
            player.hand_cards = [card_ref(key) for key in ("song", "ash", "army", "skull", "song_again")]
            self.stage = "song"
        elif self.stage == "song" and action == "play_song":
            before = player.meeples
            self._play("song")
            self._message("song", f"{player.meeples - before} neue Gläubige folgen dir.", count=player.meeples - before)
            self.stage = "ash"
        elif self.stage == "ash" and action == "play_ash":
            self._play("ash")
            self._message("ash", "Roswitha liegt. Dein Heiliges Heer kostet keine Opfer mehr.")
            self.stage = "arrival"
        elif self.stage == "arrival" and action == "opponent":
            self._curated_turn("Enrico kommt", player_id="p2")
            self.state.players["p2"].hand_cards = [card_ref("enrico")]
            self._play("enrico", player_id="p2", target_player_id="p1")
            self._curated_turn("Dein nächster vorbereiteter Zug")
            self.stage = "blocked"
        elif self.stage == "blocked" and action == "try_skull":
            legal_ids = {card.card_id for card in core.get_legal_action_hand_cards(self.state, player_id="p1")}
            if IDS["skull"] in legal_ids:
                raise ValueError("Enrico blockiert die Reliquie nicht wie erwartet.")
            append_event(self.state.event_log, "demo_block_observed", card_id=IDS["skull"], blocker_id=IDS["enrico"])
            self._message("blocked", "Enrico verhindert neue Reliquien. Roswitha bleibt wirksam. Der Versuch kostet keine Aktion.")
            self.stage = "army"
        elif self.stage == "army" and action == "play_army":
            before = player.meeples
            self._play("army", mode="any_own", target_card_id=IDS["enrico"])
            self._message("army", f"Enrico ist weg. {before - player.meeples} Opfer statt vier: Roswitha hilft.", count=before - player.meeples)
            self.stage = "skull"
        elif self.stage == "skull" and action == "play_skull":
            self._play("skull", replaced_card_id=IDS["ash"])
            self._message("skull", "Roswitha wird abgelegt. Ansgards Schädel nimmt ihren Platz ein.")
            self.stage = "boost"
            self._curated_turn("Vorbereiteter Folgezug: Loblied")
        elif self.stage == "boost" and action == "play_boost":
            before = player.meeples
            self._play("song_again")
            self._message("boost", f"{player.meeples - before} neue Gläubige: drei durch den Segen, zwei durch den Schädel.", count=player.meeples - before)
            self.stage = "combo_done"
        elif self.stage == "combo_done" and action == "next":
            self.stage = "grenade_intro"
        elif self.stage == "grenade_intro" and action == "next":
            self._prepare_grenade()
            self.stage = "grenade"
        elif self.stage == "grenade":
            self._grenade_action(action, payload)
        elif self.stage == "grenade_done" and action == "next":
            self.stage = "contest_intro"
        elif self.stage in {"contest_intro", "lost"} and action in {"next", "retry"}:
            self._prepare_contest()
            self.stage = "contest"
        elif self.stage == "contest" and action in {"bid", "pass"}:
            self._bid(action, payload)
        elif self.stage == "contest" and action == "advance_opponent":
            self._opponent_bid()
        elif self.stage == "claim" and action in {"manifest", "keep_power"}:
            believers_before = player.meeples
            core.claim_phenomenon(
                self.state, player_id="p1", card_id=IDS["yak"], card_name="Yak mit 2 Köpfen",
                card_alignment="<Chaos>", manifest_requested=action == "manifest",
                manifest_body_part_category="Körperteil Beine" if action == "manifest" else None,
                allow_baseline_manifestation=False,
            )
            self.stage = "finale" if action == "manifest" else "power_done"
            gained = player.meeples - believers_before
            if action == "manifest":
                self._message("manifest", f"{gained - 3} Gläubige für das gewonnene Phänomen, drei für die Offenbarung.", count=gained - 3)
            else:
                self._message("keep_power", f"Der Yak bleibt als Macht gespeichert. {gained} Gläubige folgen dir.", count=gained)
        else:
            raise ValueError("Diese Aktion ist in der aktuellen Szene nicht verfügbar.")

    def _grenade_payload(self, target: Any) -> dict[str, Any]:
        if target not in {"p2", "p3", "split"}:
            raise ValueError("Wähle einen Mitgott oder beide.")
        tier = self.state.players["p1"].hand_grenade_state.meeples_committed
        amount = {1: 3, 2: 5, 3: 8}[tier]
        if target == "split":
            return {"target_player_ids": ["p2", "p3"],
                    "target_sacrifice_amounts": {"p2": (amount + 1) // 2, "p3": amount // 2}}
        return {"target_player_ids": [target]}

    def _grenade_action(self, action: str, payload: dict[str, Any]) -> None:
        grenade = self.state.players["p1"].hand_grenade_state
        if action == "charge" and not self.grenade_pending and self.actions > 0:
            effect = self._grenade_payload(payload.get("target", "p2")) if grenade.meeples_committed == 2 else {}
            # Third-tier targeting uses the forthcoming tier before the engine increments it.
            if grenade.meeples_committed == 2 and payload.get("target") == "split":
                effect = {"target_player_ids": ["p2", "p3"], "target_sacrifice_amounts": {"p2": 4, "p3": 4}}
            core.take_actions(self.state, player_id="p1", actions_available=1,
                              action_intents=[{"action": "grenade", "level": grenade.meeples_committed + 1,
                                               "detonate": False, "effect_payload": effect}])
            self.actions -= 1
            self.grenade_pending = not grenade.used
            self._message("charge", "Ein Gläubiger lädt die Granate.")
            if grenade.used:
                self.stage = "grenade_done"
                self._message("third_charge", "Dritte Ladung: acht Opfer. Die Granate zündet verpflichtend.")
        elif action == "ignite" and self.grenade_pending:
            core._detonate_grenade(self.state, player_id="p1", tier=grenade.meeples_committed,
                                  automatic=False, effect_payload=self._grenade_payload(payload.get("target")),
                                  decision_source="explicit_intent")
            self.grenade_pending = False
            self.stage = "grenade_done"
            amount = {1: 3, 2: 5}[grenade.detonated_tier]
            self._message("ignite", f"Stufe {grenade.detonated_tier}: {amount} Opfer.", tier=grenade.detonated_tier, count=amount)
        elif action == "wait" and self.grenade_pending:
            self.grenade_pending = False
            self._message("wait", "Du zündest noch nicht. Eine weitere Ladung braucht eine weitere Aktion.")
        elif action == "next_turn" and self.actions == 0 and not self.grenade_pending:
            for pid, key in (("p2", "song"), ("p3", "song_again")):
                core.take_actions(self.state, player_id=pid, actions_available=1,
                                  action_intents=[{"action": "play_hand_card", "card_id": IDS[key]}])
            self.state.round_number += 1
            self._curated_turn("Mitgötter haben je einen Segen gespielt")
            self._message("next_turn", "Deine Mitgötter haben ihre Herden vergrößert. Du hast wieder zwei Aktionen.")
        else:
            raise ValueError("Diese Granatenaktion ist gerade nicht möglich.")

    def _bid(self, action: str, payload: dict[str, Any]) -> None:
        contest = self.contest
        if contest is None or contest.ended or contest.player_order[contest.current_player_idx] != "p1":
            raise ValueError("Du bist beim Bieten gerade nicht dran.")
        choice = None
        if action == "bid":
            value = payload.get("value")
            if type(value) is not int or value not in {2, 4, 6}:
                raise ValueError("Wähle eine verfügbare Wahrheitskarte.")
            selected = next((card for card in self.state.players["p1"].hand_cards
                             if card.category == "Wahrheit" and card.truth_value == value), None)
            if selected is None:
                raise ValueError("Diese Wahrheitskarte wurde bereits geboten.")
            choice = bidding.ContestBidChoice(truth_card_ids=[selected.card_id])
        self._contest_step("p1", action, choice)
        self._finish_contest()

    def _opponent_bid(self) -> None:
        contest = self.contest
        if contest is None or contest.ended:
            raise ValueError("Kein aktives Stechen.")
        pid = contest.player_order[contest.current_player_idx]
        if pid == "p1":
            raise ValueError("Du bist beim Bieten am Zug.")
        options = bidding.get_legal_bid_options(self.state, pid, contest)
        count = sum(bid.player_id == pid for bid in contest.played_bids)
        plan = list(TRUTH_IDS[pid].values())
        planned = plan[count] if count < len(plan) else None
        choice = next((option for option in options if option.truth_card_ids == [planned]), None)
        self._contest_step(pid, "bid" if choice else "pass", choice)
        self._finish_contest()

    def _finish_contest(self) -> None:
        contest = self.contest
        if contest and contest.ended and self.score is None:
            self.score = bidding.score_committed_bids(self.state, contest.played_bids)
            bidding.append_contest_reveal_log(self.state, contest_kind="demo", current_round=8,
                                             contested_card_id=IDS["yak"], score=self.score,
                                             nun_sacrifice_player_ids=[])
            bidding.finalize_committed_bids(self.state, contest.played_bids)
            self.stage = "claim" if self.score.winner_id == "p1" else "lost"
            if self.score.winner_id and self.score.winner_id != "p1":
                core.claim_phenomenon(self.state, player_id=self.score.winner_id,
                                     card_id=IDS["yak"], card_alignment="<Chaos>",
                                     allow_baseline_manifestation=False)
            self._message("reveal", "Alle Karten sind aufgedeckt. Die Engine zählt die Gebote.")

    def _contest_step(self, pid: str, action: str, choice: bidding.ContestBidChoice | None) -> None:
        assert self.contest is not None
        moves = core.get_legal_moves(self.state, player_id=pid, phase="contest", contest_state=self.contest,
                                    eligible_player_ids=self.contest.player_order)
        if not any(move["action"] == action and
                   (action == "pass" or move["bid_choice"]["truth_card_ids"] == choice.truth_card_ids)
                   for move in moves):
            raise ValueError("Dieses Gebot ist nicht legal.")
        bidding.step_contest_with_intents(
            self.state, self.contest,
            turn_intents={pid: [bidding.ContestTurnIntent(action=action, bid_choice=choice)]},
            turn_intent_positions={pid: 0}, nun_sacrifice_decisions={},
            require_explicit_turn_intents=True,
        )
        self.bid_action = {"player": pid, "kind": action}

    def view(self) -> dict[str, Any]:
        if self.stage == "mini":
            match = self.match.view()
            return {"stage": "mini", "revision": self.revision, "chapter": 0,
                    "round": self.state.round_number, "actions": self.match.actions,
                    "players": [player | {"name": PLAYER_NAMES[player["id"]]} for player in match["players"]],
                    "tableau": match["players"][0]["tableau"], "body_count": len(self.state.players["p1"].body_parts),
                    "feedback": "", "feedback_message": None, "match": match,
                    "endgame": self.state.endgame_active, "revealed": self.state.players["p1"].god_revealed,
                    "grenade": {"level": self.state.players["p1"].hand_grenade_state.meeples_committed,
                                "used": self.state.players["p1"].hand_grenade_state.used},
                    "trace": self._safe_trace()}
        chapter, title, prompt = STAGES[self.stage]
        own = self.state.players["p1"]
        grenade = own.hand_grenade_state
        counts = {}
        if self.contest:
            counts = {pid: sum(bid.player_id == pid for bid in self.contest.played_bids)
                      for pid in self.state.player_order}
        current = (self.contest.player_order[self.contest.current_player_idx]
                   if self.stage == "contest" and self.contest and not self.contest.ended else None)
        legal = core.get_legal_moves(self.state, player_id="p1", phase="contest", contest_state=self.contest,
                                    eligible_player_ids=self.contest.player_order) if current == "p1" else []
        own_bids = [bid for bid in self.contest.played_bids if bid.player_id == "p1"] if self.contest else []
        return {
            "stage": self.stage, "revision": self.revision, "chapter": chapter, "mini_available": True, "mini_played": self.match is not None,
            "title": title, "prompt": prompt, "feedback": self.feedback,
            "feedback_message": copy.deepcopy(self.feedback_message),
            "actions": self.actions, "round": self.state.round_number,
            "players": [{"id": pid, "name": PLAYER_NAMES[pid],
                         "believers": p.meeples, "bid_count": counts.get(pid, 0),
                         "passed": bool(self.contest and pid in self.contest.passed_players)}
                        for pid, p in self.state.players.items()],
            "tableau": [key for key, card_id in IDS.items() if any(c.card_id == card_id for c in own.tableau)],
            "truth": [card.truth_value for card in own.hand_cards if card.category == "Wahrheit"],
            "truth_cards": [{"value": card.truth_value, "art": f"truth_p1_{card.truth_value}"}
                            for card in own.hand_cards if card.category == "Wahrheit"],
            "contest_turn": current,
            "can_bid": any(move["action"] == "bid" for move in legal),
            "can_pass": any(move["action"] == "pass" for move in legal),
            "own_bid_total": sum(bid.bid_total for bid in own_bids),
            "bid_action": copy.deepcopy(self.bid_action),
            "grenade": {"level": grenade.meeples_committed, "used": grenade.used,
                        "pending": self.grenade_pending},
            "score": self.score.bid_totals if self.score else None,
            "bids": [{"player": bid.player_id, "values": bid.truth_values,
                      "art": [f"truth_{bid.player_id}_{value}" for value in bid.truth_values]}
                     for bid in self.contest.played_bids] if self.score and self.contest else [],
            "winner": self.score.winner_id if self.score else None,
            "tie_breaker": self.score.tie_breaker if self.score else None,
            "revealed": own.god_revealed, "endgame": self.state.endgame_active,
            "body_count": len(own.body_parts),
            "trace": self._safe_trace(),
        }

    def _safe_trace(self) -> list[dict[str, Any]]:
        return [{"step": row["step"], "scene": row["scene"], "action": row["action"],
                       "feedback": row["feedback"],
                       "feedback_message": copy.deepcopy(row["feedback_message"]),
                       "events": [{key: value for key, value in event.items()
                                   if key in {"type", "player_id", "category", "additional_cost",
                                              "intrinsic_cost_paid", "committed", "tier",
                                              "free_meeples_after", "actions_available"}}
                                  for event in row["events"]
                                  if not (event.get("player_id") != "p1"
                                          and (event.get("type") == "card_drawn"
                                               or event.get("type", "").startswith("truth_")))]}
                for row in self.trace]


def artwork_allowlist() -> dict[str, Path]:
    db = CardsDB.load(root_dir=REPO)
    paths = {key: REPO / str((db.assets_by_id or {})[card_id]["front"])
             for key, card_id in CARD_ART_IDS.items()}
    paths.update({f"{key}_en": REPO / str((db.assets_by_id or {})[card_id]["front_en"])
                  for key, card_id in CARD_ART_IDS.items()})
    paths.update({
        "truth_back": REPO / str((db.assets_by_id or {})[TRUTH_IDS["p1"][2]]["back"]),
        "logo": REPO / "assets/ui/bim-logo-transparent-v2.png",
        "monk": REPO / "assets/ui/meeple-roles-v4/gesangsmoench.png",
        "pass": REPO / "assets/ui/holy-meeple-surrender.png",
        "missionary": REPO / "assets/ui/meeple-roles-v6/missionar.png",
        "nun": REPO / "assets/ui/meeple-roles-v3/kampfnonne.png",
        "believer": REPO / "assets/ui/believer-token-cutout.png",
        "alignment_chaos": REPO / "assets/ui/alignment-chaos.png",
        "alignment_wrath": REPO / "assets/ui/alignment-wrath.png",
        "alignment_gentle": REPO / "assets/ui/alignment-gentle.png",
        "alignment_unfathomable": REPO / "assets/ui/alignment-unfathomable.png",
        "monument": REPO / "assets/ui/monument-squirrel-03-original-cutout-clean.png",
        "temple": REPO / "assets/ui/temple-monk-original-cloudless.png",
        "prophet": REPO / "assets/ui/BIM_Token_Wood_Prophet.png",
        "playerboard": REPO / "assets/ui/ekona-private/playerboard-en.png",
        "middleboard": REPO / "assets/ui/ekona-private/middleboard-en.png",
        "viewer_lobby": REPO / "assets/ui/ekona-private/viewer-lobby.jpg",
        "viewer_cards": REPO / "assets/ui/ekona-private/viewer-cards.jpg",
        "viewer_truth": REPO / "assets/ui/ekona-private/viewer-truth.jpg",
        "code_workshop": REPO / "assets/ui/ekona-private/code-workshop-v1.png",
        "test_lab": REPO / "assets/ui/ekona-private/test-lab-v1.png",
    })
    missing = [key for key, path in paths.items() if not path.is_file()]
    if missing:
        raise ValueError(f"Missing allowlisted demo artwork: {', '.join(missing)}")
    return paths
