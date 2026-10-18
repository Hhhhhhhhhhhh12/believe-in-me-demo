'use strict';

const t = DemoLanguage.text;
const projectStats = JSON.parse(document.querySelector('#project-stats')?.textContent || 'null');
const developmentStats = JSON.parse(document.querySelector('#development-stats')?.textContent || 'null');
const app = document.querySelector('#app');
const accessibilityPage = location.pathname.endsWith('/accessibility.html');
const techPage = location.pathname.endsWith('/under-the-surface.html');
const informationPage = accessibilityPage || techPage;
const storyDestinations = ['opening','flock','rivals','body','ready','app','board','play'];
const requestedResume = new URLSearchParams(location.search).get('resume');
let resumeChapter = storyDestinations.includes(requestedResume) ? requestedResume : null;
let accessReturnChapter = '';
if (resumeChapter) {
  const url = new URL(location.href); url.searchParams.delete('resume');
  history.replaceState(null, '', url);
}
if (accessibilityPage) app.replaceChildren(document.querySelector('#accessibility-content').content.cloneNode(true));
if (techPage) app.replaceChildren(document.querySelector('#tech-content').content.cloneNode(true));
const errorBox = document.querySelector('#error');
const announcements = document.querySelector('#announcements');
const systemMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
const accessStorageKey = 'believe-in-me-accessibility-v1';
const defaultAccessPreferences = {textSize:'normal', clearCards:false, highContrast:false, motion:'system', commandKeys:true};
let accessPreferences = {...defaultAccessPreferences};
let accessNotice = '';
let accessExampleState = 'ready';
let briefingScroll = null;
let viewerSceneKey = 'viewer_lobby';
try {
  const stored = JSON.parse(localStorage.getItem(accessStorageKey) || 'null');
  if (stored && typeof stored === 'object' && !Array.isArray(stored)) {
    if (['normal','larger'].includes(stored.textSize)) accessPreferences.textSize = stored.textSize;
    for (const key of ['clearCards','highContrast','commandKeys']) {
      if (typeof stored[key] === 'boolean') accessPreferences[key] = stored[key];
    }
    if (['system','reduced','full'].includes(stored.motion)) accessPreferences.motion = stored.motion;
  } else {
    const legacy = localStorage.getItem('believe-in-me-motion');
    if (['reduced','full'].includes(legacy)) accessPreferences.motion = legacy;
  }
} catch (_) { /* The setting still works when browser storage is unavailable. */ }

function applyMotionPreference(scrollSnapshot = briefingScroll?.capture()) {
  const reduced = accessPreferences.motion === 'reduced' || (accessPreferences.motion === 'system' && systemMotion.matches);
  document.documentElement.dataset.motion = reduced ? 'reduced' : 'full';
  if (reduced) { stopBelieverAnimation(); stopContestAnimation(); }
  briefingScroll?.refresh(scrollSnapshot);
  document.querySelectorAll('#reduce-motion,[data-access-pref="motion"]').forEach(input => { input.checked = reduced; });
  const status = reduced ? t('Animationen sind ausgeschaltet.', 'Animations are off.') : t('Animationen sind eingeschaltet.', 'Animations are on.');
  document.querySelectorAll('#motion-status,#settings-motion-status').forEach(node => {
    node.textContent = `${status} ${accessPreferences.motion === 'system' ? t('Folgt deiner Systemeinstellung.', 'Following your system preference.') : ''}`;
  });
}

function applyAccessPreferences() {
  const scrollSnapshot = briefingScroll?.capture();
  const root = document.documentElement;
  root.dataset.textSize = accessPreferences.textSize;
  root.dataset.clearCards = accessPreferences.clearCards ? 'on' : 'off';
  root.dataset.contrast = accessPreferences.highContrast ? 'high' : 'normal';
  root.dataset.commandKeys = accessPreferences.commandKeys ? 'on' : 'off';
  document.querySelectorAll('[name="text-size"],[data-access-pref="textSize"]').forEach(input => { input.checked = input.value === accessPreferences.textSize; });
  for (const [key, id] of [['clearCards','clear-card-labels'],['highContrast','high-contrast'],['commandKeys','bid-pass-shortcuts']]) {
    document.querySelectorAll(`#${id},[data-access-pref="${key}"]`).forEach(input => { input.checked = accessPreferences[key]; });
  }
  syncCommandShortcuts();
  applyMotionPreference(scrollSnapshot);
  document.querySelectorAll('#accessibility-status,#settings-status').forEach(node => { node.textContent = ({
    saved: t('Anzeigeeinstellungen gespeichert.', 'Display settings saved.'),
    temporary: t('Angewendet. Dieser Browser kann die Auswahl nicht für den nächsten Start speichern.', 'Applied. This browser cannot save your choices for the next visit.'),
    reset: t('Anzeige zurückgesetzt. Sprache und Spielstand bleiben unverändert.', 'Display reset. Language and game state are unchanged.'),
  })[accessNotice] || ''; });
  briefingScroll?.refresh(scrollSnapshot);
}

function saveAccessPreferences(reset = false) {
  accessNotice = reset ? 'reset' : 'saved';
  try { localStorage.setItem(accessStorageKey, JSON.stringify(accessPreferences)); }
  catch (_) { accessNotice = 'temporary'; }
  applyAccessPreferences();
}

document.addEventListener('change', event => {
  const preference = event.target.dataset.accessPref;
  if (preference === 'textSize') accessPreferences.textSize = event.target.value;
  else if (preference === 'motion') accessPreferences.motion = event.target.checked ? 'reduced' : 'full';
  else if (['clearCards','highContrast','commandKeys'].includes(preference)) accessPreferences[preference] = event.target.checked;
  else if (event.target.name === 'text-size') accessPreferences.textSize = event.target.value;
  else if (event.target.id === 'clear-card-labels') accessPreferences.clearCards = event.target.checked;
  else if (event.target.id === 'high-contrast') accessPreferences.highContrast = event.target.checked;
  else if (event.target.id === 'reduce-motion') accessPreferences.motion = event.target.checked ? 'reduced' : 'full';
  else if (event.target.id === 'bid-pass-shortcuts') accessPreferences.commandKeys = event.target.checked;
  else return;
  saveAccessPreferences();
});
document.addEventListener('click', event => {
  if (event.target.closest('#motion-system,[data-motion-system]')) {
    accessPreferences.motion = 'system';
    saveAccessPreferences();
  }
  if (event.target.closest('#reset-accessibility,[data-reset-accessibility]')) {
    accessPreferences = {...defaultAccessPreferences};
    saveAccessPreferences(true);
  }
});
systemMotion.addEventListener('change', () => { if (accessPreferences.motion === 'system') applyMotionPreference(); });
applyAccessPreferences();
let state;
let busy = false;
let lastStage = '';
let target = 'p2';
let previousBelievers = {};
let animateBelievers = false;
let enlargedArt = null;
let enlargedArtOptions = {};
let restartOpener = null;
let accessibilityOpener = null;
let miniBriefing = !informationPage && location.hash === '#before-mini-match';
let introBriefing = !informationPage && (miniBriefing || Boolean(resumeChapter) || location.hash === '#before-you-play' || location.hash.startsWith('#story-'));
if (introBriefing) {
  // Chapter links remain useful in-page; a fresh visit starts the story at the top.
  history.scrollRestoration = 'manual';
  const url = new URL(location.href);
  url.hash = miniBriefing ? 'before-mini-match' : 'before-you-play';
  history.replaceState(null, '', url);
}
let opponentTimer = null;
let bidMotion = null;
const names = {
  song: 'Loblied', song_again: 'Loblied', ash: 'Roswithas noch warme Asche',
  skull: 'Ansgards geborstener Schädel', enrico: 'Enrico der Entdecker',
  army: 'Irmgard die Inquisitorin', grenade: 'Heilige Handgranate der kalten Rache',
  yak: 'Yak mit 2 Köpfen', head: 'Walter', chest: 'der zweifelnde Bestimmer',
  legs: 'mit Hausstauballergie', frauke: 'Frauke die Foltermagd', henk: 'Henk der Hetzer',
  squirrels: 'Eichhörnchenplage', earthquake: 'Erdbeben', tornado: 'Tornado',
};
const artNames = {
  ...names,
  ash: 'Die noch warme Asche von Roswitha, der Rothaarigen',
  skull: 'Der geborstene Schädel von Ansgard, dem Älteren',
};
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const viewerScenes = () => [
  ['viewer_lobby', t('Himmelspforte', 'Heavenly Gate'), t('Original-Viewer: englischer Einstieg mit Logo und Spielauswahl.', 'Original Viewer: English entry with the logo and game selection.'), t('Dein Weg ins Himmelreich.', 'Your way into the Heavenly Realm.')],
  ['viewer_cards', t('Karten und Entscheidungen', 'Cards and choices'), t('Original-Viewer: Roswitha und Irmgard auf der Hand, mit Henk und Abdul als sichtbaren Zielen.', 'Original Viewer: Roswitha and Irma in hand, with Henk and Abdul as visible targets.'), t('Eine Kartenhand. Mehr als ein Plan.', 'One hand. More than one plan.')],
  ['viewer_truth', t('Wahrheitskarten', 'Truth cards'), t('Original-Viewer: Gloria mit den Wahrheitskarten 2, 4 und 6 zur Auswahl.', 'Original Viewer: Gloria with Truth cards 2, 4 and 6 to choose from.'), t('Deine Wahrheit. Deine Entscheidung.', 'Your Truth. Your choice.')],
];
const cardName = (key, full = false) => key.startsWith('viewer_') ? viewerScenes().find(scene => scene[0] === key)?.[1] || key : /^truth_p\d_\d+$/.test(key)
  ? t(`Wahrheit ${key.split('_').at(-1)}`, `Truth ${key.split('_').at(-1)}`)
  : DemoLanguage.name(key, (full ? artNames : names)[key], full);
const image = (key, className = '', alt = cardName(key, true) || '') => `<img src="${window.BimBrowser.art(DemoLanguage.art(key))}" data-artwork="${escape(key)}" class="${className}" alt="${escape(alt)}">`;
const button = (action, label, cls = 'confirm', extra = '') => `<button type="button" class="${cls}" data-action="${action}" ${extra}>${label}</button>`;
const arrowIcon = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>';
const accessibilityIcon = document.querySelector('.accessibility-control .icon').outerHTML;
const cardType = key => ({
  song:t('Segen','Blessing'), song_again:t('Segen','Blessing'),
  ash:t('Reliquie','Relic'), skull:t('Reliquie','Relic'), enrico:t('Aufklärer','Enlightener'),
  army:t('Heiliges Heer','Holy Army'), grenade:t('Heilige Handgranate','Holy Hand Grenade'), yak:t('Phänomen','Phenomenon'), squirrels:t('Phänomen','Phenomenon'), earthquake:t('Phänomen','Phenomenon'), tornado:t('Phänomen','Phenomenon'),
  head:t('Kopf','Head'), chest:t('Brust','Chest'), legs:t('Beine','Legs'),
  frauke:t('Heiliges Heer','Holy Host'), henk:t('Aufklärer','Enlightener'),
})[key] || (/^truth_p\d_\d+$/.test(key) ? t('Wahrheit','Truth') : '');
function readableCard(key, detail = null) {
  const c = detail || state?.match?.hand.find(item => item.art === key) || state?.match?.card_details?.[key];
  const rules = {
    song:t('Taufe 3 Gläubige. Mit Chaos-Gesinnung: 4.', 'Baptize 3 believers. With Chaos alignment: 4.'),
    song_again:t('Taufe 3 Gläubige. Mit Zorn-Gesinnung: 4.', 'Baptize 3 believers. With Wrath alignment: 4.'),
    ash:t('Keine Opferkosten für Heiliges Heer.', 'No sacrifice costs for Holy Army cards.'),
    skull:t('Immer wenn du einen Segen spielst: Taufe 2 zusätzliche Gläubige.', 'Whenever you play a Blessing: baptize 2 additional believers.'),
    enrico:t('Keine neuen Reliquien an diesem Göttertableau. Bereits angelegte bleiben wirksam.', 'No new Relics on this god tableau. Relics already placed remain active.'),
    army:t('0 Opfer: Die Unberührte oder Henk ablegen. Oder 4 Opfer: Einen beliebigen Aufklärer ablegen.', '0 sacrifices: discard the Untouched or Henk. Or 4 sacrifices: discard any Enlightener.'),
    grenade:t('Je nach Ladung müssen Mitgötter deiner Wahl insgesamt 3, 5 oder 8 Gläubige opfern.', 'Depending on the charge, fellow gods of your choice sacrifice a total of 3, 5 or 8 believers.'),
    yak:t('Ein Mitgott setzt seinen nächsten Zug aus, darf aber am Stechen teilnehmen. Danach diese Karte ablegen.', 'One fellow god skips their next turn but may still join the contest. Discard this card afterwards.'),
    squirrels:t('Falls möglich, 1–2 Missionare eines Mitgottes in deinen Missionars-Tempel versetzen. Danach diese Karte ablegen.', 'If possible, move 1–2 missionaries from a fellow god into your missionary temple. Discard this card afterwards.'),
    earthquake:t('Eine Reliquie eines Mitgottes zerstören oder ein Gebot zerschmettern. Danach diese Karte ablegen.', 'Destroy one fellow god’s Relic or shatter one Commandment. Discard this card afterwards.'),
    tornado:t('Alle Mitgötter werfen ihre Hand ab und ziehen auf 3 Karten nach. Danach diese Karte ablegen.', 'All fellow gods discard their hands and draw back up to 3 cards. Discard this card afterwards.'),
    head:t('Walter · Chaos · Kopfbedeckung.', 'Walter · Chaos · Headwear.'),
    chest:t('Der zweifelnde Bestimmer · Chaos · Brusthaare.', 'The doubtful determiner · Chaos · Chest hair.'),
    legs:t('Mit Hausstauballergie · Chaos · Socken.', 'With a dust allergy · Chaos · Socks.'),
    henk:t('Eine gespeicherte Phänomen-Macht auslösen kostet 3 Opfer.', 'Unleashing a stored Phenomenon power costs 3 sacrifices.'),
    frauke:t('0 Opfer: Den Kartographen oder die Hellfühlige ablegen. Oder 4 Opfer: Einen beliebigen Aufklärer ablegen.', '0 sacrifices: discard the Cartographer or the Clairsentient. Or 4 sacrifices: discard any Enlightener.'),
  };
  const truth = c?.truth_value ?? (/^truth_p\d_\d+$/.test(key) ? Number(key.split('_').at(-1)) : null);
  const effect = truth !== null ? t(`Gedruckter Wahrheitswert: ${truth}.`, `Printed Truth value: ${truth}.`) : rules[key];
  const cost = c?.cost_believers ?? (['ash','skull','enrico','henk'].includes(key) ? 2 : null);
  return `<div class="readable-card">${effect ? `<p>${escape(effect)}</p>` : ''}<dl>${cost !== null ? `<div><dt>${t('Anlegekosten','Placement cost')}</dt><dd>${cost} ${t('Gläubige','believers')}</dd></div>` : ''}${c?.bid_value !== undefined ? `<div><dt>${t('Aktueller Gebotswert','Current bid value')}</dt><dd>${c.bid_value}</dd></div>` : ''}</dl></div>`;
}
const card = (key, cls = '') => `<button type="button" class="card-art ${cls}" data-art="${key}" title="${escape(t('Karte vergrößern', 'Enlarge card'))}" aria-label="${escape(t(`${cardType(key)}: ${cardName(key, true)} vergrößern`, `Enlarge ${cardType(key)}: ${cardName(key, true)}`))}"><span class="card-picture">${image(key)}<span class="magnify" aria-hidden="true">${arrowIcon}</span></span><span class="card-access-label" aria-hidden="true"><strong>${escape(cardType(key))}</strong><span>${escape(cardName(key))}</span></span></button>`;
const playerName = player => player.id === 'p1' ? t('Du', 'You') : player.name;

function tokens(count, cls = '', previous = count) {
  const animate = animateBelievers && document.documentElement.dataset.motion === 'full';
  return `<div class="tokens ${cls}" role="img" aria-label="${count} ${t('Gläubige', 'believers')}">${Array.from({length: count}, (_, i) => `<img src="./art/believer.png" alt="" class="token token-${i % 4} ${i >= previous ? `gained-believer ${animate ? 'new-believer' : ''}` : ''}" ${i >= previous ? `style="--arrival-delay:${200 + (i - previous) * 180}ms"` : ''}>`).join('')}</div>`;
}

function stopBelieverAnimation() {
  document.querySelectorAll('.new-believer,.flock-gaining,.count-gaining').forEach(node => {
    node.classList.remove('new-believer', 'flock-gaining', 'count-gaining');
  });
}

function stopContestAnimation() {
  document.querySelectorAll('.bid-landing,.bid-revealing,.opponent-playing').forEach(node => {
    node.classList.remove('bid-landing', 'bid-revealing', 'opponent-playing');
  });
}

app.addEventListener('animationend', event => {
  const cls = {baptism:'new-believer', 'flock-gain':'flock-gaining', 'flock-count':'count-gaining'}[event.animationName];
  if (cls) event.target.classList.remove(cls);
  const bidClass = {'bid-land':'bid-landing', 'bid-reveal':'bid-revealing', 'opponent-play':'opponent-playing'}[event.animationName];
  if (bidClass) event.target.classList.remove(bidClass);
});

function progress() {
  const labels = t(['Segen', 'Reliquie', 'Aufklärer', 'Heer', 'Granate', 'Körper'], ['Blessing', 'Relic', 'Enlightener', 'Army', 'Grenade', 'Body']);
  return `<ol class="progress" aria-label="${t('Spielabschnitte', 'Game chapters')}">${labels.map((label, i) => `<li class="${state.chapter > i + 1 ? 'complete' : ''} ${state.chapter === i + 1 ? 'current' : ''}" ${state.chapter === i + 1 ? 'aria-current="step"' : ''}><span aria-hidden="true">${state.chapter > i + 1 ? '✓' : i + 1}</span>${label}<small class="color-assist-state" aria-hidden="true">${state.chapter > i + 1 ? t('Fertig','Complete') : state.chapter === i + 1 ? t('Aktuell','Current') : t('Danach','Next')}</small>${state.chapter > i + 1 ? `<span class="visually-hidden">, ${t('abgeschlossen', 'completed')}</span>` : ''}</li>`).join('')}</ol>`;
}

function board() {
  const own = state.players[0];
  const gained = Math.max(0, own.believers - (previousBelievers.p1 ?? own.believers));
  const animate = gained && animateBelievers && document.documentElement.dataset.motion === 'full';
  const tableau = state.tableau.filter(key => !['head', 'chest', 'legs'].includes(key));
  return `<aside class="board" aria-label="${t('Spielzustand', 'Game state')}"><div class="herd-heading"><h2>${t('Deine Herde', 'Your flock')}</h2><strong class="believer-count ${animate ? 'count-gaining' : ''}">${own.believers}</strong><div class="flock-change ${animate ? 'flock-gaining' : ''}">${gained ? `<strong>+${gained}</strong><span>${t('neue Gläubige', 'new believers')}</span>` : ''}</div></div>${tokens(own.believers, '', previousBelievers.p1 ?? own.believers)}<div class="turn-meta"><span>${t('Runde', 'Round')} ${state.round}</span><span>${state.stage === 'contest' || state.score ? t('Phänomen-Stechen', 'Phenomenon contest') : `${state.actions} ${state.actions === 1 ? t('Aktion', 'action') : t('Aktionen', 'actions')}`}</span></div>${tableau.length ? `<div class="tableau-strip">${tableau.map(key => `<div>${card(key)}<span>${escape(cardName(key))}</span></div>`).join('')}</div>` : `<div class="tableau-empty">${state.body_count ? `${state.body_count} ${t('Körperteile manifestiert', 'body parts manifested')}` : t('Dein Göttertableau', 'Your god tableau')}</div>`}<div class="opponents">${state.players.slice(1).map(p => `<div><div class="opponent-name">${escape(playerName(p))}<strong>${p.believers}</strong></div>${tokens(p.believers, 'small', previousBelievers[p.id] ?? p.believers)}${state.stage === 'contest' ? `<p>${t('Brust manifestiert', 'Chest manifested')} · ${p.bid_count} ${p.bid_count === 1 ? t('verdeckte Karte', 'face-down card') : t('verdeckte Karten', 'face-down cards')}${p.passed ? t(' · gepasst', ' · passed') : ''}</p>` : ''}</div>`).join('')}</div></aside>`;
}

function controls() {
  switch (state.stage) {
    case 'song': return `<div class="effect">+3 <span>${t('Gläubige', 'believers')}</span></div>${button('play_song', t('Loblied spielen', 'Play Chant'))}`;
    case 'ash': return `<div class="cost">${t('2 Gläubige zum Anlegen', '2 believers to place')}</div>${button('play_ash', t('Roswitha anlegen', 'Place Roswitha'))}`;
    case 'arrival': return `<p class="scene-note">${t('Ein vorbereiteter Mitgott-Zug.', 'A prepared fellow-god turn.')}</p>${button('opponent', t('Mitgott ist am Zug', 'Let your fellow god play'))}`;
    case 'blocked': return `${button('try_skull', t('Schädel anlegen', 'Place the skull'), 'next')}<p class="hint">${t('Enrico liegt jetzt an deinem Tableau.', 'Enrico is now on your tableau.')}</p>`;
    case 'army': return `<div class="effect"><s>4</s> 0 <span>${t('Opferkosten', 'sacrifice cost')}</span></div>${button('play_army', t('Enrico entfernen', 'Remove Enrico'))}`;
    case 'skull': return `<div class="cost">${t('2 Gläubige · ersetzt Roswitha', '2 believers · replaces Roswitha')}</div>${button('play_skull', t('Schädel anlegen', 'Place the skull'))}`;
    case 'boost': return `<p class="scene-note">${t('Vorbereiteter Folgezug', 'Prepared next turn')}</p>${button('play_boost', t('Loblied spielen', 'Play Chant'))}`;
    case 'combo_done': return `<div class="effect">3 + 2 <span>${t('Gläubige', 'believers')}</span></div>${button('next', `<span class="grenade-entry-art" aria-hidden="true">${image('grenade', '', '')}</span><span>${t('Heilige Handgranate!', 'Holy Hand Grenade!')}</span>`, 'next grenade-entry')}`;
    case 'grenade_intro': return button('next', t('Granate ausprobieren', 'Try the grenade'), 'next');
    case 'grenade': return grenadeControls();
    case 'grenade_done': return button('next', t('Zum letzten Körperteil', 'On to the final body part'), 'next');
    case 'contest_intro': return button('next', t('Um den Yak bieten', 'Bid for the Yak'), 'next');
    case 'contest': return contestControls();
    case 'claim': return `${scores()}<div class="choice-stack">${button('manifest', t('Beine manifestieren', 'Manifest the legs'), 'next')}${button('keep_power', t('Nur die Macht behalten', 'Keep only the power'), 'back')}</div>`;
    case 'lost': return `${scores()}${button('retry', t('Wettstreit erneut spielen', 'Play the contest again'), 'next')}`;
    case 'finale': return `<div class="effect">+3 <span>${t('Gläubige zur Offenbarung', 'believers for Revelation')}</span></div><p>${t('Die Götterdämmerung beginnt. Die Partie geht in ihre Schlussphase.', 'Twilight of the Gods begins. The game enters its final phase.')}</p>${button('overview', t('Das ganze Spiel entdecken', 'Discover the whole game'), 'next')}<button type="button" class="back" data-tech>${t('Technik ansehen', 'View the technology')}</button>`;
    case 'power_done': return `${button('overview', t('Das ganze Spiel entdecken', 'Discover the whole game'), 'next')}<button type="button" class="back" data-tech>${t('Technik ansehen', 'View the technology')}</button>`;
    default: return '';
  }
}

function grenadeControls() {
  const level = state.grenade.level;
  const targetChoice = `<fieldset class="target-choice"><legend>${t('Wen trifft die Rache?', 'Who faces your revenge?')}</legend><select id="target" aria-label="${t('Ziel der Granate', 'Grenade target')}">${state.players.slice(1).map(p => `<option value="${p.id}" ${target === p.id ? 'selected' : ''}>${escape(playerName(p))}</option>`).join('')}<option value="split" ${target === 'split' ? 'selected' : ''}>${t('Beide, gleichmäßig verteilt', 'Both, split evenly')}</option></select></fieldset>`;
  if (state.grenade.pending) return `${targetChoice}<div class="effect">${level === 1 ? 3 : 5}<span>${t('Opfer bei deinen Mitgöttern', 'sacrifices among your fellow gods')}</span></div>${button('ignite', t('Jetzt zünden', 'Detonate now'))}${button('wait', t('Weiterladen', 'Keep charging'), 'back')}<p class="hint">${level === 2 ? t('Für die nächste Ladung sind erst deine Mitgötter am Zug.', 'Your fellow gods take their turns before the next charge.') : t('Eine weitere Ladung kostet deine zweite Aktion.', 'Another charge costs your second action.')}</p>`;
  if (!state.actions) return `<p>${t('Beide Aktionen sind verbraucht. Vor der dritten Ladung kommen deine Mitgötter dran.', 'Both actions are spent. Your fellow gods take their turns before the third charge.')}</p>${button('next_turn', t('Mitgötter spielen lassen', 'Let your fellow gods play'), 'next')}`;
  return `${level === 2 ? targetChoice : ''}<div class="charge-track">${[1,2,3].map(n => `<span class="${level >= n ? 'charged' : ''}">${n}<small>${({1:3,2:5,3:8})[n]} ${t('Opfer', 'sacrifices')}</small><small class="color-assist-state">${level >= n ? t('Geladen','Charged') : t('Nicht geladen','Uncharged')}</small></span>`).join('')}</div><p class="cost">${t('1 Aktion + 1 Gläubiger', '1 action + 1 believer')}${level === 2 ? t(' · zündet verpflichtend', ' · must detonate') : ''}</p>${button('charge', level === 2 ? t('Dritte Ladung und zünden', 'Third charge and detonate') : t('Granate aufladen', 'Charge the grenade'))}`;
}

function contestControls() {
  // Keep the existing preview usable while its older Python process is still running.
  const live = state.contest_turn !== undefined;
  const cards = state.truth_cards || state.truth.map(value => ({value}));
  const passed = state.players[0].passed;
  const ownTurn = live ? state.contest_turn === 'p1' : true;
  const active = state.players.find(p => p.id === state.contest_turn);
  const status = passed ? t('Du hast endgültig gepasst.', 'You have passed for good.')
    : ownTurn ? t('Dein Gebot', 'Your bid') : t(`${playerName(active)} ist am Zug.`, `${playerName(active)} is taking their turn.`);
  return `<p class="bid-turn" id="bid-turn" tabindex="-1">${status}</p><div class="truth-hand ${live ? 'original-truth-hand' : ''}" role="group" aria-label="${t('Deine Wahrheitskarten', 'Your Truth cards')}">${cards.map(({value, art}) => button('bid', `${art ? image(art, '', '') : `<span>${value}</span>`}<small>${value} ${t('Wahrheit', 'Truth')}</small>`, `truth-card ${live ? 'original-truth' : ''}`, `data-value="${value}" title="${t(`Wahrheit ${value} bieten`, `Bid Truth ${value}`)}" aria-label="${t(`Wahrheit ${value} bieten`, `Bid Truth ${value}`)}" ${live && !state.can_bid ? 'disabled' : ''}`)).join('')}</div>${!cards.length ? `<p class="hint">${t('Keine Wahrheitskarte mehr auf der Hand.', 'No Truth cards left in your hand.')}</p>` : ''}${button('pass', t('Endgültig passen', 'Pass for good'), 'back', live && !state.can_pass ? 'disabled' : '')}<p class="hint">${live && ownTurn && !state.can_pass ? t('Du eröffnest: Lege zuerst eine Karte.', 'You open the contest: play one card first.') : t('Eine Karte pro Zug. Ein Pass ist endgültig. Die Werte bleiben bis zum Aufdecken geheim.', 'One card per turn. A pass is final. Values stay hidden until the reveal.')}</p>${live && !ownTurn ? button('advance_opponent', t('Gegnerzug fortsetzen', "Continue the opponent's turn"), 'back', `data-opponent-retry ${errorBox.hidden ? 'hidden' : ''}`) : ''}`;
}

function contestTable(motion) {
  const revealed = !!state.score;
  return `<div class="contest-table" role="group" aria-label="${t('Gebote im Stechen', 'Contest bids')}">${state.players.map(p => {
    const art = p.id === 'p1' ? 'head' : p.id === 'p2' ? 'frauke' : 'henk';
    const active = p.id === state.contest_turn;
    const played = motion?.player === p.id;
    const keys = revealed ? state.bids.filter(b => b.player === p.id).flatMap(b => b.art) : Array(p.bid_count).fill('truth_back');
    const label = revealed ? t(`${state.score[p.id] || 0} Wahrheit`, `${state.score[p.id] || 0} Truth`)
      : p.passed ? t('Endgültig gepasst', 'Passed for good')
      : active ? t('Am Zug', 'Taking a turn') : t('Wartet', 'Waiting');
    return `<section class="bid-seat ${active ? 'active-seat' : ''} ${state.winner === p.id ? 'winning-seat' : ''}" aria-labelledby="bid-name-${p.id}"><div class="bid-portrait ${p.id === 'p1' ? 'own-portrait' : ''} ${played ? 'opponent-playing' : ''}" aria-hidden="true">${image(art, '', '')}</div><h2 id="bid-name-${p.id}">${escape(playerName(p))}</h2><p class="bid-seat-status">${label}${revealed && state.winner === p.id ? ` · ${t('Gewonnen', 'Winner')}` : ''}</p><div class="bid-lane ${revealed ? 'revealed-lane' : ''}" style="--bid-count:${keys.length}" role="img" aria-label="${escape(revealed ? `${playerName(p)}: ${state.bids.filter(b => b.player === p.id).flatMap(b => b.values).join(' + ') || 0}` : `${playerName(p)}: ${p.bid_count} ${t('verdeckte Karten', 'face-down cards')}`)}">${keys.map((key, i) => `<img src="${window.BimBrowser.art(DemoLanguage.art(key))}" alt="" style="--bid-index:${i}" class="bid-card ${revealed && motion ? 'bid-revealing' : played && motion.kind === 'bid' && i === keys.length - 1 ? 'bid-landing' : ''}">`).join('')}${!keys.length ? `<span aria-hidden="true">—</span>` : ''}</div>${p.id === 'p1' && !revealed ? `<p class="own-bid-total">${t('Deine gebotene Wahrheit', 'Your committed Truth')}: <strong>${state.own_bid_total}</strong></p>` : ''}${revealed ? `<p class="bid-values">${state.bids.filter(b => b.player === p.id).flatMap(b => b.values).join(' + ') || 0}</p>` : ''}</section>`;
  }).join('')}</div>`;
}

function contestScene(motion) {
  const [title, prompt] = DemoLanguage.scene(state);
  return `${progress()}<div class="game-layout contest-layout"><section class="contest-scene" aria-labelledby="stage-title"><div class="contest-heading"><div class="contest-prize">${card('yak', 'landscape')}</div><div><h1 id="stage-title" tabindex="-1">${escape(title)}</h1><p class="prompt">${escape(prompt)}</p></div></div>${contestTable(motion)}${state.feedback ? `<p class="feedback">${escape(DemoLanguage.feedback(state))}</p>` : ''}<div class="controls contest-controls ${state.stage === 'contest' ? 'bidding-controls' : ''}">${controls()}</div></section>${board()}</div>`;
}

function scores() {
  return `<div class="scores" role="group" aria-label="${t('Aufgedeckte Gebote', 'Revealed bids')}">${state.players.map(p => `<div class="${state.winner === p.id ? 'winner' : ''}"><strong>${escape(playerName(p))}</strong><span>${state.score?.[p.id] ?? 0}</span><small>${state.bids.filter(b => b.player === p.id).flatMap(b => b.values).join(' + ') || t('gepasst', 'passed')}</small>${state.winner === p.id ? `<small class="score-result">${t('Gewonnen', 'Winner')}</small>` : ''}</div>`).join('')}</div>${state.tie_breaker === 'last_card_contributor' ? `<p class="hint">${t('Gleichstand: Die letzte beigetragene Karte entscheidet.', 'Tie: the last contributed card decides.')}</p>` : ''}`;
}

function artwork() {
  switch (state.stage) {
    case 'song': return card('song');
    case 'ash': return card('ash');
    case 'arrival': return `<div class="visitor">${image('missionary', '', t('Missionar', 'Missionary'))}</div>`;
    case 'blocked': return `<div class="blocked-pair">${card('enrico')}${card('skull')}<span class="blocked-label">${t('Neue Reliquie gesperrt', 'New relic blocked')}</span></div>`;
    case 'army': return `<div class="army-context" role="group" aria-label="${t('Irmgard entfernt Enrico aus deinem Tableau. Roswitha erspart die Opferkosten.', 'Irma removes Enrico from your tableau. Roswitha waives the sacrifice cost.')}"><figure><figcaption>${t('Dein Heiliges Heer', 'Your Holy Army')}</figcaption>${card('army')}<p>${t('Roswitha: 0 Opfer', 'Roswitha: 0 sacrifices')}</p></figure><span class="army-direction" aria-hidden="true">&#8594;</span><figure class="army-target"><figcaption>${t('Ziel: Enrico', 'Target: Enrico')}</figcaption>${card('enrico')}<p>${t('Auf deinem Tableau', 'On your tableau')}</p></figure></div>`;
    case 'skull': return card('skull');
    case 'boost': return card('song_again');
    case 'combo_done': return `<div class="combo-pair">${card('skull')}${card('song_again')}</div>`;
    case 'grenade_intro': case 'grenade': case 'grenade_done': return `<div class="grenade-art">${card('grenade', 'landscape')}<div class="grenade-tokens">${tokens(state.grenade.level)}</div></div>`;
    case 'contest_intro': return body(false);
    case 'finale': return body(true);
    case 'contest': case 'claim': case 'lost': case 'power_done': return card('yak', 'landscape');
    default: return '';
  }
}

function body(complete) {
  return `<div class="god-body" role="group" aria-label="${complete ? escape(DemoLanguage.scene(state)[1]) : t('Walter mit Kopf und Brust; Beine fehlen', 'Walter with head and chest; legs missing')}">${image('head')}${image('chest')}${complete ? image('legs') : `<div class="missing-part"><span>?</span><p>${t('Beine fehlen', 'Legs missing')}</p></div>`}</div>`;
}

function briefing() {
  if (miniBriefing && state.mini_available) return quickMiniBriefing();
  if (state.mini_available) return scrollBriefing();
  const principles = [
    [tokens(6), t('Sammle Gläubige', 'Gather believers'),
      t('Gläubige sind deine Macht. Gewinne neue und setze andere für starke Karten ein.',
        'Believers are your power. Gain more, and spend some on powerful cards.')],
    [image('missionary', '', ''), t('Überliste deine Mitgötter', 'Outwit your fellow gods'),
      t('Zwei Mitgötter teilen dein Himmelreich. Reliquien helfen deinen Plänen; Aufklärer und Handgranaten können sie durchkreuzen.',
        'Two fellow gods share your realm. Relics help your plans; Enlighteners and Holy Hand Grenades can disrupt them.')],
    [image('head', '', ''), t('Vervollständige deinen Gott', 'Complete your god'),
      t('Gewinne Phänomene und manifestiere Kopf, Brust und Beine. In der Schlusswertung stehen vollständige Götter vorne; danach entscheiden die Gläubigen.',
        'Win phenomena and manifest a head, chest and legs. At final scoring, complete gods rank first; believers then break ties.')],
  ];
  return `<section class="briefing" aria-labelledby="stage-title"><div class="briefing-heading"><h1 id="stage-title" tabindex="-1">${t('Ein Gott im Werden.', 'A god in the making.')}</h1><p>${t('Du bist ein Gott. Eine kleine Herde glaubt an dich. Zwei andere Götter hätten das lieber anders.', "You're a god. A small flock believes in you. Two other gods would rather they didn't.")}</p></div><ol class="briefing-principles">${principles.map(([art, title, text]) => `<li><div class="briefing-art" aria-hidden="true">${art}</div><h2>${title}</h2><p>${text}</p></li>`).join('')}</ol><div class="briefing-start"><div><h2>${t('Dein erstes Wunder', 'Your first miracle')}</h2><p>${t('Du beginnst mit sechs Gläubigen. Ein Segen bringt drei weitere zu dir.', 'You begin with six believers. A blessing brings three more to your flock.')}</p><small>${t('Ein paar vorbereitete Momente aus einer größeren Partie.', 'A few prepared moments from a larger match.')}</small></div><div class="briefing-actions">${button('start', t('Das erste Wunder wirken', 'Perform your first miracle'))}<button type="button" class="back" data-briefing="close">${t('Zurück', 'Back')}</button></div></div></section>`;
}

function quickMiniBriefing() {
  const rivals = `<div class="quick-rivals">${['frauke','henk'].map(key => `<figure>${image(key, '', '')}<figcaption>${escape(cardName(key,true))}</figcaption></figure>`).join('')}</div>`;
  const trinity = `<div class="quick-trinity"><span class="story-halo" aria-hidden="true"></span><div class="quick-god">${['head','chest','legs'].map(key => `<div class="quick-god-part quick-god-${key}">${image(key, '', '')}</div>`).join('')}</div><span class="quick-missing-label">${t('Die letzte Manifestation', 'The final manifestation')}</span></div>`;
  const principles = [
    ['flock', tokens(6), t('Deine Herde', 'Your flock'), t('Du startest mit sechs Gläubigen. Als Chaos-Gott gewinnt Walter durch das Loblied vier weitere.', 'Start with six believers. As a Chaos god, Walter gains four more with Chant.')],
    ['rivals', rivals, t('Du bist nicht allein.', 'You are not alone.'), t('Frauke und Henk haben ihre eigenen Pläne. Spiele deine Karten, besetze Tempel und überbiete sie.', 'Frauke and Henk have plans of their own. Play your cards, fill your temples and outbid them.')],
    ['trinity', trinity, t('Vollende deine Dreifaltigkeit.', 'Complete your Trinity.'), t('Kopf und Brust sind bereits manifestiert. Gewinne ein Phänomen-Stechen und manifestiere die fehlenden Beine, um Walter zu vervollständigen.', 'His head and chest are already manifested. Win a phenomenon contest and manifest the missing legs to complete Walter.')],
  ];
  return `<section class="briefing mini-briefing quick-mini-briefing" aria-labelledby="stage-title"><div class="briefing-heading"><h1 id="stage-title" tabindex="-1">${t('Dein Himmelreich wartet.', 'Your Heavenly Realm awaits.')}</h1><p>${t('Du bist Walter. Frauke und Henk spielen gegen dich.', 'You are Walter. Frauke and Henk are your rivals.')}</p></div><ol class="briefing-principles">${principles.map(([key,art,title,text]) => `<li class="quick-principle quick-principle-${key}"><div class="briefing-art" aria-hidden="true">${art}</div><h2>${title}</h2><p>${text}</p></li>`).join('')}</ol><div class="briefing-start"><div><p>${t('Vorbereitetes Mittelspiel · kleinere Originalstapel · echte Regeln.', 'Prepared mid-game start · smaller original decks · real rules.')}</p></div><div class="briefing-actions">${button('start_mini', `<span class="quick-command-seal" aria-hidden="true"><span class="story-halo"></span>${image('head', '', '')}</span><span>${t('Mini-Partie beginnen', 'Begin the mini-match')}</span>${arrowIcon}`, 'next embark quick-embark')}<button type="button" class="back" data-briefing="close">${t('Zurück', 'Back')}</button></div></div></section>`;
}

function scrollBriefing() {
  const chapters = [
    ['flock', t('Gläubige', 'Believers')],
    ['rivals', t('Mitgötter', 'Fellow gods')],
    ['body', t('Dreifaltigkeit', 'Trinity')],
  ];
  const halo = '<span class="story-halo" aria-hidden="true"></span>';
  const bodyParts = ['head','chest','legs'].map(key => `<button type="button" class="story-body-part story-${key}" data-art="${key}" aria-label="${escape(t(`${cardName(key)} vergrößern`, `Enlarge ${cardName(key)}`))}">${image(key)}</button>`).join('');
  return `<section class="briefing mini-briefing scroll-briefing" aria-labelledby="stage-title">
    <header class="story-opening" id="story-opening">
      <p class="briefing-eyebrow">${t('Du bist Walter.', 'You are Walter.')}</p>
      <div class="story-coronation" aria-hidden="true">${halo}${image('head','story-walter','')}</div>
      <h1 id="stage-title" tabindex="-1">${t('Erobere deinen Platz im Himmelreich.', 'Claim your place in the heavens.')}</h1>
      <p>${t('Du spielst einen Gott. Eine kleine Herde glaubt an dich. Frauke die Foltermagd und Henk der Hetzer hätten das lieber anders.', "You're a god. A small flock believes in you. Frida the Flayer and Henk the Heckler would rather they didn't.")}</p>
      <button type="button" class="story-skip" data-briefing="mini">${image('head','', '')}<span>${t('Direkt zur Mini-Partie', 'Skip to mini-match')}</span>${arrowIcon}</button>
      <div class="story-opening-roles" aria-hidden="true">${image('monk','','')}${image('missionary','','')}${image('nun','','')}</div>
      <a class="story-scroll-link" href="#story-flock">${t('Entdecke dein Himmelreich', 'Discover your realm')}${arrowIcon}</a>
    </header>
    <nav class="story-nav" aria-label="${t('Einstiegskapitel', 'Introduction chapters')}">
      ${chapters.map(([key,label],i) => `<a href="#story-${key}" data-story-link="${key}"><span aria-hidden="true">0${i+1}</span><span>${label}</span></a>`).join('')}
      <a href="#story-app" data-story-link="viewer">${t('Viewer', 'Viewer')}</a>
      <a href="#story-board" data-story-link="board">${t('Brettspiel', 'Board game')}</a>
      <a class="story-play-link" href="#story-play">${t('Spielen', 'Play')}${arrowIcon}</a>
      <a class="story-access" href="./accessibility.html" data-accessibility title="${t('Über Barrierefreiheit', 'About Accessibility')}" aria-label="${t('Über Barrierefreiheit', 'About Accessibility')}">${accessibilityIcon}</a>
    </nav>
    <section class="story-chapter story-flock" id="story-flock" data-story-chapter="flock" aria-labelledby="story-flock-title">
      <div class="story-viewport">
        <div class="story-copy"><p class="story-kicker">01 · ${t('Deine Herde', 'Your flock')}</p><h2 id="story-flock-title">${t('Deine Macht beginnt mit Glauben.', 'Your power starts with belief.')}</h2><p>${t('Du beginnst mit sechs Gläubigen. Das Loblied tauft drei weitere. Eine größere Herde bringt mehr Möglichkeiten; für starke Karten opferst du manchmal einen Teil davon.', 'You begin with six believers. Chant baptizes three more. A larger flock brings more possibilities; powerful cards sometimes cost you a few of them.')}</p><p class="story-fact">${t('Ein Segen. Drei neue Gläubige.', 'One blessing. Three new believers.')}</p></div>
        <div class="story-art story-flock-art">
          ${card('song','story-card')}
          <div class="story-believers" aria-hidden="true">${Array.from({length:9},(_,i) => `<img src="./art/believer.png" alt="" class="story-believer ${i>5?'story-new-believer':''}" style="--believer-index:${i%3}">`).join('')}</div>
          <div class="story-monk-scene" aria-hidden="true">${halo}${image('monk','story-monk','')}</div>
          <div class="story-flock-total" aria-hidden="true"><strong data-story-count>9</strong><span>${t('Gläubige', 'believers')}</span></div>
        </div>
      </div>
    </section>
    <section class="story-chapter story-rivals" id="story-rivals" data-story-chapter="rivals" aria-labelledby="story-rivals-title">
      <div class="story-viewport">
        <div class="story-copy"><p class="story-kicker">02 · ${t('Karten und Gegenpläne', 'Cards and counterplans')}</p><h2 id="story-rivals-title">${t('Ein guter Plan. Zwei Mitgötter.', 'One good plan. Two fellow gods.')}</h2><p>${t('Reliquien stärken deinen Plan. Enrico verhindert neue Reliquien, aber er schaltet Roswithas bereits liegende Asche nicht ab. Dein Heiliges Heer kann ihn entfernen.', 'Relics strengthen your plan. Enrico blocks new relics, but cannot switch off Roswitha’s ash once it is in place. Your Holy Host can remove him.')}</p><p class="story-fact">${t('Karten wirken zusammen. Nicht nur einzeln.', 'Cards work together. Not just alone.')}</p><div class="story-rival-names"><figure>${image('frauke','','')}<figcaption>${escape(cardName('frauke',true))}</figcaption></figure><figure>${image('henk','','')}<figcaption>${escape(cardName('henk',true))}</figcaption></figure></div></div>
        <div class="story-art story-card-fan">${halo}${card('ash','story-card story-ash')}${card('enrico','story-card story-enrico')}${card('army','story-card story-army')}</div>
      </div>
    </section>
    <section class="story-chapter story-body" id="story-body" data-story-chapter="body" aria-labelledby="story-body-title">
      <div class="story-viewport">
        <div class="story-copy"><p class="story-kicker">03 · ${t('Dein göttlicher Körper', 'Your divine body')}</p><h2 id="story-body-title">${t('Vom Kopf bis zur Gottheit.', 'From head to godhood.')}</h2><p>${t('Ein vollständiger Gott besteht aus Kopf, Brust und Beinen. Walter hat bereits Kopf und Brust. Gewinne Phänomen-Stechen mit deinen Wahrheitskarten und manifestiere die fehlenden Beine.', 'A complete god has a head, chest and legs. Walter already has a head and chest. Win phenomenon contests with your Truth cards and manifest the missing legs.')}</p><p class="story-fact">${t('In der Schlusswertung stehen vollständige Götter vorne. Danach entscheiden die Gläubigen.', 'At final scoring, complete gods rank first. Believers then break ties.')}</p></div>
        <div class="story-art story-body-art"><div class="story-god">${halo}${bodyParts}</div><p class="story-body-caption">${t('Dein Ziel: ein vollständiger Gott.', 'Your goal: a complete god.')}</p></div>
      </div>
    </section>
    <section class="story-ready" id="story-ready" aria-labelledby="story-ready-title">
      <div class="realm-gate" aria-hidden="true">${halo}${image('logo','','')}</div>
      <div class="story-ready-copy"><p class="story-kicker">${t('Das digitale Himmelreich', 'The digital realm')}</p><h2 id="story-ready-title">${t('Dein Himmelreich. Auf dem Bildschirm.', 'Your realm. On screen.')}</h2><div class="briefing-actions"><a class="embark realm-link" href="#story-app"><span>${t('Betritt dein Himmelreich', 'Enter your heavenly realm')}</span>${arrowIcon}</a></div></div>
    </section>
    ${viewerShowcase()}
    ${boardShowcase()}
  </section>`;
}

function viewerShowcase() {
  const selected = viewerScenes().find(scene => scene[0] === viewerSceneKey);
  return `<section class="realm-showcase viewer-showcase" id="story-app" data-story-stop="viewer" aria-labelledby="viewer-title" tabindex="-1">
    <header class="realm-heading"><span class="story-halo realm-heading-halo" aria-hidden="true"></span><p class="story-kicker">${t('Das digitale Himmelreich', 'The digital realm')}</p><h2 id="viewer-title">${t('Karten werden Entscheidungen.', 'Cards become choices.')}</h2></header>
    <fieldset class="viewer-scenes"><legend class="visually-hidden">${t('Viewer-Ansicht', 'Viewer scene')}</legend>${viewerScenes().map(([key,title]) => `<label><input type="radio" name="viewer-scene" value="${key}" ${key === viewerSceneKey ? 'checked' : ''}><span>${title}</span></label>`).join('')}</fieldset>
    <figure class="realm-gallery"><button type="button" class="viewer-capture" data-art="${viewerSceneKey}" aria-label="${escape(t(`${selected[1]} vergrößern`, `Enlarge ${selected[1]}`))}">${image(viewerSceneKey,'',selected[2])}<span class="viewer-zoom" aria-hidden="true">+</span></button><figcaption>${t('Original-Viewer · 1.2-Vorbereitung', 'Actual Viewer · Version 1.2 preparation')}</figcaption></figure>
    <div class="realm-next"><a class="embark realm-link" href="#story-board"><span>${t('Entdecke das Brettspiel', 'Discover the board game')}</span>${arrowIcon}</a></div>
  </section>`;
}

function boardShowcase() {
  const figures = ['believer','monk','believer','missionary','believer','nun'];
  return `<section class="realm-showcase board-showcase" id="story-board" data-story-stop="board" aria-labelledby="board-title" tabindex="-1">
    <header class="realm-heading"><span class="story-halo realm-heading-halo" aria-hidden="true"></span><p class="story-kicker">${t('Vom Bildschirm an den Spieltisch', 'From screen to table')}</p><h2 id="board-title">${t('Ein Himmelreich. Ein gemeinsamer Tisch.', 'One realm. One shared table.')}</h2></header>
    <div class="realm-table" data-board-build><div class="realm-table-stage"><div class="realm-playerboards">${[['Walter',1],[cardName('frauke',true),0],[cardName('henk',true),2]].map(([name,i]) => `<figure class="realm-playerboard realm-playerboard-${i}"><div class="original-tableau">${image('playerboard','original-board',t('Originales englisches Spielertableau','Original English player board'))}<div class="board-build-pieces" aria-hidden="true">${['head','chest','legs','ash','skull','enrico','monument'].map((key,n) => `<span class="board-build-piece build-${key}" data-build-order="${n + i}">${image(key,'','')}</span>`).join('')}${Array.from({length:8},(_,n) => `<span class="board-build-piece build-token token-${n}" data-build-order="${4+n}">${image(n < 5 ? 'monk' : 'missionary','','')}</span>`).join('')}</div></div><figcaption>${escape(name)}</figcaption></figure>`).join('')}</div>
    <div class="realm-meeples" aria-hidden="true">${Array.from({length:36},(_,i) => `<span class="board-build-piece" data-build-order="${Math.floor(i/4)+2}">${image(figures[i%figures.length],'realm-meeple','')}</span>`).join('')}</div><figure class="realm-middleboard">${image('middleboard','',t('Originales englisches Mittelbrett','Original English central board'))}<figcaption>${t('Das Mittelbrett verbindet alle Götter.', 'The central board connects every god.')}</figcaption></figure></div></div>
    <div class="realm-play" id="story-play" tabindex="-1"><div class="realm-play-copy"><p class="story-kicker">${t('Jetzt bist du dran.', 'Now it is your turn.')}</p><h2>${t('Aus einem Plan wird eine Partie.', 'A plan becomes a match.')}</h2><p>${t('Spiele deine Karten. Besetze Tempel. Biete gegen Frauke und Henk.', 'Play your cards. Fill your temples. Bid against Frauke and Henk.')}</p><small>${t('Illustrierter Aufbau. Vorbereitetes Mittelspiel · kleinere Originalstapel · echte Regeln.', 'Illustrated setup. Prepared mid-game start · smaller original decks · real rules.')}</small></div><div class="briefing-actions">${button('start_mini',`<span class="embark-halo" aria-hidden="true"></span><span>${t('Mini-Partie spielen', 'Play the mini-match')}</span>${arrowIcon}`,'next embark realm-play-command')}<button type="button" class="back" data-briefing="close">${t('Zurück','Back')}</button></div></div>
    <div class="briefing-tech"><button type="button" class="back" data-tech><span>${t('Unter der Oberfläche', 'Under the surface')}</span>${arrowIcon}</button></div>
  </section>`;
}

function setupBriefingScroll(snapshot) {
  const root = app.querySelector('.scroll-briefing');
  if (!root) return null;
  const chapters = [...root.querySelectorAll('[data-story-chapter]')];
  const stops = [...root.querySelectorAll('[data-story-stop]')];
  const anchors = [...root.querySelectorAll('.story-opening,[data-story-chapter],.story-ready,[data-story-stop]')];
  const navigation = root.querySelector('.story-nav');
  const opening = root.querySelector('.story-opening');
  let frame = null;
  let pendingPosition = null;
  let position = null;
  let readingPosition = snapshot || null;
  const clamp = value => Math.max(0,Math.min(1,value));
  const scale = () => navigation.getBoundingClientRect().width / Math.max(1, navigation.offsetWidth);
  const navigationHeight = () => getComputedStyle(navigation).position === 'sticky' ? navigation.getBoundingClientRect().height : 0;
  const inset = () => navigationHeight() + 12 * scale();
  function paint() {
    frame = null;
    const reduced = document.documentElement.dataset.motion === 'reduced';
    const viewport = innerHeight;
    const navHeight = navigationHeight();
    root.style.setProperty('--story-nav-height',`${navHeight / scale()}px`);
    const contentHeight = Math.max(...chapters.map(chapter => Math.max(chapter.querySelector('.story-copy').offsetHeight,chapter.querySelector('.story-art').offsetHeight))) * scale();
    const pinned = !reduced && root.clientWidth > 760 && viewport >= 560 && contentHeight + 80 <= viewport - navHeight;
    const layout = pinned ? 'pinned' : 'flow';
    const preserve = pendingPosition || (root.dataset.storyLayout && root.dataset.storyLayout !== layout ? position : null);
    pendingPosition = null;
    root.dataset.storyLayout = layout;
    if (preserve) restore(preserve);
    const openingRect = opening.getBoundingClientRect();
    opening.style.setProperty('--scene-progress',reduced ? 1 : clamp(-openingRect.top/Math.max(1,openingRect.height)).toFixed(4));
    let active = null;
    for (const chapter of chapters) {
      const rect = chapter.getBoundingClientRect();
      const travel = Math.max(1,rect.height-viewport+navHeight);
      const art = chapter.querySelector('.story-art');
      const progress = reduced ? 1 : clamp(pinned ? (navHeight-rect.top)/travel : (viewport*.85-art.getBoundingClientRect().top)/(viewport*.65));
      chapter.style.setProperty('--scene-progress',progress.toFixed(4));
      if (rect.top <= viewport*.45 && rect.bottom > viewport*.45) active = chapter.dataset.storyChapter;
      const count = chapter.querySelector('[data-story-count]');
      if (count) count.textContent = String(6+Math.round((art.matches(':focus-within') ? 1 : progress)*3));
    }
    for (const stop of stops) {
      const rect = stop.getBoundingClientRect();
      stop.style.setProperty('--scene-progress',reduced ? 1 : clamp((viewport*.85-rect.top)/(viewport*.65)).toFixed(4));
      if (rect.top <= viewport*.45 && rect.bottom > viewport*.45) active = stop.dataset.storyStop;
    }
    const build = root.querySelector('[data-board-build]');
    if (build) {
      const rect = build.getBoundingClientRect();
      const progress = reduced ? 1 : clamp((navHeight - rect.top) / Math.max(viewport*.65, rect.height - viewport*.35 + navHeight));
      build.querySelectorAll('[data-build-order]').forEach(piece => {
        const amount = reduced ? 1 : clamp(progress * 14 - Number(piece.dataset.buildOrder));
        piece.style.setProperty('--piece-progress', amount.toFixed(4));
      });
    }
    root.querySelectorAll('[data-story-link]').forEach(link => {
      if (link.dataset.storyLink === active) link.setAttribute('aria-current','location');
      else link.removeAttribute('aria-current');
    });
    position = capture();
    // Header/navigation controls can scroll the opening into view before changing pages or language.
    if (position.id !== 'story-opening' || !readingPosition) {
      readingPosition = position;
      updateAccessNavigation(position.id?.replace('story-', ''));
    }
  }
  function refresh(snapshot) {
    if (snapshot?.id || snapshot?.top === 0) pendingPosition = snapshot;
    if (frame === null) frame = requestAnimationFrame(paint);
  }
  function capture() {
    if (scrollY <= 1) return {top:0};
    const current = anchors.filter(node => node.getBoundingClientRect().top <= inset()+1).at(-1) || anchors[0];
    const rect = current.getBoundingClientRect();
    return {id:current.id, fraction:clamp((inset()-rect.top)/Math.max(1,rect.height))};
  }
  function restore(snapshot) {
    const node = snapshot.id ? document.getElementById(snapshot.id) : null;
    if (node) window.scrollTo({top:scrollY+node.getBoundingClientRect().top-inset()+snapshot.fraction*node.getBoundingClientRect().height,behavior:'instant'});
    else if (snapshot.top === 0) window.scrollTo({top:0,behavior:'instant'});
  }
  function resize() { refresh(position); }
  paint();
  if (snapshot) restore(snapshot);
  else window.scrollTo({top:0,behavior:'instant'});
  window.addEventListener('scroll',refresh,{passive:true});
  window.addEventListener('resize',resize);
  root.addEventListener('focusin',refresh);
  root.addEventListener('focusout',refresh);
  paint();
  return {refresh,capture,reading:() => readingPosition || capture(),destroy() {
    window.removeEventListener('scroll',refresh);
    window.removeEventListener('resize',resize);
    root.removeEventListener('focusin',refresh);
    root.removeEventListener('focusout',refresh);
    if (frame !== null) cancelAnimationFrame(frame);
  }};
}

function setBriefing(open, mini = false) {
  if (!state || busy || state.stage !== 'intro') return;
  introBriefing = open;
  miniBriefing = open && mini && state.mini_available;
  const url = new URL(location.href);
  url.hash = open ? (miniBriefing ? 'before-mini-match' : 'before-you-play') : '';
  history.replaceState(null, '', url);
  render();
}

function updateAccessNavigation(source = accessReturnChapter) {
  if (storyDestinations.includes(source)) accessReturnChapter = source;
  if (informationPage) {
    const chapter = new URLSearchParams(location.search).get('from');
    if (storyDestinations.includes(chapter)) accessReturnChapter = chapter;
  }
  for (const [path, selector] of [['/accessibility','a[data-accessibility]'],['/under-the-surface','a[data-tech]']]) {
    document.querySelectorAll(selector).forEach(link => {
      const url = new URL(path === '/accessibility' ? './accessibility.html' : './under-the-surface.html', window.BimBrowser.base);
      url.searchParams.set('lang', DemoLanguage.get());
      if (storyDestinations.includes(accessReturnChapter)) url.searchParams.set('from', accessReturnChapter);
      link.href = url.pathname + url.search;
    });
  }
  if (informationPage) {
    const source = new URLSearchParams(location.search).get('from');
    const url = new URL('./index.html', window.BimBrowser.base);
    url.searchParams.set('lang', DemoLanguage.get());
    if (storyDestinations.includes(source)) { url.searchParams.set('resume', source); url.hash = 'before-you-play'; }
    document.querySelectorAll('.access-return,.tech-return').forEach(link => { link.href = url.pathname + url.search + url.hash; });
  }
}

function overview() {
  const worlds = t([
    ['temple', 'Tempel und Figuren', 'Gesangsmönche taufen. Missionare gewinnen Gläubige von Mitgöttern. Kampfnonnen verstärken dein Gebot.'],
    ['monument', 'Monumente und Wahrheit', 'Baue Monumente und verbessere deine persönlichen Wahrheitskarten. Eine größere Herde ist nicht dein einziger Weg zur Macht.'],
    ['prophet', 'Prophet und Gebote', 'Der Falsche Prophet zieht weiter. Gebote verändern die Bedingungen für alle Betroffenen. Ein guter Plan braucht manchmal einen neuen Plan.'],
  ], [
    ['temple', 'Temples and figures', 'Singing monks baptize. Missionaries gain believers from fellow gods. Battle nuns strengthen your bid.'],
    ['monument', 'Monuments and Truth', 'Build monuments and improve your personal Truth cards. A bigger flock is not your only path to power.'],
    ['prophet', 'Prophet and commandments', 'The False Prophet moves on. Commandments change the conditions for everyone affected. Sometimes a good plan needs a new plan.'],
  ]);
  return `<section class="overview visual-overview" aria-labelledby="stage-title"><header class="overview-opening">${image('logo', 'overview-logo', 'Believe in Me, please')}<h1 id="stage-title" tabindex="-1">${t('Das Himmelreich geht weiter.', 'The Heavenly Realm goes on.')}</h1><p>${t('Ein kleiner Ausschnitt eines großen Himmelreichs.', 'A small glimpse of a much larger Heavenly Realm.')}</p></header><section class="worlds" aria-labelledby="worlds-title"><h2 id="worlds-title" class="worlds-title">${t('Noch zu entdecken', 'Still to discover')}</h2><div class="worlds-grid">${worlds.map(([art,title,text]) => `<article class="world world-${art}"><div class="world-art" aria-hidden="true">${image(art, '', '')}</div><h3>${title}</h3><p>${text}</p></article>`).join('')}</div></section><div class="overview-closing"><div><h2>${t('Das war erst der Anfang.', 'That was just the beginning.')}</h2><p>${state.mini_played ? t('Diese Mini-Partie verbindet deine Kartenhand, Tempel und Phänomen-Stechen auf dem Weg zur Dreifaltigkeit. Das vollständige Spiel bietet weitere Kartenkombinationen, andere Götter, Monumente und neun verschiedene Heilige Handgranaten.', 'This mini-match connects your hand, temples and phenomenon contests on the path to a complete Trinity. The full game adds more card combinations, other gods, monuments and nine different Holy Hand Grenades.') : t('Du hast Segen, Reliquien, Aufklärer, Heiliges Heer, eine Handgranate und ein Phänomen-Stechen erlebt. Eine ganze Partie bringt weitere Kartenkombinationen, andere Götter, neun Handgranaten und gespeicherte Mächte bis zur Götterdämmerung zusammen.', 'You have seen blessings, relics, an Enlightener, a Holy Army, a grenade and a phenomenon contest. A full match brings more card combinations, other gods, nine Holy Hand Grenades and stored powers together, all the way to Twilight of the Gods.')}</p></div><div class="overview-actions">${button('restart',t('Noch einmal ins Himmelreich', 'Back to the Heavenly Realm'), 'next')}<button type="button" class="back" data-tech>${t('Unter der Oberfläche', 'Under the surface')}</button></div></div><div class="overview-access"><p>${t('Barrierefreiheit mitgedacht. Tastaturbedienung und reduzierte Bewegung sind Teil der Demo; die umfassende Prüfung mit Menschen steht noch aus.', 'Accessibility considered. Keyboard controls and reduced motion are part of the demo; a full review with people is still outstanding.')}</p><button type="button" class="back" data-accessibility>${t('Über Barrierefreiheit', 'About Accessibility')}</button></div></section>`;
}

function updateAccessExample() {
  const result = document.querySelector('#access-demo-result');
  if (!result) return;
  const bid = accessExampleState === 'bid';
  const passed = accessExampleState === 'pass';
  result.dataset.state = accessExampleState;
  result.setAttribute('aria-label', t('Beispielgebot', 'Example bid'));
  document.querySelector('#access-command-sample').dataset.exampleState = accessExampleState;
  const title = bid ? t('Gebot abgelegt', 'Bid placed') : passed ? t('Endgültig gepasst', 'Passed for good') : t('Noch kein Gebot', 'No bid yet');
  result.innerHTML = `<div class="access-demo-placement" aria-hidden="true">${bid ? image('truth_p1_4','','') : passed ? image('pass','','') : '<span>&mdash;</span>'}</div><div class="access-demo-outcome"><strong>${title}</strong>${bid ? `<p><span class="access-demo-bid-value">4</span> ${t('Wahrheit','Truth')}</p>` : `<p>${passed ? t('Kein weiteres Gebot','No further bid') : t('Wahrheit 4','Truth 4')}</p>`}</div>`;
  const message = ({
    ready: t('Beispiel bereit. Noch kein Spielzug.', 'Example ready. No game move.'),
    select: t('Wahrheit 4 ausgewählt. Beispiel, kein Spielzug.', 'Truth 4 selected. Example, not a game move.'),
    bid: t('Gebot ausgewählt. Beispiel, keine Karte gespielt.', 'Bid selected. Example, no card played.'),
    pass: t('Passen ausgewählt. Beispiel, keine Partie verlassen.', 'Pass selected. Example, no match left.'),
  })[accessExampleState];
  const status = document.querySelector('#access-demo-status');
  if (status.textContent !== message) status.textContent = message;
}

function render(focusedAction, readingPosition) {
  if (techPage) {
    DemoLanguage.apply();
    document.title = `${t('Unter der Oberfläche','Under the surface')} · Believe in Me`;
    updateTech();
    document.querySelector('.tech-control').setAttribute('aria-current','page');
    document.querySelector('#restart').hidden = true;
    app.setAttribute('aria-busy','false');
    updateAccessNavigation();
    if (lastStage !== 'tech') {
      lastStage = 'tech';
      document.querySelector('#tech-title').focus({preventScroll:true});
      window.scrollTo({top:0,behavior:'instant'});
    }
    return;
  }
  if (accessibilityPage) {
    DemoLanguage.apply();
    document.title = `${t('Über Barrierefreiheit', 'About Accessibility')} · Believe in Me`;
    document.querySelector('#access-command-sample').innerHTML = `${miniHandCard({id:'truth-4',art:'truth_p1_4',truth_value:4,bid_value:4},{sample:true})}${gameCommand(t('Passen','Pass'),{sample:'pass',pass:true})}`;
    updateAccessExample();
    document.querySelector('#access-reading-sample').innerHTML = `${card('song')}<figcaption><span class="story-kicker">${t('Segen · Chaos','Blessing · Chaos')}</span><strong>${escape(cardName('song'))}</strong>${readableCard('song',{cost_believers:null})}<span class="access-state">${t('Grundwirkung 3 · mit Chaos 4','Base effect 3 · with Chaos 4')}</span></figcaption>`;
    document.querySelector('#access-game-values').innerHTML = `<div class="mini-flock"><div><h2>${t('Deine Herde','Your flock')}</h2><strong>6</strong><span>${t('freie Gläubige','free believers')}</span></div>${tokens(6)}</div><div class="access-turn-example"><h3>${t('Dein Zug.','Your turn.')}</h3><p class="mini-action-count">${t('2 Aktionen übrig','2 actions left')}</p></div><div class="access-blocked-example">${card('enrico')}<div><h3>${escape(cardName('enrico',true))}</h3><p>${t('Neue Reliquie gesperrt. Bereits angelegte Reliquien bleiben wirksam.', 'New relic blocked. Relics already in place remain active.')}</p></div></div><p class="access-example-note">${t('Darstellungsbeispiele, keine laufende Spielsituation.', 'Presentation examples, not a live game state.')}</p>`;
    const sacrificeExample = document.querySelector('.access-motion-example');
    sacrificeExample.removeAttribute('aria-hidden');
    sacrificeExample.innerHTML = `<span class="story-halo" aria-hidden="true"></span><div class="sacrifice-meeples" aria-hidden="true">${Array.from({length:6},(_,i) => `<span class="${i >= 3 ? 'sacrificed-meeple' : 'remaining-meeple'}">${image('believer','','')}</span>`).join('')}</div><p class="sacrifice-summary">${t('6 Gläubige · 3 Opfer · 3 bleiben', '6 believers · 3 sacrificed · 3 remain')}</p><button type="button" class="back" data-sacrifice-example>${t('Opfer zeigen', 'Show sacrifice')}</button><p class="access-example-note" role="status" id="sacrifice-example-status">${t('Darstellungsbeispiel, kein Spielzug.', 'Presentation example, not a game move.')}</p>`;
    document.querySelector('#restart').hidden = true;
    app.setAttribute('aria-busy', 'false');
    updateAccessNavigation();
    applyAccessPreferences();
    document.querySelectorAll('a[data-accessibility]').forEach(link => { link.setAttribute('aria-current','page'); });
    if (lastStage !== 'accessibility') { lastStage = 'accessibility'; document.querySelector('#stage-title').focus({preventScroll:true}); window.scrollTo({top:0,behavior:'instant'}); }
    return;
  }
  const scrollSnapshot = readingPosition || briefingScroll?.capture();
  briefingScroll?.destroy();
  briefingScroll = null;
  const motion = document.documentElement.dataset.motion === 'full' ? bidMotion : null;
  bidMotion = null;
  if (state.stage === 'mini') {
    app.innerHTML = miniScene(motion, focusedAction?.action === 'start_mini');
  } else if (state.stage === 'intro' && introBriefing) {
    app.innerHTML = briefing();
  } else if (state.stage === 'intro') {
    const roles = [['monk', t('Gesangsmönch', 'Singing monk')], ['missionary', t('Missionar', 'Missionary')], ['nun', t('Kampfnonne', 'Battle nun')]];
    app.innerHTML = `<section class="intro intro-showcase intro-choices"><h1 id="stage-title" class="visually-hidden" tabindex="-1">Believe in Me</h1><img class="intro-logo" src="./art/logo.png" alt="Believe in Me, please"><div class="roles">${roles.map(([key, label]) => `<figure>${image(key, '', label)}<figcaption>${label}</figcaption></figure>`).join('')}</div><p class="intro-tagline">${t('Ein Gott wird nicht an einem Tag gemacht.', "A god isn't made in a day.")}</p><nav class="entry-paths" aria-label="${t('Dein Weg ins Himmelreich', 'Choose your path')}">${state.mini_available ? `<button type="button" class="entry-path" data-briefing="mini">${image('head', 'entry-art', '')}<span>${t('Mini-Partie', 'Mini-Match')}</span>${arrowIcon}</button>` : ''}<a class="entry-path" href="./accessibility.html?lang=${DemoLanguage.get()}">${image('monk', 'entry-art', '')}<span>${t('Über Barrierefreiheit', 'About Accessibility')}</span>${arrowIcon}</a><button type="button" class="entry-path" data-briefing="open">${image('missionary', 'entry-art', '')}<span>Demo</span>${arrowIcon}</button></nav></section>`;
  } else if (state.stage === 'overview') {
    app.innerHTML = overview();
  } else if (state.contest_turn !== undefined && ['contest','claim','lost'].includes(state.stage)) {
    app.innerHTML = contestScene(motion);
  } else {
    const transition = ['grenade_intro','contest_intro'].includes(state.stage);
    const [title, prompt] = DemoLanguage.scene(state);
    app.innerHTML = `${progress()}<div class="game-layout ${state.stage === 'finale' ? 'revelation' : ''}"><section class="scene"><div class="scene-art ${state.stage === 'grenade_done' ? 'detonated' : ''}">${artwork()}</div><div class="scene-copy">${transition ? `<p class="scene-note">${t('Neue vorbereitete Spielsituation', 'New prepared game scene')}</p>` : ''}<h1 id="stage-title" tabindex="-1">${escape(title)}</h1><p class="prompt">${escape(prompt)}</p>${state.feedback ? `<p class="feedback">${escape(DemoLanguage.feedback(state))}</p>` : ''}<div class="controls">${controls()}</div></div></section>${board()}</div>`;
  }
  animateBelievers = false;
  app.setAttribute('aria-busy','false');
  const visibleStage = state.stage === 'intro' && introBriefing ? 'briefing' : state.stage;
  if (visibleStage !== lastStage) {
    const leavingBriefing = lastStage === 'briefing';
    lastStage = visibleStage;
    const heading = document.querySelector('#stage-title');
    heading?.focus({preventScroll:true});
    if (window.innerWidth < 760 || visibleStage === 'briefing' || leavingBriefing) window.scrollTo({top:0,behavior:'instant'});
  } else if (focusedAction) {
    const choices = [...app.querySelectorAll('[data-action]')];
    const next = choices.find(b => !b.disabled && b.dataset.action === focusedAction.action && b.dataset.value === focusedAction.value)
      || choices.find(b => !b.disabled && b.dataset.action === focusedAction.action) || choices.find(b => !b.disabled && !b.hidden);
    if (next && state.stage !== 'contest') next.focus({preventScroll:true});
  }
  // Announce only accepted actions, never selection, language or display rerenders.
  syncControls();
  briefingScroll = setupBriefingScroll(resumeChapter ? {id:`story-${resumeChapter}`, fraction:0} : scrollSnapshot);
  resumeChapter = null;
  updateAccessNavigation();
}

function syncControls() {
  document.querySelector('#restart').disabled = busy || !state;
  document.querySelector('#logout').disabled = busy || !state;
  app.querySelectorAll('button').forEach(b => {
    const action = b.dataset.action;
    b.disabled = busy || b.hasAttribute('data-unavailable') || (state.stage === 'contest' && state.contest_turn !== undefined
      && ((action === 'bid' && !state.can_bid) || (action === 'pass' && !state.can_pass)));
  });
  app.querySelector('[data-opponent-retry]')?.toggleAttribute('hidden', errorBox.hidden);
  syncCommandShortcuts();
}

function syncCommandShortcuts() {
  app.querySelectorAll('[data-command-key]').forEach(control => {
    const enabled = accessPreferences.commandKeys && !control.hasAttribute('data-command-unselected');
    if (enabled) control.setAttribute('aria-keyshortcuts', control.dataset.commandKey);
    else control.removeAttribute('aria-keyshortcuts');
  });
}

document.addEventListener('keydown', event => {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.metaKey || event.ctrlKey
      || event.altKey || event.shiftKey || busy || !accessPreferences.commandKeys || document.hidden
      || document.querySelector('dialog[open], [popover]:popover-open')) return;
  const active = event.target instanceof Element ? event.target : document.activeElement;
  if (active?.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"]')) return;
  const key = event.key.toLowerCase();
  if (!['b','p'].includes(key)) return;
  let control;
  if (accessibilityPage) {
    control = app.querySelector(`[data-access-demo="${key === 'b' ? 'bid' : 'pass'}"]`);
  } else if (state?.stage === 'mini' && state.match.phase === 'contest' && state.match.actor === 'p1') {
    control = key === 'p' ? app.querySelector('[data-action="mini_pass"]')
      : [...app.querySelectorAll('[data-action="mini_bid"]')].find(node => node.dataset.cardId === miniSelected);
  }
  // Reuse the exact visible command; never pick another card or bypass legality.
  if (!control || control.disabled || control.hidden || !control.getClientRects().length) return;
  event.preventDefault();
  control.click();
});

function stopOpponentTimer() {
  if (opponentTimer !== null) clearTimeout(opponentTimer);
  opponentTimer = null;
}

function scheduleOpponent() {
  // Mini-match results remain readable until an explicit Continue command.
  if (informationPage || state?.stage === 'mini') return;
  if (opponentTimer !== null || busy || !errorBox.hidden || document.hidden || document.querySelector('dialog[open]')
      || state?.stage !== 'contest' || !state.contest_turn || state.contest_turn === 'p1') return;
  const revision = state.revision;
  opponentTimer = setTimeout(() => {
    opponentTimer = null;
    if (state.revision === revision) act('advance_opponent');
  }, document.documentElement.dataset.motion === 'reduced' ? 400 : 1200);
}

async function refresh() {
  const response = await fetch('/api/state');
  if (response.status === 401) { window.location.assign(`./index.html?lang=${DemoLanguage.get()}`); return; }
  if (!response.ok) throw new Error(t('Der Spielstand konnte nicht geladen werden.', 'The game state could not be loaded.'));
  state = await response.json();
  previousBelievers = Object.fromEntries(state.players.map(p => [p.id, p.believers]));
  animateBelievers = false;
  render();
  scheduleOpponent();
}

async function act(action, extra = {}) {
  if (busy) return;
  stopOpponentTimer();
  busy = true;
  const active = document.activeElement;
  const focusedAction = active?.dataset.action ? {action:active.dataset.action, value:active.dataset.value} : null;
  announcements.textContent = '';
  let failed = false;
  errorBox.hidden = true;
  app.setAttribute('aria-busy','true');
  app.querySelectorAll('button').forEach(b => b.disabled = true);
  try {
    const submit = () => fetch('/api/action', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action, revision:state.revision, csrf:state.csrf, target, ...extra})});
    let response = await submit();
    // Another tab may have advanced this session. Only a confirmed reset can retry.
    if (response.status === 409 && action === 'restart') { await refresh(); response = await submit(); }
    if (response.status === 401) { window.location.assign(`./index.html?lang=${DemoLanguage.get()}`); return; }
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 409) await refresh();
      throw new Error(result.error ? DemoLanguage.error(result.error) : t('Der Zug konnte nicht ausgeführt werden.', 'The move could not be completed.'));
    }
    // Prepared scenes replace the flock; only real gains should celebrate an arrival.
    const prepared = action === 'restart' || result.trace.at(-1)?.events.some(event => event.type === 'demo_scene_prepared');
    previousBelievers = Object.fromEntries((prepared ? result : state).players.map(p => [p.id, p.believers]));
    animateBelievers = !prepared;
    const before = state;
    const focusMiniResult = before.stage === 'mini' && result.stage === 'mini'
      && action.startsWith('mini_');
    const feedback = result.stage === 'mini' ? miniAnnouncement(before, result, action) : DemoLanguage.feedback(result) || '';
    bidMotion = result.match?.last_move || result.bid_action;
    state = result;
    if (focusMiniResult) miniFeedback = feedback;
    if (action === 'restart') {
      miniSelected = null;
      miniFeedback = '';
      viewerSceneKey = 'viewer_lobby';
      target = 'p2';
      accessReturnChapter = '';
      document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
    }
    if (state.stage !== 'intro' || action === 'restart') {
      introBriefing = false;
      miniBriefing = false;
      if (['#before-you-play', '#before-mini-match'].includes(location.hash) || location.hash.startsWith('#story-')) {
        const url = new URL(location.href); url.hash = ''; history.replaceState(null, '', url);
      }
    }
    if (action === 'restart') {
      const url = new URL(location.href); url.hash = ''; url.searchParams.delete('resume');
      history.replaceState(null, '', url);
      lastStage = '';
    }
    busy = false;
    render(focusMiniResult ? null : focusedAction);
    if (focusMiniResult) {
      // One spoken target: the result, not another card plus a competing live message.
      app.querySelector('#mini-action-result').focus();
    } else announcements.textContent = feedback;
    if (action === 'restart') window.scrollTo({top:0,behavior:'instant'});
    if (state.stage === 'contest' && state.bid_action) {
      const actor = playerName(state.players.find(p => p.id === state.bid_action.player));
      announcements.textContent = state.bid_action.kind === 'bid'
        ? t(`${actor} legt eine verdeckte Karte.`, `${actor} plays a face-down card.`)
        : t(`${actor} passt endgültig.`, `${actor} passes for good.`);
      if (focusedAction && state.contest_turn !== 'p1') app.querySelector('#bid-turn')?.focus({preventScroll:true});
    }
  } catch (error) {
    failed = true;
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    busy = false;
    app.setAttribute('aria-busy','false');
    syncControls();
    if (!failed && state.stage === 'contest' && state.contest_turn === 'p1') {
      (app.querySelector('[data-action="bid"]:not(:disabled)') || app.querySelector('[data-action="pass"]:not(:disabled)'))?.focus({preventScroll:true});
      announcements.textContent += ` ${t('Du bist beim Bieten am Zug.', 'It is your turn to bid.')}`;
    }
    if (failed && active?.isConnected) active.focus({preventScroll:true});
    if (!failed) scheduleOpponent();
  }
}

function traceMetrics(trace) {
  const events = trace.flatMap(row => row.events);
  const prepared = events.filter(event => event.type === 'demo_scene_prepared').length;
  return {steps: trace.length, engineEvents: events.length - prepared, prepared};
}

function updateTech() {
  const number = value => new Intl.NumberFormat(DemoLanguage.get()).format(value);
  const metric = (key, value, label, note = '') => `<div data-metric="${key}"><dt>${escape(label)}${note ? `<span class="metric-help">${escape(note)}</span>` : ''}</dt><dd><span class="metric-value">${number(value)}</span></dd></div>`;
  if (developmentStats) {
    const d = developmentStats;
    const month = value => new Intl.DateTimeFormat(DemoLanguage.get(), {month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(`${value}-01T00:00:00Z`));
    const maximum = Math.max(...d.months.flatMap(([,prompts,commits]) => [prompts || 0,commits]));
    const labels = [t('Gespeicherte Prompts','Recorded prompts'),t('Code-Staende','Commits')];
    const chart = d.months.map(([date,prompts,commits]) => `<div class="development-month"><h4>${escape(month(date))}</h4><dl>${[prompts,commits].map((value,index) => `<div><dt>${escape(labels[index])}</dt><dd>${value === null ? `<span class="metric-note">${t('Keine Aufzeichnung','No record')}</span>` : `<span class="development-bar development-bar-${index}" aria-hidden="true" style="width:${value / maximum * 100}%"></span><strong>${number(value)}</strong>`}</dd></div>`).join('')}</dl></div>`).join('');
    document.querySelector('#development-process').innerHTML = `<h3 id="development-title">${t('Die Entwicklung des Gesamtprojekts','Developing the full project')}</h3><dl class="project-metrics development-metrics">${[
      metric('prompts',d.prompts,labels[0],t(`Aus ${number(d.chats)} projektzugeordneten Chats`,`From ${number(d.chats)} repository-associated chats`)),
      metric('documentedDecisions',d.decisions,t('Dokumentierte Entscheidungen','Documented decisions'),t(`${number(d.activeDecisions)} davon aktiv`,`${number(d.activeDecisions)} currently active`)),
      metric('commits',d.commits,labels[1],t('Alle lokal erreichbaren Branches','All locally reachable branches')),
    ].join('')}</dl><p class="metric-note">${t('Erfasster Zeitraum','Recorded period')}: ${d.from} – ${d.to} · ${t('Stand','Snapshot')}: ${d.date}</p><h4>${t('Monatlicher Entwicklungsverlauf','Development by month')}</h4><div class="development-chart">${chart}</div><details class="metric-evidence"><summary>${t('Was diese Zahlen belegen','What these numbers measure')}</summary><ul><li>${t('Prompts sind gespeicherte Nutzernachrichten in lokal vorhandenen Codex-Chats mit BiM-Arbeitsverzeichnis. Geforkte Nachrichten werden dedupliziert; automatische Agentennachrichten werden nicht gezählt. Auch Rückfragen und Freigaben zählen. Projektzugeordnete Chats können andere Themen enthalten.','Prompts are recorded user messages in locally available Codex chats associated with the BiM working directory. Forked messages are deduplicated; automated agent messages are excluded. Clarifications and approvals count. Repository-associated chats may include other topics.')}</li><li>${t('Gelöschte oder fehlende Chats und andere KI-Werkzeuge sind nicht erfasst. Keine Aufzeichnung bedeutet nicht: keine Arbeit. Oktober ist ein angebrochener Monat.','Deleted or missing chats and other AI tools are not covered. No record does not mean no work. October is a partial month.')}</li><li>${t('Entscheidungen sind eindeutige D-Nummern in DECISIONS.md, einschließlich historischer Einträge. Nicht jede Entwicklungsentscheidung ist dort dokumentiert.','Decisions are unique D identifiers in DECISIONS.md, including historical entries. Not every development decision is documented there.')} <code>${escape(d.revision.slice(0,8))}</code></li><li>${t('Code-Stände sind eindeutige Git-Commits aller lokal erreichbaren Referenzen, einschließlich Merge-Commits und nicht integrierter Branches. Keine Zahl veröffentlichter Funktionen oder bestandener Tests.','Commits are unique Git revisions across all locally reachable references, including merges and unintegrated branches. They do not count published features or passing tests.')}</li></ul><p>${t('Nur aggregierte Zahlen: keine Prompt-Inhalte, Chatnamen oder privaten Pfade.','Aggregates only: no prompt contents, chat titles or private paths.')}</p></details>`;
  }
  if (projectStats && document.querySelector('#project-metrics')) {
    document.querySelector('#project-metrics').innerHTML = [
      metric('sourceLines', projectStats.sourceLines, t('Nichtleere Python-Zeilen', 'Non-empty Python lines'), t('Regelkern, Simulation, Oberfläche', 'Engine, simulation, interface')),
      metric('sourceFiles', projectStats.sourceFiles, t('Python-Quelldateien', 'Python source files'), t('Ohne Tests und Abhängigkeiten', 'Excluding tests and dependencies')),
      metric('testFunctions', projectStats.testFunctions, t('Testfunktionen', 'Test functions'), t('Im Quellcode, nicht bestandene Fälle', 'Source definitions, not passed cases')),
      metric('decisions', projectStats.decisions, t('Aktive Entscheidungen', 'Active decisions'), t('Regeln und Entwicklungsverträge', 'Rules and development contracts')),
    ].join('');
    const date = new Intl.DateTimeFormat(DemoLanguage.get(), {dateStyle:'medium', timeZone:'UTC'}).format(new Date(`${projectStats.date}T00:00:00Z`));
    document.querySelector('#project-snapshot').textContent = t(`Quellcode-Stand vom ${date} · Gesamtprojekt, nicht nur diese Demo.`, `Source snapshot: ${date} · The full project, not just this demo.`);
    document.querySelector('#test-counting').textContent = t(`Funktionen, deren Name mit test_ beginnt, aus ${number(projectStats.testFiles)} Testdateien. Parametrisierte Varianten werden nicht zusätzlich gezählt; kein Bestehens- oder Abdeckungsversprechen.`, `Functions whose names start with test_ in ${number(projectStats.testFiles)} test files. Parameterized variants are not counted again; no pass or coverage claim.`);
    document.querySelector('#source-revision').innerHTML = `${t('Quellcode-Referenz', 'Source reference')}: <code>${escape(projectStats.snapshot.slice(0,8))}</code>`;
  }
  if (document.querySelector('#session-metrics')) {
    const stats = traceMetrics(state.trace);
    const eventCounts = new Map();
    for (const event of state.trace.flatMap(row => row.events)) {
      if (event.type === 'demo_scene_prepared') continue;
      eventCounts.set(event.type, (eventCounts.get(event.type) || 0) + 1);
    }
    const entries = [...eventCounts].sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0]));
    const maximum = Math.max(1,...entries.map(([,count]) => count));
    document.querySelector('#event-distribution').innerHTML = entries.length
      ? `<dl class="event-chart">${entries.map(([type,count]) => `<div><dt><code>${escape(type)}</code></dt><dd><span class="event-bar" aria-hidden="true" style="width:${count / maximum * 100}%"></span><strong>${number(count)}</strong></dd></div>`).join('')}</dl>`
      : `<p class="metric-note">${t('Noch keine Regelkern-Ereignisse aufgezeichnet. Das Diagramm entsteht aus deinen ausgeführten Zügen.', 'No engine events recorded yet. The chart is populated by your completed moves.')}</p>`;
    document.querySelector('#session-metrics').innerHTML = [
      metric('steps', stats.steps, t('Erfasste Schritte', 'Recorded steps')),
      metric('engineEvents', stats.engineEvents, t('Regelkern-Ereignisse', 'Engine events')),
      metric('prepared', stats.prepared, t('Vorbereitete Übergänge', 'Prepared transitions')),
    ].join('');
    document.querySelector('#trace-range').textContent = stats.steps
      ? t(`Schritte ${number(state.trace[0].step)} bis ${number(state.trace.at(-1).step)}. Der Verlauf enthält höchstens die letzten 100 Schritte.`, `Steps ${number(state.trace[0].step)} to ${number(state.trace.at(-1).step)}. The trace retains up to the latest 100 steps.`)
      : t('Noch keine Schritte aufgezeichnet.', 'No steps recorded yet.');
  }
}

function openTechPage(control) {
  stopOpponentTimer();
  updateAccessNavigation();
  if (control.tagName === 'BUTTON') window.location.assign(document.querySelector('.tech-control').href);
}

function updateArt(key) {
  const capture = viewerScenes().find(scene => scene[0] === key);
  document.querySelector('#art-dialog').classList.toggle('viewer-art-dialog',Boolean(capture));
  const title = enlargedArtOptions.title || cardName(key, true);
  const artwork = enlargedArtOptions.english ? `${key}_en` : key;
  document.querySelector('#art-detail').innerHTML = `<h2 id="art-title" ${enlargedArtOptions.english ? 'lang="en"' : ''}>${escape(title)}</h2>${capture ? '' : readableCard(key)}<div class="zoom-art ${capture ? 'viewer-zoom-art' : ['grenade','yak','squirrels','earthquake','tornado'].includes(key) ? 'landscape' : ''}">${image(artwork,'',capture?.[2] || title)}</div>`;
}

function applyLanguage() {
  const readingPosition = briefingScroll?.reading();
  DemoLanguage.apply();
  applyAccessPreferences();
  if (state) render(undefined, readingPosition);
  if (enlargedArt && document.querySelector('#art-dialog').open) updateArt(enlargedArt);
}

document.addEventListener('click', event => {
  const settings = event.target.closest('[data-access-settings]');
  if (settings) {
    if (busy) return;
    accessibilityOpener = settings;
    stopOpponentTimer();
    applyAccessPreferences();
    updateAccessNavigation();
    settings.setAttribute('aria-expanded','true');
    document.querySelector('#accessibility-dialog').showModal();
    document.querySelector('#access-settings-title').focus({preventScroll:true});
    return;
  }
  if (event.target.closest('[data-sacrifice-example]')) {
    const sample = document.querySelector('.sacrifice-meeples');
    sample.classList.remove('sacrifice-playing');
    void sample.offsetWidth;
    sample.classList.add('sacrifice-playing');
    document.querySelector('#sacrifice-example-status').textContent = t('Beispiel: 3 Gläubige geopfert, 3 bleiben. Kein Spielzug.', 'Example: 3 believers sacrificed, 3 remain. No game move.');
    return;
  }
  if (event.target.closest('[data-access-select]')) {
    accessExampleState = 'select';
    updateAccessExample();
    return;
  }
  const accessExample = event.target.closest('[data-access-demo]');
  if (accessExample) {
    accessExampleState = accessExample.dataset.accessDemo;
    updateAccessExample();
    return;
  }
  const selected = event.target.closest('[data-mini-select]');
  if (selected && !busy) { miniSelected = selected.dataset.miniSelect; render(); app.querySelector(`[data-mini-select="${CSS.escape(miniSelected)}"]`)?.focus({preventScroll:true}); return; }
  const introduction = event.target.closest('[data-briefing]');
  if (introduction) { setBriefing(introduction.dataset.briefing !== 'close', introduction.dataset.briefing === 'mini'); return; }
  const action = event.target.closest('[data-action]');
  if (action && !action.disabled) {
    if (action.dataset.action === 'restart') requestRestart(action);
    else act(action.dataset.action, action.dataset.action.startsWith('mini_') ? miniPayload(action) : action.dataset.value ? {value:Number(action.dataset.value)} : {});
    return;
  }
  const art = event.target.closest('[data-art]');
  if (art) {
    enlargedArt = art.dataset.art;
    enlargedArtOptions = {english:art.dataset.artEnglish === 'true',title:art.dataset.artTitle || null};
    updateArt(enlargedArt);
    document.querySelector('#art-dialog').showModal();
  }
  const tech = event.target.closest('[data-tech]');
  if (tech) {
    if (busy) { event.preventDefault(); return; }
    if (!event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) openTechPage(tech);
  }
  if (event.target.closest('[data-accessibility]')) {
    stopOpponentTimer();
    updateAccessNavigation();
    if (event.target.closest('[data-accessibility]').tagName === 'BUTTON') window.location.assign(document.querySelector('a[data-accessibility]').href);
  }
  if (event.target.closest('.dialog-close')) event.target.closest('dialog').close();
  if (document.querySelector('dialog[open]')) stopOpponentTimer();
});
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('close', scheduleOpponent));
document.querySelector('#accessibility-dialog').addEventListener('close', () => {
  document.querySelector('.accessibility-control').setAttribute('aria-expanded','false');
  const opener = accessibilityOpener?.isConnected ? accessibilityOpener : document.querySelector('.accessibility-control');
  opener.focus({preventScroll:true});
  accessibilityOpener = null;
});
function requestRestart(opener) {
  if (!state || busy || informationPage) return;
  restartOpener = opener;
  stopOpponentTimer();
  document.querySelector('#restart-dialog').showModal();
  document.querySelector('[data-restart-cancel]').focus();
}
document.querySelector('#restart-dialog').addEventListener('close', () => {
  if (restartOpener?.isConnected) restartOpener.focus({preventScroll:true});
  restartOpener = null;
});
document.addEventListener('visibilitychange', () => { if (document.hidden) stopOpponentTimer(); else scheduleOpponent(); });
document.addEventListener('change', event => {
  if (event.target.name === 'viewer-scene') {
    viewerSceneKey = event.target.value;
    const scene = viewerScenes().find(item => item[0] === viewerSceneKey);
    const capture = app.querySelector('.viewer-capture');
    capture.dataset.art = viewerSceneKey;
    capture.setAttribute('aria-label',t(`${scene[1]} vergrößern`,`Enlarge ${scene[1]}`));
    const img = capture.querySelector('img');
    img.src = `${window.BimBrowser.art(viewerSceneKey)}`;
    img.alt = scene[2];
    return;
  }
  if (event.target.id === 'target') target = event.target.value;
  if (event.target.matches('[data-language]')) {
    if (busy) { event.target.value = DemoLanguage.get(); return; }
    const id = event.target.id;
    DemoLanguage.set(event.target.value);
    applyLanguage();
    document.getElementById(id)?.focus({preventScroll:true});
  }
});
document.querySelector('#restart').addEventListener('click', event => requestRestart(event.currentTarget));
document.querySelector('[data-restart-cancel]').addEventListener('click', () => document.querySelector('#restart-dialog').close());
document.querySelector('[data-restart-confirm]').addEventListener('click', () => { document.querySelector('#restart-dialog').close(); act('restart'); });
document.querySelector('#logout').addEventListener('click', async () => {
  if (!state || busy) return;
  busy = true;
  errorBox.hidden = true;
  try {
    const response = await fetch('/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:state.csrf})});
    if (response.ok || response.status === 401) window.location.assign(`./index.html?lang=${DemoLanguage.get()}`);
    else { errorBox.textContent = t('Abmelden fehlgeschlagen. Bitte erneut versuchen.', 'Sign out failed. Please try again.'); errorBox.hidden = false; }
  } catch (_) {
    errorBox.textContent = t('Abmelden fehlgeschlagen. Bitte prüfe die Verbindung und versuche es erneut.', 'Sign out failed. Check your connection and try again.');
    errorBox.hidden = false;
  } finally {
    busy = false;
  }
});
applyLanguage();
refresh().catch(() => { errorBox.textContent = t('Der Spielstand konnte nicht geladen werden.', 'The game state could not be loaded.'); errorBox.hidden = false; app.innerHTML = `<p class="loading">${t('Bitte lade die Seite erneut.', 'Please reload the page.')}</p>`; });
