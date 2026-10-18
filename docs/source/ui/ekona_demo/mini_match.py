"""A curated mid-game setup, followed by ordinary engine turns and contests."""
from __future__ import annotations

from typing import Any

from engine import contest as bidding, core, round as rounds
from engine.logging import append_event


class MiniMatch:
    def __init__(self, state: Any) -> None:
        from .model import IDS, TRUTH_IDS, card_ref

        self.ids = IDS
        self.state = state
        self.phase = "turn"
        self.turn_frame = None
        self.round_frame = None
        self.turn_index = 0
        self.actions = 0
        self.manual_truth_draws = 0
        self.contest = None
        self.score = None
        self.prize = None
        self.pending_pass = None
        self.last_move: dict[str, Any] | None = None
        self.revealed_truth_art: set[str] = set()
        self.history: list[dict[str, Any]] = []
        own = state.players["p1"]
        own.tableau = [card_ref("head"), card_ref("chest")]
        own.body_parts = {"Kopf", "Brust"}
        own.manifested_parts_counts["<Chaos>"] = 2
        own.alignment = "<Chaos>"
        own.hand_cards = [card_ref(key) for key in ("song", "ash", "army", "skull")]
        own.hand_cards += [card_ref(TRUTH_IDS["p1"][value]) for value in (4, 6)]
        own.hand_grenade_state.grenade = core.build_hand_grenade_card(IDS["grenade"])
        for pid, chest in (("p2", "die-beinahe-allwissende__Körperteil Brust__1"),
                           ("p3", "der-spaerlich-erleuchtete__Körperteil Brust__1")):
            player = state.players[pid]
            player.tableau = [card_ref(chest)]
            player.body_parts = {"Brust"}
            player.manifested_parts_counts["<Sanftmut>"] = 1
            player.hand_cards = [card_ref(card_id) for card_id in TRUTH_IDS[pid].values()]
        state.players["p2"].hand_cards.append(card_ref("enrico"))
        state.players["p3"].hand_cards.append(card_ref("loblied__Segen__2"))
        state.heavenly_draw_pile = [card_ref("song_again")]
        state.body_part_draw_pile = [card_ref("legs")]
        state.phenomenon_draw_pile = [card_ref(key) for key in ("yak", "squirrels", "earthquake", "tornado")]
        state.require_explicit_action_intents = True
        for pid, player in state.players.items():
            core.apply_alignment_change(state, player_id=pid,
                                        new_alignment=core.compute_alignment(player.manifested_parts_counts))
        append_event(state.event_log, "demo_scene_prepared", scene="mini_match", round=1)
        self._begin_round()

    @property
    def actor(self) -> str | None:
        if self.phase == "contest" and self.contest and not self.contest.ended:
            return self.contest.player_order[self.contest.current_player_idx]
        if self.phase in {"turn", "draw"} and self.round_frame:
            return self.round_frame.turn_order[self.turn_index]
        return None

    def _begin_round(self) -> None:
        self.round_frame = rounds.begin_round(self.state)
        if self.round_frame is None:
            self.phase = "finished"
            return
        self.turn_index = 0
        self.score = None
        self.contest = None
        self.prize = None
        self._begin_turn()

    def _begin_turn(self) -> None:
        self.phase = "turn"
        self.manual_truth_draws = 0
        pid = self.round_frame.turn_order[self.turn_index]
        self.turn_frame = core.begin_turn(self.state, player_id=pid)
        if self.turn_frame is None:
            self._next_turn()
        else:
            self.actions = self.turn_frame.actions_available

    def _next_turn(self) -> None:
        self.turn_index += 1
        if self.turn_index < len(self.round_frame.turn_order):
            self._begin_turn()
        else:
            self._begin_contest()

    def _finish_turn(self) -> None:
        core.finalize_turn(self.state, frame=self.turn_frame)
        self._next_turn()

    def _begin_draw(self) -> None:
        self.phase = "draw"
        player = self.state.players[self.actor]
        append_event(self.state.event_log, "draw_step_started", player_id=self.actor,
                     hand_size=len(player.hand_cards), hand_limit=self.hand_limit,
                     cards_needed=max(0, self.hand_limit - len(player.hand_cards)))
        if len(player.hand_cards) >= self.hand_limit:
            self._finish_turn()

    @property
    def hand_limit(self) -> int:
        player = self.state.players[self.actor or "p1"]
        return player.commandment_state.effective_hand_limit + core._get_local_hand_limit_modifier(self.state, player_id=player.player_id)

    def _begin_contest(self) -> None:
        self.phase = "contest"
        self.actions = 0
        # Use the same draw/empty-pile terminal path as the normal round adapter.
        card_id = bidding._resolve_contested_phenomenon_card_id(self.state, contested_card_id=None)
        if card_id is None:
            core.finalize_terminal_game_if_needed(self.state, reason="phenomenon_draw_pile_empty")
            self.phase = "finished"
            return
        from .model import card_ref
        self.prize = card_ref(card_id)
        order = self.round_frame.turn_order
        eligible, ineligible, blocked = bidding._compute_contest_eligibility(self.state, order)
        for pid in blocked:
            self.state.players[pid].skip_next_contest = False
        self.contest = bidding.ContestState(player_order=list(eligible), current_player_idx=0,
                                            start_player_idx=self.state.start_player_idx,
                                            current_round=self.state.round_number, contested_card_id=card_id)
        append_event(self.state.event_log, "contest_eligibility_computed", current_round=self.state.round_number,
                     eligible_player_ids=list(eligible), ineligible_player_ids=list(ineligible),
                     effect_blocked_player_ids=list(blocked), contested_card_id=card_id)
        if not eligible:
            self.score = bidding.ContestScore(bid_totals={}, winner_id=None,
                                              tied_player_ids=[], tie_breaker="no_eligible_players")
            self.contest.ended = True
            self.state.phenomenon_discard.append(card_id)
            append_event(self.state.event_log, "contested_phenomenon_discarded_no_eligible",
                         current_round=self.state.round_number, card_id=card_id,
                         ineligible_player_ids=list(ineligible),
                         phenomenon_discard_size=len(self.state.phenomenon_discard))
            self._log_contest_end("no_eligible_players")
            self.phase = "round_end"
        else:
            append_event(self.state.event_log, "contest_started", current_round=self.state.round_number,
                         start_player_idx=self.state.start_player_idx, start_player_id=order[0],
                         opening_player_id=eligible[0], turn_order=list(eligible), contested_card_id=card_id)

    def options(self, pid: str = "p1") -> list[dict[str, Any]]:
        if self.phase != "turn" or self.actor != pid:
            return []
        options: list[dict[str, Any]] = []
        for move in core.get_legal_moves(self.state, player_id=pid, actions_available=self.actions,
                                        include_monument_choices=False):
            kind = move["action"]
            intent = {key: move[key] for key in ("action", "card_id", "role_type", "level", "detonate", "target_player_id", "phenomenon_card_id") if key in move}
            if kind == "play_hand_card":
                card = next(card for card in self.state.players[pid].hand_cards if card.card_id == move["card_id"])
                effect = dict(move.get("default_payload") or move.get("effect_payload") or {})
                if card.category == "Aufklärer":
                    for target in self.state.player_order:
                        if target != pid:
                            options.append({"intent": intent | {"effect_payload": effect | {"target_player_id": target}}, "art": self.art(card), "target": target, "kind": "play"})
                    continue
                if card.category == "Heiliges Heer":
                    for target_card in self.state.players[pid].tableau:
                        if target_card.category == "Aufklärer":
                            options.append({"intent": intent | {"effect_payload": effect | {"mode": "any_own", "target_card_id": target_card.card_id}}, "art": self.art(card), "target_art": self.art(target_card), "kind": "play"})
                    continue
                if card.category == "Reliquie":
                    relics = [c for c in self.state.players[pid].tableau if c.category == "Reliquie"]
                    if relics and len(relics) >= core._get_slot_limit(self.state.players[pid], slot_kind="relics"):
                        effect["replaced_card_id"] = relics[0].card_id
                intent["effect_payload"] = effect
                options.append({"intent": intent, "art": self.art(card), "kind": "play"})
            elif kind == "role" and move["role_type"] in {"Mönche", "Missionare", "Nonnen"}:
                options.append({"intent": intent, "role": move["role_type"], "kind": "role"})
            elif kind == "grenade":
                for target in self.state.player_order:
                    if target != pid:
                        options.append({"intent": intent | {"effect_payload": {"target_player_ids": [target]}},
                                        "art": "grenade", "kind": "grenade", "target": target,
                                        "level": move["level"], "detonate": move["detonate"] or move["level"] == 3})
            elif kind == "unleash_stored_power" and move["phenomenon_card_id"] == self.ids["yak"]:
                for target in self.state.player_order:
                    if target != pid:
                        options.append({"intent": intent | {"effect_payload": {"target_player_id": target}}, "art": "yak", "kind": "power", "target": target})
            elif kind == "prophet_send":
                options.append({"intent": intent, "kind": "prophet", "target": move["target_player_id"]})
            elif kind == "skip":
                options.append({"intent": intent, "kind": "skip"})
        return options

    def _execute(self, option: dict[str, Any], pid: str) -> None:
        start = len(self.state.event_log)
        core.take_actions(self.state, player_id=pid, actions_available=self.actions,
                          action_intents=[option["intent"]], require_explicit_action_intents=True)
        result = next(event for event in reversed(self.state.event_log[start:]) if event["type"] == "take_actions_resolved")
        self.actions = result["remaining_actions"]
        self.last_move = {"player": pid, **{key: value for key, value in option.items() if key != "intent"}}
        self.history.append(dict(self.last_move))
        self.history = self.history[-8:]

    def perform(self, action: str, payload: dict[str, Any]) -> None:
        self.last_move = None
        if action == "mini_move" and self.actor == "p1" and self.phase == "turn":
            index = payload.get("move_index")
            options = self.options()
            if type(index) is not int or not 0 <= index < len(options):
                raise ValueError("Dieser Zug ist nicht verfügbar.")
            self._execute(options[index], "p1")
        elif action == "mini_end_turn" and self.actor == "p1" and self.phase == "turn":
            self._begin_draw()
        elif action == "mini_draw" and self.actor == "p1" and self.phase == "draw":
            value = payload.get("value")
            if type(value) is not int or value not in self.truth_choices("p1") or self.manual_truth_draws >= 2:
                raise ValueError("Diese Wahrheitskarte ist nicht verfügbar.")
            cards = core._add_truth_cards_to_hand(self.state, player_id="p1", truth_values=[value], source="manual-draw")
            append_event(self.state.event_log, "draw_choice_resolved", player_id="p1", mode="truth", truth_values=[value],
                         prepared_truth_card_ids=[card.card_id for card in cards], hand_size=len(self.state.players["p1"].hand_cards))
            self.manual_truth_draws += 1
            if self.manual_truth_draws >= 2 or len(self.state.players["p1"].hand_cards) >= self.hand_limit:
                self._finish_turn()
        elif action == "mini_draw_rest" and self.actor == "p1" and self.phase == "draw":
            self._finish_turn()
        elif action == "mini_bid" and self.phase == "contest" and self.actor == "p1":
            card_id = payload.get("card_id")
            option = next((opt for opt in bidding.get_legal_bid_options(self.state, "p1", self.contest)
                           if opt.truth_card_ids + opt.heavenly_card_ids == [card_id]), None)
            if option is None:
                raise ValueError("Dieses Gebot ist nicht legal.")
            self._bid_step("p1", "bid", option)
        elif action == "mini_pass" and self.phase == "contest" and self.actor == "p1":
            moves = core.get_legal_moves(self.state, player_id="p1", phase="contest",
                                        contest_state=self.contest, eligible_player_ids=self.contest.player_order)
            if not any(move["action"] == "pass" for move in moves):
                raise ValueError("Du musst das Stechen mit einer Karte eröffnen.")
            self._bid_step("p1", "pass", None)
        elif action == "mini_nun" and self.phase == "nun":
            sacrifice = payload.get("sacrifice")
            if type(sacrifice) is not bool:
                raise ValueError("Wähle, ob du eine Nonne opferst.")
            pid = self.pending_pass
            self.pending_pass = None
            self.phase = "contest"
            self._bid_step(pid, "pass", None, sacrifice=sacrifice)
        elif action == "mini_claim" and self.phase == "claim" and self.score.winner_id == "p1":
            manifest = payload.get("manifest")
            if type(manifest) is not bool or manifest and "Körperteil Beine" not in self.manifest_choices():
                raise ValueError("Diese Manifestation ist nicht verfügbar.")
            self._claim(manifest)
        elif action == "mini_next_round" and self.phase == "round_end":
            core.maybe_start_endgame_countdown(self.state, trigger_source="round_end_post_contest")
            rounds.finalize_round(self.state, frame=self.round_frame)
            self._begin_round()
        elif action == "mini_advance" and self.actor in {"p2", "p3"}:
            self._opponent()
        else:
            raise ValueError("Diese Aktion ist gerade nicht verfügbar.")

    def truth_choices(self, pid: str) -> list[int]:
        if self.phase != "draw" or self.actor != pid or self.manual_truth_draws >= 2 or len(self.state.players[pid].hand_cards) >= self.hand_limit:
            return []
        return core._available_truth_draw_values_for_hand_preparation(self.state, player_id=pid)

    def manifest_choices(self) -> list[str]:
        return core.get_manifestable_body_part_categories(self.state, player_id="p1",
            phenomenon_alignment=self.prize.metadata.get("alignment") if self.prize else "<Chaos>")

    def _opponent(self) -> None:
        pid = self.actor
        if self.phase == "turn":
            options = self.options(pid)
            preferred = next((opt for opt in options if opt["kind"] == "play"), None)
            if preferred is None:
                preferred = next((opt for opt in options if opt.get("role") == "Mönche"), None)
            if preferred and self.actions:
                self._execute(preferred, pid)
            else:
                self._begin_draw()
        elif self.phase == "draw":
            from .model import TRUTH_IDS
            available = self.truth_choices(pid)
            values = [value for value in reversed(TRUTH_IDS[pid]) if value in available]
            if values:
                core._add_truth_cards_to_hand(self.state, player_id=pid, truth_values=values[:min(2, self.hand_limit - len(self.state.players[pid].hand_cards))], source="manual-draw")
            self._finish_turn()
        elif self.phase == "contest":
            options = bidding.get_legal_bid_options(self.state, pid, self.contest)
            # Fixed personality, not access to the human's hand or hidden bid totals.
            count = sum(bid.player_id == pid for bid in self.contest.played_bids)
            choice = next((opt for opt in options if opt.truth_card_ids), None)
            legal_pass = any(move["action"] == "pass" for move in core.get_legal_moves(
                self.state, player_id=pid, phase="contest", contest_state=self.contest,
                eligible_player_ids=self.contest.player_order))
            if count >= 2 and legal_pass or not options:
                self._bid_step(pid, "pass", None)
            else:
                self._bid_step(pid, "bid", choice or options[0])

    def _bid_step(self, pid: str, action: str, choice: Any, *, sacrifice: bool | None = None) -> None:
        own = self.state.players["p1"]
        if (action == "pass" and not self.contest.nuns_used and sacrifice is None
                and self.contest.total_pass_count + 1 >= max(1, len(self.contest.player_order) - 1)
                and any(bid.player_id == "p1" and bid.truth_cards for bid in self.contest.played_bids)
                and own.nunnery_state.prepared_nuns and bidding._can_apply_nun_sacrifice(self.state, player_id="p1")):
            self.pending_pass = pid
            self.phase = "nun"
            return
        bidding.step_contest_with_intents(self.state, self.contest,
            turn_intents={pid: [bidding.ContestTurnIntent(action=action, bid_choice=choice)]},
            turn_intent_positions={pid: 0}, nun_sacrifice_decisions={"p1": bool(sacrifice), "p2": False, "p3": False},
            require_explicit_turn_intents=True)
        self.last_move = {"player": pid, "kind": action}
        if self.contest.ended:
            bidding._append_contest_reveal_window_events(self.state, contest=self.contest,
                                                        contested_card_id=self.prize.card_id)
            self.score = bidding.score_committed_bids(self.state, self.contest.played_bids)
            bidding.append_contest_reveal_log(self.state, contest_kind="mini", current_round=self.state.round_number,
                contested_card_id=self.prize.card_id, score=self.score, nun_sacrifice_player_ids=self.contest.nun_sacrifice_player_ids)
            for bid in self.contest.played_bids:
                for card in bid.truth_cards:
                    self.revealed_truth_art.add(self.art(card, bid.player_id))
            outcome = bidding.apply_contest_outcome_resolution(self.state,
                current_round=self.state.round_number, contested_card_id=self.prize.card_id, score=self.score)
            self.contest.winner_id = self.score.winner_id
            bidding.finalize_committed_bids(self.state, self.contest.played_bids)
            self._log_contest_end(outcome.outcome)
            self.phase = "claim"
            if self.score.winner_id != "p1":
                self._claim(False)

    def _log_contest_end(self, outcome: str) -> None:
        append_event(self.state.event_log, "contest_ended", current_round=self.state.round_number,
                     start_player_idx=self.state.start_player_idx, contested_card_id=self.prize.card_id,
                     winner_id=self.score.winner_id, bid_totals=self.score.bid_totals,
                     bid_count=self.contest.bid_count, passed_player_ids=list(self.contest.passed_player_ids),
                     tie_breaker=self.score.tie_breaker, outcome=outcome)

    def _claim(self, manifest: bool) -> None:
        pid = self.score.winner_id
        if pid:
            core.claim_phenomenon(self.state, player_id=pid, card_id=self.prize.card_id,
                card_name=self.prize.name, card_alignment=self.prize.metadata.get("alignment"),
                manifest_requested=manifest, manifest_body_part_category="Körperteil Beine" if manifest else None,
                allow_baseline_manifestation=False)
        self.phase = "round_end"

    def art(self, card: Any, pid: str = "p1") -> str:
        if card.category == "Wahrheit":
            return f"truth_{pid}_{card.truth_value}"
        if card.card_id == "loblied__Segen__2":
            return "song"
        return next((key for key, card_id in self.ids.items() if card_id == card.card_id), "")

    def view(self) -> dict[str, Any]:
        own = self.state.players["p1"]
        options = self.options()
        bid_ids = {card_id for choice in bidding.get_legal_bid_options(self.state, "p1", self.contest)
                   for card_id in choice.truth_card_ids + choice.heavenly_card_ids} if self.phase == "contest" and self.actor == "p1" else set()
        moves = core.get_legal_moves(self.state, player_id="p1", phase="contest", contest_state=self.contest,
                                    eligible_player_ids=self.contest.player_order) if self.phase == "contest" and self.actor == "p1" else []
        return {
            "phase": self.phase, "actor": self.actor, "actions": self.actions,
            "hand": [self.describe_card(card, own_hand=True) | {"id": card.card_id,
                      "can_bid": card.card_id in bid_ids} for card in own.hand_cards],
            "card_details": {self.art(card): self.describe_card(card)
                             for card in own.hand_cards + own.tableau +
                             ([self.prize] if self.prize else [])
                             if self.art(card)},
            "options": [{"index": index, "card_id": opt["intent"].get("card_id"), **{key: value for key, value in opt.items() if key != "intent"}}
                        for index, opt in enumerate(options)],
            "truth_choices": self.truth_choices("p1"), "draws_left": max(0, 2 - self.manual_truth_draws),
            "can_pass": any(move["action"] == "pass" for move in moves),
            "can_manifest": "Körperteil Beine" in self.manifest_choices(),
            "prize": self.art(self.prize) if self.prize else None,
            "history": list(self.history), "last_move": self.last_move,
            "rounds_left": self.state.endgame_rounds_left if self.state.endgame_active else None,
            "winner_ids": core.resolve_final_winners(self.state) if self.state.game_over else [],
            "game_over": self.state.game_over, "end_reason": self.state.game_over_reason,
            "roles": [{"type": role, "assigned": own.assigned_role_meeples.get(role, 0),
                       "capacity": getattr(own, field)} for role, field in (("Mönche", "monks_slots"), ("Missionare", "missionaries_slots"), ("Nonnen", "nuns_slots"))],
            "nun_active": own.nunnery_state.active, "nun_ready": own.nunnery_state.prepared_nuns,
            "stored": [self.art_by_id(card_id) for card_id in own.stored_phenomena],
            "prophet": own.prophet_owner,
            "players": [{"id": pid, "believers": player.meeples, "bound": sum(player.assigned_role_meeples.values()),
                         "alignment": player.alignment,
                         "complete": core.has_complete_trinity(player), "hand_count": len(player.hand_cards),
                         "tableau": [self.art(card, pid) for card in player.tableau if self.art(card, pid)],
                         "bid_count": sum(bid.player_id == pid for bid in self.contest.played_bids) if self.contest else 0,
                         "passed": bool(self.contest and pid in self.contest.passed_players)} for pid, player in self.state.players.items()],
            "own_bid_total": sum(bid.bid_total for bid in self.contest.played_bids if bid.player_id == "p1") if self.contest else 0,
            "score": self.score.bid_totals if self.score else None, "winner": self.score.winner_id if self.score else None,
            "bids": [{"player": bid.player_id, "values": bid.truth_values + [bidding._get_effective_bid_truth_value(self.state, player_id=bid.player_id, card=card) for card in bid.heavenly_cards],
                      "art": [self.art(card, bid.player_id) for card in bid.truth_cards + bid.heavenly_cards]}
                     for bid in self.contest.played_bids] if self.score and self.contest else [],
        }

    def describe_card(self, card: Any, *, own_hand: bool = False) -> dict[str, Any]:
        # Only callers holding the human hand or an already public card may project it.
        result = {"art": self.art(card), "category": card.category,
                  "rules_text": card.metadata.get("rules_text", ""),
                  "alignment": card.metadata.get("alignment"),
                  "cost_believers": card.metadata.get("cost_believers"),
                  "truth_value": card.truth_value}
        if own_hand:
            result["bid_value"] = bidding._get_effective_bid_truth_value(
                self.state, player_id="p1", card=card)
        return result

    def art_by_id(self, card_id: str) -> str:
        return next((key for key, value in self.ids.items() if value == card_id), "")
