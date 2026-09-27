import { applyMove, createGame, legalMoves, chooseBotMove } from "./engine.mjs";

const byId = (id) => document.getElementById(id);
const seedInput = byId("seed");
const hand = byId("hand");
const opponentList = byId("opponents");
const eventsList = byId("events");
const resultPanel = byId("result");
let game;
let generation = 0;
let moveCount = 0;

function textElement(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = content;
  return element;
}

function scoreTrack(player) {
  const track = document.createElement("progress");
  track.max = game.targetProgress;
  track.value = player.progress;
  track.setAttribute("aria-label", `${player.id} progress toward ${game.targetProgress}`);
  return track;
}

function eventLabel(event) {
  const actor = event.player_id === "p1" ? "You" : `Bot ${event.player_id.slice(1)}`;
  switch (event.type) {
    case "resource_gained": return `${actor} gathered a resource.`;
    case "card_drawn": return `${actor} drew a card.`;
    case "resources_converted": return `${actor} converted resources into 2 progress.`;
    case "card_played": return `${actor} played ${event.card_name} for ${event.progress} progress.`;
    case "turn_passed": return `${actor} passed.`;
    default: return "Match complete.";
  }
}

function renderOpponents() {
  opponentList.replaceChildren();
  for (const player of game.players.slice(1)) {
    const seat = textElement("article", "opponent", "");
    if (game.turnIndex === Number(player.id.slice(1)) - 1 && !game.winnerId) {
      seat.classList.add("is-active");
    }
    const top = textElement("div", "opponent-top", "");
    top.append(
      textElement("strong", "", `Bot ${player.id.slice(1)}`),
      textElement("span", "", `${player.progress} / ${game.targetProgress}`),
    );
    const details = textElement(
      "p", "opponent-details",
      `${player.resources} resources · ${player.hand.length} cards`,
    );
    seat.append(top, scoreTrack(player), details);
    opponentList.append(seat);
  }
}

function renderHand(available) {
  hand.replaceChildren();
  const cards = game.players[0].hand;
  byId("hand-count").textContent = `${cards.length} / 3 cards`;
  if (!cards.length) {
    hand.append(textElement("p", "empty-hand", "No cards in hand. Draw a card or gather resources."));
    return;
  }
  for (const card of cards) {
    const enabled = available.some((move) => move.action === "play_card" && move.cardId === card.id);
    const button = document.createElement("button");
    button.type = "button";
    button.className = `hand-card art-${card.art}`;
    button.dataset.cardId = card.id;
    button.disabled = !enabled;
    button.setAttribute("aria-label", `Play ${card.name}: cost ${card.cost}, gain ${card.progress} progress`);
    const art = document.createElement("img");
    art.src = `./assets/${card.art}.svg`;
    art.alt = "";
    art.width = 88;
    art.height = 88;
    const top = textElement("span", "card-top", card.name);
    const bottom = textElement("span", "card-bottom", "");
    bottom.append(
      textElement("span", "", `${card.cost} cost`),
      textElement("strong", "", `+${card.progress} progress`),
    );
    button.append(top, art, bottom);
    hand.append(button);
  }
}

function renderEvents() {
  eventsList.replaceChildren();
  const recent = game.events.filter((event) => event.type !== "match_finished").slice(-7).reverse();
  for (const event of recent) {
    const item = textElement("li", "", eventLabel(event));
    const round = textElement("span", "event-round", `R${event.round}`);
    item.prepend(round);
    eventsList.append(item);
  }
  byId("turn-count").textContent = `${moveCount} ${moveCount === 1 ? "turn" : "turns"}`;
}

function render() {
  const yourTurn = game.turnIndex === 0 && !game.winnerId;
  const available = yourTurn ? legalMoves(game) : [];
  const you = game.players[0];
  byId("round-number").textContent = game.roundNumber;
  byId("your-resources").textContent = you.resources;
  byId("your-progress").textContent = you.progress;
  byId("your-progress-bar").value = you.progress;
  byId("deck-count").textContent = game.drawPile.length;
  byId("turn-status").textContent = game.winnerId
    ? "Match complete"
    : yourTurn ? "Your turn" : `Bot ${game.turnIndex + 1} is playing`;
  for (const button of document.querySelectorAll("[data-move]")) {
    button.disabled = !available.some((move) => move.action === button.dataset.move);
  }
  renderOpponents();
  renderHand(available);
  renderEvents();
  resultPanel.hidden = !game.winnerId;
  if (game.winnerId) {
    resultPanel.className = `result ${game.winnerId === "p1" ? "won" : "lost"}`;
    resultPanel.replaceChildren(
      textElement("span", "eyebrow", "Match complete"),
      textElement("h2", "", game.winnerId === "p1" ? "You won" : `Bot ${game.winnerId.slice(1)} won`),
      textElement("p", "", `${moveCount} turns · Seed ${game.seed}`),
    );
  }
}

function advanceBots(expectedGeneration) {
  if (expectedGeneration !== generation || game.winnerId || game.turnIndex === 0) return;
  window.setTimeout(() => {
    if (expectedGeneration !== generation || game.winnerId || game.turnIndex === 0) return;
    game = applyMove(game, chooseBotMove(game));
    moveCount += 1;
    render();
    advanceBots(expectedGeneration);
  }, 400);
}

function takeMove(move) {
  if (game.turnIndex !== 0 || game.winnerId) return;
  const available = legalMoves(game);
  if (!available.some((candidate) =>
    candidate.action === move.action && (candidate.cardId ?? null) === (move.cardId ?? null)
  )) return;
  game = applyMove(game, move);
  moveCount += 1;
  render();
  advanceBots(generation);
}

document.querySelector(".arena").addEventListener("click", (event) => {
  const card = event.target.closest("[data-card-id]");
  if (card) return takeMove({ action: "play_card", cardId: card.dataset.cardId });
  const action = event.target.closest("[data-move]");
  if (action) takeMove({ action: action.dataset.move });
});

byId("new-game").addEventListener("submit", (event) => {
  event.preventDefault();
  const seed = Number(seedInput.value);
  if (!Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) {
    seedInput.setCustomValidity("Enter an integer from 0 to 4294967295.");
    seedInput.reportValidity();
    return;
  }
  seedInput.setCustomValidity("");
  generation += 1;
  moveCount = 0;
  game = createGame(seed);
  render();
});

seedInput.addEventListener("input", () => seedInput.setCustomValidity(""));
game = createGame(7);
render();
