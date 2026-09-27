import assert from "node:assert/strict";
import test from "node:test";

import { applyMove, chooseBotMove, createGame, legalMoves } from "../docs/engine.mjs";

test("same seed deals the same cards and isolates match state", () => {
  const first = createGame(7);
  const second = createGame(7);
  assert.deepEqual(first, second);
  const changed = applyMove(first, { action: "gather" });
  assert.equal(first.players[0].resources, 1);
  assert.equal(first.events.length, 0);
  assert.equal(changed.players[0].resources, 2);
});

test("draw moves one card from the pile and advances the turn", () => {
  const game = createGame(7);
  const topCard = game.drawPile[0];
  const next = applyMove(game, { action: "draw" });
  assert.equal(next.players[0].hand.at(-1), topCard);
  assert.equal(next.drawPile.length, game.drawPile.length - 1);
  assert.equal(next.turnIndex, 1);
  assert.equal(next.events[0].type, "card_drawn");
});

test("illegal moves reject without changing the match", () => {
  const game = createGame(7);
  assert.throws(() => applyMove(game, { action: "convert" }), RangeError);
  assert.throws(() => applyMove(game, { action: "play_card", cardId: "missing" }), RangeError);
  assert.throws(() => applyMove(game, { action: "gather", cardId: "unexpected" }), RangeError);
  assert.equal(game.turnIndex, 0);
  assert.equal(game.events.length, 0);
});

test("cards consume resources and can finish the match", () => {
  const game = createGame(7);
  const card = game.players[0].hand[0];
  const ready = {
    ...game,
    players: [{ ...game.players[0], resources: card.cost, progress: 10 - card.progress }, ...game.players.slice(1)],
  };
  const next = applyMove(ready, { action: "play_card", cardId: card.id });
  assert.equal(next.winnerId, "p1");
  assert.equal(next.players[0].resources, 0);
  assert.equal(next.players[0].discardCount, 1);
  assert.deepEqual(legalMoves(next), []);
  assert.equal(next.events.at(-1).type, "match_finished");
});

test("pass advances rounds after the last player", () => {
  let game = createGame(7);
  for (let index = 0; index < game.players.length; index += 1) {
    game = applyMove(game, { action: "pass" });
  }
  assert.equal(game.turnIndex, 0);
  assert.equal(game.roundNumber, 2);
});

test("bots only choose legal actions and eventually finish", () => {
  for (const seed of [0, 1, 7, 19, 99]) {
    let game = createGame(seed);
    for (let turn = 0; turn < 200 && !game.winnerId; turn += 1) {
      const chosen = chooseBotMove(game);
      assert.ok(legalMoves(game).some((move) =>
        move.action === chosen.action && (move.cardId ?? null) === (chosen.cardId ?? null)
      ));
      game = applyMove(game, chosen);
    }
    assert.ok(game.winnerId, `seed ${seed} should finish`);
    assert.ok(game.players.every((player) => player.resources >= 0));
  }
});

test("input ranges are checked", () => {
  for (const seed of [-1, 2 ** 32, 1.5, "7"]) {
    assert.throws(() => createGame(seed), RangeError);
  }
  assert.throws(() => createGame(7, 1), RangeError);
  assert.throws(() => createGame(7, 9), RangeError);
});
