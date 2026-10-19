'use strict';

let miniSelected = null;
let miniFeedback = '';
const miniRoles = () => ({'Mönche':t('Gesangsmönch','Singing monk'), 'Missionare':t('Missionar','Missionary'), 'Nonnen':t('Kampfnonne','Battle nun')});
const miniRoleArt = {'Mönche':'monk', 'Missionare':'missionary', 'Nonnen':'nun'};
const miniAlignments = () => ({
  '<Chaos>': ['alignment_chaos', t('Chaos','Chaos')],
  '<Zorn>': ['alignment_wrath', t('Zorn','Wrath')],
  '<Sanftmut>': ['alignment_gentle', t('Sanftmut','Gentleness')],
  '<Unergründlich>': ['alignment_unfathomable', t('Unergründlich','Unfathomable')],
});
function miniPlayer(id) { return playerName(state.players.find(p => p.id === id)); }
function gameCommand(label, {action, extra = '', sample, pass = false, selected = true} = {}) {
  const attrs = sample ? `data-access-demo="${sample}"` : `data-action="${action}"`;
  const key = pass ? 'P' : 'B';
  const shortcut = `<kbd class="command-key" aria-hidden="true">${key}</kbd>`;
  const keyAttrs = `data-command-key="${key}" ${selected ? '' : 'data-command-unselected'} ${selected && accessPreferences.commandKeys ? `aria-keyshortcuts="${key}"` : ''}`;
  return `<button type="button" class="${pass ? 'viewer-pass' : 'viewer-bid'}" ${attrs} ${keyAttrs} ${extra}>${pass ? `${image('pass','pass-figure','')}<span class="pass-caption"><span>${escape(label)}</span>${shortcut}</span>` : `<span>${escape(label)}</span>${shortcut}`}</button>`;
}
function miniHandCard(c, {sample = false} = {}) {
  const contest = !sample && state.match.phase === 'contest';
  const selected = sample ? true : miniSelected === c.id;
  const descriptionId = `${sample ? 'example' : 'hand'}-${c.id}`;
  const unavailable = contest && !c.can_bid;
  const plays = !sample && state.match.phase === 'turn' && state.match.actor === 'p1'
    ? state.match.options.filter(option => option.kind === 'play' && option.card_id === c.id) : [];
  return `<div class="mini-hand-card"><button type="button" class="hand-choice ${selected ? 'selected-card' : ''}" ${sample ? 'data-access-select' : `data-mini-select="${escape(c.id)}"`} aria-pressed="${selected}" aria-label="${escape(t(`${cardName(c.art)} auswählen`,`Select ${cardName(c.art)}`))}" aria-describedby="${escape(descriptionId)}">${image(c.art,'','')}<span class="hand-caption"><strong>${escape(cardName(c.art))}</strong><span class="hand-type">${escape(cardType(c.art))}</span>${c.bid_value !== undefined ? `<span class="hand-bid-value">${t('Gebotswert','Bid value')} ${c.bid_value}</span>` : ''}<span class="hand-state">${selected ? t('Ausgewählt','Selected') : t('Auswählen','Select')}${unavailable ? ` · ${t('Bieten nicht verfügbar','Bid unavailable')}` : ''}</span></span></button><div id="${escape(descriptionId)}" class="visually-hidden" hidden>${readableCard(c.art,c)}</div>${sample ? `<button type="button" class="hand-enlarge" data-art="${c.art}" aria-label="${escape(t(`${cardName(c.art)} vergrößern`,`Enlarge ${cardName(c.art)}`))}">+</button>` : ''}${plays.length ? `<div class="hand-play-commands">${plays.map(miniCommand).join('')}</div>` : ''}${contest || sample ? gameCommand(t('Bieten','Bid'),{action:'mini_bid',sample:sample ? 'bid' : null,selected,extra:`data-card-id="${escape(c.id)}" aria-label="${escape(t(`${cardName(c.art)} bieten`,`Bid ${cardName(c.art)}`))}" ${unavailable ? 'data-unavailable disabled' : ''}`}) : ''}</div>`;
}
function miniCardSummary(c) {
  return ({
    song:t('3 Gläubige · Chaos: 4','3 believers · Chaos: 4'),
    song_again:t('3 Gläubige · Zorn: 4','3 believers · Wrath: 4'),
    ash:t('Heiliges Heer ohne Opfer','Holy Host: no sacrifices'),
    skull:t('Segen: +2 Gläubige','Blessings: +2 believers'),
    army:t('Aufklärer entfernen','Remove an Enlightener'),
    enrico:t('Neue Reliquien gesperrt','New Relics blocked'),
    henk:t('Phänomen-Macht: 3 Opfer','Phenomenon power: 3 sacrifices'),
  })[c.art] || (c.category === 'Wahrheit' ? t(`Wahrheit ${c.truth_value}`,`Truth ${c.truth_value}`) : cardType(c.art));
}
function miniSelectedPreview() {
  const c = state.match.hand.find(item => item.id === miniSelected);
  if (!c || state.match.phase !== 'turn' || state.match.actor !== 'p1') return '';
  const alignment = state.players[0].alignment;
  const song = ['song','song_again'].includes(c.art);
  const gain = song && alignment ? 3 + Number(alignment === (c.art === 'song' ? '<Chaos>' : '<Zorn>')) + (state.tableau.includes('skull') ? 2 : 0) : null;
  const value = gain !== null ? `+${gain}` : c.category === 'Wahrheit' ? c.bid_value : null;
  const label = gain !== null ? t('Gläubige','believers') : c.category === 'Wahrheit' ? t('Wahrheit','Truth') : miniCardSummary(c);
  // Selection previews never play a card; legal commands still come from the server.
  return `<div class="mini-selected-preview" aria-label="${t('Ausgewählte Karte','Selected card')}"><span class="mini-card-altar" aria-hidden="true">${image(c.art,'mini-preview-art','')}</span><div class="mini-preview-effect">${value !== null ? `<strong>${escape(value)}</strong>` : ''}<span>${escape(label)}</span>${gain !== null ? `<div class="mini-preview-meeples" aria-hidden="true">${Array.from({length:gain},()=>image('believer','','')).join('')}</div>` : ''}</div></div>`;
}
function miniAnnouncement(before, after, action) {
  const m = after.match;
  const move = m.last_move;
  const labels = {
    mini_end_turn:t('Zug beendet.','Turn ended.'), mini_draw:t('Wahrheitskarte gezogen.','Truth card drawn.'),
    mini_draw_rest:t('Karten nachgezogen.','Cards drawn.'), mini_pass:t('Du passt endgültig.','You pass for good.'),
    mini_bid:t('Du bietest eine verdeckte Karte.','You bid a face-down card.'),
    mini_claim:t('Phänomen beansprucht.','Phenomenon claimed.'), mini_nun:t('Nonnen-Entscheidung ausgeführt.','Battle nun choice completed.'),
    mini_next_round:t('Runde abgeschlossen.','Round completed.'), start_mini:t('Deine Mini-Partie beginnt.','Your mini-match begins.'),
  };
  const parts = [move ? `${miniPlayer(move.player)}: ${move.kind === 'pass' ? t('passt endgültig','passes for good') : move.kind === 'bid' ? t('bietet eine verdeckte Karte','bids a face-down card') : move.art ? cardName(move.art) : move.role ? miniRoles()[move.role] : t('Zug ausgeführt','Move completed')}.` : labels[action] || t('Zug ausgeführt.','Move completed.')];
  if (before.match?.phase === 'contest' && m.phase !== 'contest' && m.score) {
    parts.push(t('Die Gebote sind aufgedeckt.', 'The bids are revealed.'));
    parts.push(after.players.map(p => `${playerName(p)}: ${m.score[p.id] ?? 0}`).join(', ') + '.');
    parts.push(m.winner
      ? m.winner === 'p1' ? t('Du gewinnst das Phänomen.', 'You win the phenomenon.')
        : t(`${miniPlayer(m.winner)} gewinnt das Phänomen.`, `${miniPlayer(m.winner)} wins the phenomenon.`)
      : t('Das Phänomen wird abgelegt.', 'The phenomenon is discarded.'));
  }
  if (before.stage === 'mini') {
    for (const p of after.players) {
      const old = before.players.find(item => item.id === p.id);
      const delta = p.believers - old.believers;
      const boundDelta = p.bound - old.bound;
      if (delta) parts.push(t(`${playerName(p)}: ${p.believers} freie Gläubige (${delta > 0 ? '+' : ''}${delta}).`, `${playerName(p)}: ${p.believers} free believers (${delta > 0 ? '+' : ''}${delta}).`));
      if (boundDelta) parts.push(t(`${playerName(p)}: ${p.bound} Gläubige in Tempeln (${boundDelta > 0 ? '+' : ''}${boundDelta}).`, `${playerName(p)}: ${p.bound} believers in temples (${boundDelta > 0 ? '+' : ''}${boundDelta}).`));
    }
  }
  if (m.phase === 'turn' && m.actor === 'p1') parts.push(t(`Dein Zug: ${m.actions} ${m.actions === 1 ? 'Aktion' : 'Aktionen'} übrig.`, `Your turn: ${m.actions} ${m.actions === 1 ? 'action' : 'actions'} left.`));
  else if (m.phase === 'contest') parts.push(m.actor === 'p1' ? t('Du bist beim Bieten am Zug.','It is your turn to bid.') : t(`${miniPlayer(m.actor)} ist beim Bieten am Zug.`, `${miniPlayer(m.actor)} is taking a bid turn.`));
  else if (m.phase === 'draw') parts.push(t('Karten nachziehen.','Draw cards.'));
  else if (m.phase === 'claim') parts.push(t('Macht behalten oder Beine manifestieren.','Keep the power or manifest legs.'));
  else if (m.phase === 'round_end') parts.push(t('Du kannst jetzt die Runde abschließen.', 'You can now complete the round.'));
  else if (m.phase === 'finished') parts.push(m.winner_ids.length ? t(`Sieger: ${m.winner_ids.map(miniPlayer).join(', ')}.`, `Winner: ${m.winner_ids.map(miniPlayer).join(', ')}.`) : t('Niemand hat gewonnen.','No one won.'));
  return parts.join(' ');
}
function miniPayload(element) {
  const result = {};
  if (element.dataset.moveIndex !== undefined) result.move_index = Number(element.dataset.moveIndex);
  if (element.dataset.cardId) result.card_id = element.dataset.cardId;
  if (element.dataset.value) result.value = Number(element.dataset.value);
  if (element.dataset.manifest !== undefined) result.manifest = element.dataset.manifest === 'true';
  if (element.dataset.sacrifice !== undefined) result.sacrifice = element.dataset.sacrifice === 'true';
  return result;
}
function miniOptionLabel(option) {
  const targetName = option.target ? miniPlayer(option.target) : '';
  switch (option.kind) {
    case 'play': return option.target ? t(`Spielen gegen ${targetName}`,`Play against ${targetName}`) : option.target_art ? t(`${cardName(option.target_art)} entfernen`,`Remove ${cardName(option.target_art)}`) : t('Karte spielen','Play card');
    case 'role': return miniRoles()[option.role];
    case 'grenade': return option.detonate ? t(`Ladung ${option.level}: ${targetName} treffen`,`Charge ${option.level}: strike ${targetName}`) : t(`Aufladen: Stufe ${option.level}`,`Charge: level ${option.level}`);
    case 'power': return t(`${targetName} setzt aus`,`${targetName} skips a turn`);
    case 'prophet': return t(`Prophet zu ${targetName}`,`Send Prophet to ${targetName}`);
    default: return t('Aktion auslassen','Skip action');
  }
}
function miniCommand(option) {
  const label = option.kind === 'play' ? `${cardName(option.art)}: ${miniOptionLabel(option)}` : miniOptionLabel(option);
  return button('mini_move', escape(miniOptionLabel(option)), 'confirm', `data-move-index="${option.index}" aria-label="${escape(label)}"`);
}
function miniTableauCommands() {
  const m = state.match;
  if (m.phase !== 'turn' || m.actor !== 'p1') return '';
  const roles = m.options.filter(option => option.kind === 'role');
  const charges = m.options.filter(option => option.kind === 'grenade');
  const chargeOnly = charges.find(option => !option.detonate);
  const other = m.options.filter(option => ['power','prophet'].includes(option.kind));
  if (!roles.length && !charges.length && !other.length) return '';
  return `<div class="mini-tableau-tools" aria-label="${t('Tableau-Befehle','Tableau commands')}">${roles.length ? `<div class="mini-temple-actions">${roles.map(option => `<button type="button" class="temple-command" data-action="mini_move" data-move-index="${option.index}">${image(miniRoleArt[option.role],'','')}<span>${escape(miniRoles()[option.role])}</span></button>`).join('')}</div>` : ''}${charges.length ? `<details class="mini-grenade-actions"><summary>${image('grenade','','')}${t('Heilige Handgranate','Holy Hand Grenade')} · ${state.grenade.level}/3</summary>${chargeOnly ? miniCommand(chargeOnly) : ''}${charges.filter(option => option.detonate).map(miniCommand).join('')}</details>` : ''}${other.length ? `<div class="mini-other-actions">${other.map(miniCommand).join('')}</div>` : ''}</div>`;
}
function miniBoard() {
  const m = state.match;
  const own = state.players[0];
  const relics = state.tableau.filter(key => ['ash','skull'].includes(key));
  const enlighteners = state.tableau.filter(key => key === 'enrico');
  const parts = ['head','chest','legs'].filter(key => state.tableau.includes(key));
  const assigned = Object.fromEntries(m.roles.map(role => [role.type,role.assigned]));
  const alignment = miniAlignments()[own.alignment];
  const slots = [['Mönche',[[17.3,31.1],[25.3,31.1],[21.3,22],[29.3,22]]], ['Missionare',[[76.3,29.8],[82,29.8]]]];
  return `<section class="mini-tableau" aria-label="${t('Dein Originaltableau','Your original tableau')}">
    <div class="mini-flock"><div><h2>${t('Dein Himmelreich','Your realm')}</h2><strong>${own.believers}</strong><span>${t('freie Gläubige','free believers')}</span></div>${m.prophet ? `<span class="mini-prophet">${image('prophet','', '')}${t('Der Prophet ist bei dir','The Prophet is with you')}</span>` : ''}</div>
    <div class="original-tableau">${image('playerboard','original-board',t('Originales englisches Spielertableau','Original English player board'))}
      ${alignment ? `<span class="board-alignment">${image(alignment[0],'',t(`Gesinnung: ${alignment[1]}`,`Alignment: ${alignment[1]}`))}</span>` : ''}
      ${parts.map(key => `<button type="button" class="board-body board-${key}" data-art="${key}" aria-label="${escape(t(`${cardName(key)} vergrößern`,`Enlarge ${cardName(key)}`))}">${image(key)}</button>`).join('')}
      ${relics.map((key,i) => `<button type="button" class="board-relic relic-${i}" data-art="${key}" aria-label="${escape(t(`${cardName(key)} vergrößern`,`Enlarge ${cardName(key)}`))}">${image(key)}</button>`).join('')}
      ${slots.flatMap(([role,positions]) => positions.slice(0,assigned[role] || 0).map(([x,y]) => `<span class="board-role board-role-${miniRoleArt[role]}" style="left:${x}%;top:${y}%">${image(miniRoleArt[role],'',miniRoles()[role])}</span>`)).join('')}
      <div class="board-grenade" role="img" aria-label="${t('Granate geladen auf Stufe','Grenade charged to level')} ${state.grenade.level}">${Array.from({length:state.grenade.level},()=>image('believer','', '')).join('')}</div>
    </div>
    <div class="visually-hidden mini-tableau-status">${escape(alignment?.[1] || '')}. ${t('Tempel','Temples')} ${own.bound}/${m.roles.reduce((sum,role)=>sum + role.capacity,0)}. ${m.roles.map(role=>`${miniRoles()[role.type]} ${role.assigned}/${role.capacity}`).join(' · ')}</div>
    <div class="mini-free-flock">${tokens(own.believers,'',previousBelievers.p1 ?? own.believers)}</div>
    ${enlighteners.length ? `<div class="mini-enlighteners"><h3>${t('Aufklärer an deinem Tableau','Enlighteners on your tableau')}</h3>${enlighteners.map(key=>card(key)).join('')}</div>` : ''}${m.stored.length ? `<div class="mini-stored"><h3>${t('Gespeicherte Mächte','Stored powers')}</h3>${m.stored.map(key=>card(key,'landscape')).join('')}</div>` : ''}${miniTableauCommands()}
  </section>`;
}
function miniOpponents(motion) {
  return `<div class="mini-opponents">${state.players.slice(1).map(p=>`<section class="mini-opponent ${state.match.actor === p.id ? 'active-opponent' : ''}" aria-label="${escape(p.name)}"><div class="bid-portrait ${motion?.player === p.id ? 'opponent-playing' : ''}" aria-hidden="true">${image(p.id === 'p2' ? 'frauke':'henk','','')}</div><div><h2>${escape(p.name)}</h2><p><strong>${p.believers}</strong> ${t('Gläubige','believers')}${p.bound ? ` · ${p.bound} ${t('im Tempel','in temples')}` : ''}</p><small>${p.hand_count} ${t('Karten','cards')}${state.match.actor === p.id ? ` · ${t('Am Zug','Taking a turn')}` : ''}</small></div></section>`).join('')}</div>`;
}
function miniContest(motion) {
  const m = state.match;
  const original = state;
  // Reuse only the existing redacted bid presentation, not the full Viewer.
  state = {...state,score:m.score,winner:m.winner,bids:m.bids,contest_turn:m.actor,own_bid_total:m.own_bid_total};
  const table = contestTable(motion);
  state = original;
  return `<div class="mini-contest-prize"><div class="middleboard">${image('middleboard','',t('Originales Phänomen-Brett','Original phenomenon board'))}${card(m.prize,'landscape')}</div></div>${table}`;
}
function miniPhenomenonExamples() {
  const examples = [['yak','Two-headed Yak'],['squirrels','Squirrel plague'],['earthquake','Earthquake']];
  return `<figure class="mini-phenomenon-examples"><div class="middleboard">${image('middleboard','',t('Originales Phänomen-Brett','Original phenomenon board'))}<div class="mini-phenomenon-selection" role="group" aria-label="${t('Phänomen-Beispiele, kein laufendes Stechen','Phenomenon examples, not an active contest')}">${examples.map(([key,name]) => `<button type="button" class="card-art landscape" data-art="${key}" data-art-english="true" data-art-title="${name}" aria-label="${escape(t(`Englisches Phänomen ${name} vergrößern`,`Enlarge English Phenomenon: ${name}`))}"><span class="card-picture">${image(`${key}_en`,'',name)}</span></button>`).join('')}</div></div><figcaption>${t('Kartenauswahl','Card selection')}</figcaption></figure>`;
}
function miniActions() {
  const m = state.match;
  if (m.phase === 'finished') {
    const winners = m.winner_ids.map(miniPlayer);
    return `<h2>${winners.length ? t('Das Himmelreich hat entschieden.','The Heavenly Realm has spoken.') : t('Noch kein fertiger Gott.','No complete god yet.')}</h2><p class="mini-result">${escape(winners.length ? winners.join(' & ') : t('Alle verlieren: Niemand hat seine Dreifaltigkeit vollendet.','Everyone loses: no one completed their Trinity.'))}</p>${m.winner_ids.length > 1 ? `<p>${t('Geteilter Sieg','Shared victory')}</p>` : ''}<p>${t('Vollständige Götter stehen vor unvollständigen. Danach zählen Gläubige in der Herde und auf dem Tableau.','Complete gods rank above incomplete ones. Then believers in the flock and on the tableau decide.')}</p>${button('overview',t('Das Himmelreich geht weiter','The Heavenly Realm goes on'),'next')}${button('restart',t('Neue Mini-Partie','New mini-match'),'back')}<button type="button" class="back" data-tech>${t('Unter der Oberfläche','Under the surface')}</button>`;
  }
  if (m.phase === 'round_end') return `<h2>${t('Die Karten liegen offen.','The cards are face up.')}</h2><p>${m.winner ? t(`${miniPlayer(m.winner)} gewinnt das Phänomen.`,`${miniPlayer(m.winner)} wins the phenomenon.`) : t('Das Phänomen wird abgelegt.','The phenomenon is discarded.')}</p>${m.score ? `<p class="mini-result">${state.players.map(p=>`${playerName(p)}: ${m.score[p.id] || 0}`).join(' · ')}</p>` : ''}${state.revealed ? `<p>${t('Walter ist vollständig. Die Götterdämmerung läuft.','Walter is complete. Twilight of the Gods is underway.')}</p>` : ''}${button('mini_next_round',t('Runde abschließen','Complete the round'),'next')}`;
  if (m.phase === 'claim') return `<h2>${t('Das Phänomen gehört dir.','The phenomenon is yours.')}</h2><p>${t('Die Macht bleibt gespeichert. Du entscheidest über die Manifestation.','The power stays stored. You decide whether to manifest.')}</p>${m.can_manifest ? button('mini_claim',t('Walters Beine manifestieren','Manifest Walter’s legs'),'next','data-manifest="true"') : ''}${button('mini_claim',t('Nur die Macht behalten','Keep only the power'),'back','data-manifest="false"')}`;
  if (m.phase === 'nun') return `<h2>${t('Das Nonnen-Fenster öffnet sich.','The Battle nun window opens.')}</h2>${image('nun','mini-nun','')}<p>${t('Opfere eine vorbereitete Kampfnonne, um deine niedrigste gebotene Wahrheitskarte zu verdoppeln. Auch nach deinem Pass.','Sacrifice one prepared Battle nun to double your lowest Truth card bid. Even after you passed.')}</p>${button('mini_nun',t('Eine Nonne opfern','Sacrifice one nun'),'confirm','data-sacrifice="true"')}${button('mini_nun',t('Nonne behalten','Keep the nun'),'back','data-sacrifice="false"')}`;
  if (m.actor !== 'p1') return `<h2>${escape(miniPlayer(m.actor))}</h2><p id="bid-turn" tabindex="-1">${t('Dein Mitgott ist am Zug.','Your fellow god is taking a turn.')}</p>${button('mini_advance',`${t('Weiter','Continue')} ${arrowIcon}`,'next',`data-mini-continue aria-label="${escape(t(`Weiter: ${miniPlayer(m.actor)}`,`Continue: ${miniPlayer(m.actor)}`))}"`)}`;
  if (m.phase === 'draw') return `<h2>${t('Dein nächster Plan.','Your next plan.')}</h2><p>${t(`Noch ${m.draws_left} Wahrheitswahlen.`,`${m.draws_left} Truth choices left.`)}</p><div class="mini-truth-draw">${[...new Set(m.truth_choices)].map(value=>button('mini_draw',`${image(`truth_p1_${value}`,'','')}<span>${value}</span>`,'truth-pick',`data-value="${value}" aria-label="${t(`Wahrheit ${value} ziehen`,`Draw Truth ${value}`)}"`)).join('')}</div>${button('mini_draw_rest',t('Rest mit Himmelreich auffüllen','Fill the rest from the Heavenly Realm'),'confirm')}`;
  if (m.phase === 'contest') return `<h2>${t('Dein Gebot.','Your bid.')}</h2><p id="bid-turn" tabindex="-1">${t('Eine Karte bieten oder endgültig passen.','Bid one card or pass for good.')}</p>${gameCommand(t('Endgültig passen','Pass for good'),{action:'mini_pass',pass:true,extra:m.can_pass ? '' : 'data-unavailable disabled'})}<p>${t('Dein gebotener Wahrheitswert:','Your committed Truth:')} <strong>${m.own_bid_total}</strong></p>`;
  return `<span class="mini-action-count">${m.actions} ${m.actions === 1 ? t('Aktion übrig','action left') : t('Aktionen übrig','actions left')}</span>${button('mini_end_turn',t('Zug beenden & nachziehen','End turn & draw'),'next')}`;
}
function miniHand() {
  const m = state.match;
  return `<section class="mini-hand" aria-labelledby="hand-title"><div class="mini-hand-heading"><div class="mini-hand-title"><h2 id="hand-title">${t('Deine Kartenhand','Your hand')}</h2><span>${m.hand.length} ${t('Karten','cards')}</span></div><div class="mini-turn-tools" aria-label="${t('Zugbefehle','Turn commands')}">${miniActions()}</div></div><div class="mini-hand-grid">${m.hand.map(c=>miniHandCard(c)).join('')}</div></section>`;
}
function miniScene(motion, arriving = false) {
  const m = state.match;
  if (!m.hand.some(c=>c.id === miniSelected)) miniSelected = m.hand.find(c=>m.options.some(o=>o.kind === 'play' && o.art === c.art))?.id || m.hand[0]?.id || null;
  const contest = ['contest','claim','nun','round_end'].includes(m.phase);
  return `<section class="mini-match ${arriving ? 'mini-arriving' : ''}">
    <header class="mini-heading"><div class="mini-realm-title"><h1 id="stage-title" tabindex="-1"><span class="mini-name-halo" aria-hidden="true"></span>Walter</h1></div><div class="mini-round-status"><span>${t('Runde','Round')} ${state.round} · ${state.body_count}/3 ${t('Körperteile','body parts')}</span>${state.endgame ? `<span>${t(`Götterdämmerung: ${m.rounds_left ?? 3} Schlussrunden`,`Twilight: ${m.rounds_left ?? 3} final rounds`)}</span>` : ''}</div></header>
    <div class="mini-play-area ${contest ? 'mini-contesting' : ''}">${miniBoard()}
      <div class="mini-center"><h2 class="mini-table-title">${t('Am Spieltisch','At the table')}</h2>
        ${contest && m.prize ? miniContest(motion) : miniPhenomenonExamples()}
        ${contest ? '' : miniOpponents(motion)}${miniSelectedPreview()}
      </div>
    </div>${miniFeedback ? `<div id="mini-action-result" class="mini-action-feedback" role="group" tabindex="-1" aria-live="off" aria-label="${escape(miniFeedback)}"><p>${escape(miniFeedback)}</p></div>` : ''}${m.phase !== 'finished' ? miniHand() : `<footer class="mini-turn-tools mini-finished">${miniActions()}</footer>`}
  </section>`;
}
