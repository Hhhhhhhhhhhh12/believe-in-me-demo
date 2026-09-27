export const CARDS = Object.freeze([
  { id: "advance-1", name: "Advance", cost: 2, progress: 2, art: "advance" },
  { id: "advance-2", name: "Advance", cost: 2, progress: 2, art: "advance" },
  { id: "boost-1", name: "Boost", cost: 3, progress: 4, art: "boost" },
  { id: "boost-2", name: "Boost", cost: 3, progress: 4, art: "boost" },
  { id: "focus-1", name: "Focus", cost: 1, progress: 1, art: "focus" },
  { id: "focus-2", name: "Focus", cost: 1, progress: 1, art: "focus" },
  { id: "sprint-1", name: "Sprint", cost: 4, progress: 5, art: "sprint" },
  { id: "sprint-2", name: "Sprint", cost: 4, progress: 5, art: "sprint" },
]);

function shuffledDeck(seed) {
  let value = seed || 0x9e3779b9;
  const deck = [...CARDS];
  for (let index = deck.length - 1; index > 0; index -= 1) {
    value ^= value << 13;
    value ^= value >>> 17;
    value ^= value << 5;
    const target = (value >>> 0) % (index + 1);
    [deck[index], deck[target]] = [deck[target], deck[index]];
  }
  return deck;
}

export function createGame(seed = 7, playerCount = 3) {
  if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) {
    throw new RangeError("Seed must be an integer between 0 and 4294967295.");
  }
  if (!Number.isInteger(playerCount) || playerCount < 2 || playerCount > 8) {
    throw new RangeError("Player count must be between two and eight.");
  }
  const deck = shuffledDeck(seed);
  return {
    seed,
    players: Array.from({ length: playerCount }, (_, index) => ({
      id: `p${index + 1}`,
      resources: 1,
      progress: 0,
      hand: [deck[index]],
      discardCount: 0,
    })),
    drawPile: deck.slice(playerCount),
    turnIndex: 0,
    roundNumber: 1,
    targetProgress: 10,
    winnerId: null,
    events: [],
  };
}

export function legalMoves(state) {
  if (state.winnerId !== null) return [];
  const player = state.players[state.turnIndex];
  const moves = [{ action: "gather" }, { action: "pass" }];
  if (state.drawPile.length && player.hand.length < 3) moves.push({ action: "draw" });
  if (player.resources >= 3) moves.push({ action: "convert" });
  for (const card of player.hand) {
    if (player.resources >= card.cost) moves.push({ action: "play_card", cardId: card.id });
  }
  return moves;
}

export function applyMove(state, move) {
  if (!legalMoves(state).some((allowed) =>
    allowed.action === move.action && (allowed.cardId ?? null) === (move.cardId ?? null)
  )) {
    throw new RangeError("That move is not available.");
  }
  const player = state.players[state.turnIndex];
  let updated = { ...player };
  let drawPile = state.drawPile;
  let type;
  let data = {};

  switch (move.action) {
    case "gather":
      updated.resources += 1;
      type = "resource_gained";
      data = { amount: 1 };
      break;
    case "draw": {
      const card = drawPile[0];
      updated.hand = [...player.hand, card];
      drawPile = drawPile.slice(1);
      type = "card_drawn";
      data = { card_id: card.id, card_name: card.name };
      break;
    }
    case "convert":
      updated.resources -= 3;
      updated.progress += 2;
      type = "resources_converted";
      data = { cost: 3, progress: 2 };
      break;
    case "play_card": {
      const card = player.hand.find((item) => item.id === move.cardId);
      updated.resources -= card.cost;
      updated.progress += card.progress;
      updated.hand = player.hand.filter((item) => item.id !== card.id);
      updated.discardCount += 1;
      type = "card_played";
      data = {
        card_id: card.id, card_name: card.name,
        cost: card.cost, progress: card.progress,
      };
      break;
    }
    default:
      type = "turn_passed";
  }

  const players = state.players.map((item, index) => index === state.turnIndex ? updated : item);
  const event = {
    round: state.roundNumber,
    turn_index: state.turnIndex,
    player_id: player.id,
    type,
    ...data,
  };
  const events = [...state.events, event];
  if (updated.progress >= state.targetProgress) {
    return {
      ...state, players, drawPile, winnerId: player.id,
      events: [...events, {
        round: state.roundNumber,
        turn_index: state.turnIndex,
        player_id: player.id,
        type: "match_finished",
        winner_id: player.id,
      }],
    };
  }
  const turnIndex = (state.turnIndex + 1) % players.length;
  return {
    ...state, players, drawPile, events, turnIndex,
    roundNumber: state.roundNumber + (turnIndex === 0 ? 1 : 0),
  };
}

export function chooseBotMove(state) {
  const moves = legalMoves(state);
  if (!moves.length) throw new RangeError("The match is already finished.");
  const player = state.players[state.turnIndex];
  const playable = moves.filter((move) => move.action === "play_card");
  const progressOf = (move) => player.hand.find((card) => card.id === move.cardId).progress;
  const winning = playable.find((move) => player.progress + progressOf(move) >= state.targetProgress);
  if (winning) return winning;
  const convert = moves.find((move) => move.action === "convert");
  if (convert && player.progress + 2 >= state.targetProgress) return convert;
  if (playable.length) return playable.reduce((best, move) =>
    progressOf(move) > progressOf(best) ? move : best
  );
  const draw = moves.find((move) => move.action === "draw");
  if (draw && !player.hand.length) return draw;
  return convert ?? moves[0];
}
