'use strict';

const DemoLanguage = (() => {
  let language = 'en';
  try {
    const requested = new URLSearchParams(location.search).get('lang');
    const saved = localStorage.getItem('believe-in-me-language');
    language = ['en', 'de'].includes(requested) ? requested : (['en', 'de'].includes(saved) ? saved : 'en');
  } catch (_) {
    const requested = new URLSearchParams(location.search).get('lang');
    if (['en', 'de'].includes(requested)) language = requested;
  }
  const text = (de, en) => language === 'en' ? en : de;
  const interpolate = (template, values) => template.replace(/\{(\w+)\}/g, (_, key) => String(values[key] ?? ''));
  const names = {
    song: 'Chant', song_again: 'Chant', ash: "Roswitha's still-warm ashes",
    skull: "Ansgar's shattered skull", enrico: 'Enrico the Explorer',
    army: 'Irma the Inquisitress', grenade: 'Holy Hand Grenade of Ice-Cold Revenge',
    yak: 'Two-headed Yak', head: 'Walter', chest: 'the Doubting Decider',
    legs: 'with house-dust allergy', frauke: 'Frida the Flayer', henk: 'Henk the Heckler',
    squirrels: 'Squirrel plague', earthquake: 'Earthquake', tornado: 'Tornado',
  };
  const artNames = {
    ...names, ash: 'The still-warm ashes of Roswitha the Redhead',
    skull: 'The shattered skull of Ansgar the Elder',
  };
  const scenes = {
    mini: ['Mini-match', 'A continuous game state.'],
    intro: ['Believe in Me', "A god isn't made in a day."],
    song: ['A small miracle', 'Play Chant and gain three believers.'],
    ash: ['Ashes with lasting effects', 'Roswitha helps your Holy Army. Placing the relic costs two believers.'],
    arrival: ['An uninvited visitor', 'Your fellow god has an Enlightener for you.'],
    blocked: ['Enrico objects', "Can you place Ansgar's skull now?"],
    army: ['Irma clears the way', 'Roswitha is already in place. Enrico cannot switch off her effect.'],
    skull: ['Room for a new plan', 'One relic slot: the skull replaces Roswitha for two believers.'],
    boost: ['Same chant. Greater effect.', 'This Chant does not match your alignment either. The skull still helps.'],
    combo_done: ['Five new believers', "Three from Chant, two from Ansgar's skull."],
    grenade_intro: ['A later round', 'Prepared scene: two actions, eight free believers and an uncharged grenade.'],
    grenade: ['Ice-cold revenge', 'Each charge takes one action and one believer. More patience, greater effect.'],
    grenade_done: ['Amen.', "The grenade is spent. Its effect is visible in your fellow gods' flocks."],
    contest_intro: ['Just before Revelation', 'Prepared scene: Walter has a head and chest. His legs are still missing.'],
    contest: ['One yak. Two heads.', 'Bid secretly for its power. Or pass for good. The sum of your cards decides.'],
    claim: ['The power is yours', 'The Yak makes a fellow god skip their next turn. They may still join the contest.'],
    lost: ['The Yak follows a fellow god', 'A fresh attempt starts with the same cards.'],
    finale: ['Hallelujah!', 'Walter, the Doubting Decider with house-dust allergy'],
    power_done: ['A power for later', 'You stored the Yak and chose not to manifest a body part.'],
    overview: ['The whole game', 'One slice played. Much more to discover.'],
  };
  const feedback = {
    song: '{count} new believers follow you.',
    ash: 'Roswitha is in place. Your Holy Army no longer costs sacrifices.',
    blocked: 'Enrico blocks new relics. Roswitha stays active. This attempt costs no action.',
    army: 'Enrico is gone. {count} sacrifices instead of four: Roswitha helps.',
    skull: "Roswitha is discarded. Ansgar's skull takes her place.",
    boost: '{count} new believers: three from the blessing, two from the skull.',
    manifest: '{count} believers for winning the phenomenon, three for Revelation.',
    keep_power: 'The Yak is stored as a power. {count} believers follow you.',
    charge: 'One believer charges the grenade.',
    third_charge: 'Third charge: eight sacrifices. The grenade must detonate.',
    ignite: 'Tier {tier}: {count} sacrifices.',
    wait: 'You hold off detonating. Another charge needs another action.',
    next_turn: 'Your fellow gods have grown their flocks. You have two actions again.',
    reveal: 'All cards are revealed. The engine totals the bids.',
  };
  const copy = {
    skip: ['Zum Spiel springen', 'Skip to the game'], session: ['Sitzung', 'Session'],
    language: ['Sprache', 'Language'], accessibility: ['Barrierefreiheit', 'Accessibility'],
    aboutAccessibility: ['Über Barrierefreiheit', 'About Accessibility'],
    restart: ['Neu beginnen', 'Restart'], logout: ['Lokale Partie löschen', 'Clear local match'],
    restartQuestion: ['Zur Himmelspforte zurück?', 'Return to the Heavenly Gate?'],
    restartDetail: ['Die aktuelle Partie wird zurückgesetzt. Dein Zugang und deine Anzeige bleiben erhalten.', 'The current match will reset. Your access and display choices stay.'],
    cancel: ['Weiterspielen', 'Keep playing'],
    loading: ['Das Himmelreich wird vorbereitet.', 'Preparing the Heavenly Realm.'],
    close: ['Schließen', 'Close'], tech: ['Unter der Oberfläche', 'Under the surface'],
    architecture: ['Python-Regelkern · getrennte Spielstände · lokale Browser-Entscheidungen', 'Python rules engine · isolated game states · browser-local decisions'],
    techEyebrow: ['Technischer Einblick', 'Technical overview'],
    eventDistribution: ['Ereignisse nach Typ', 'Events by type'],
    engineFlowTitle: ['Was ein Loblied tatsächlich verändert', 'What playing Chant actually changes'],
    flowExample: ['Beispiel: Neue Browser-Mini-Partie mit 6 Start-Glaeubigen. Nicht dein aktueller Spielstand.', 'Example: a new browser mini-match with 6 starting believers. Not your current game state.'],
    flowMove: ['Loblied spielen', 'Play Chant'],
    flowMoveDetail: ['Die Engine prüft: Walter ist am Zug, die Karte ist auf seiner Hand und eine Aktion ist verfügbar.', 'The engine checks: Walter is taking the turn, holds the card and has an action available.'],
    flowRules: ['Chaos: 3 werden 4', 'Chaos: 3 becomes 4'],
    flowRulesDetail: ['Grundwirkung: 3 Gläubige. Walters Chaos-Gesinnung erhöht die Wirkung auf 4.', 'Base effect: 3 believers. Walter\'s Chaos alignment increases the effect to 4.'],
    flowState: ['Herde: 6 auf 10', 'Flock: 6 to 10'],
    flowStateDetail: ['Vier freie Gläubige kommen hinzu. Die gespielte Karte verlässt die Hand.', 'Four free believers are gained. The played card leaves the hand.'],
    flowEvents: ['Aktionen: 2 auf 1', 'Actions: 2 to 1'],
    flowEventsDetail: ['Eine Aktion ist verbraucht. Die Zugmeldung nennt 10 freie Gläubige und den Zuwachs +4.', 'One action is spent. The turn message reports 10 free believers and the gain +4.'],
    engineeringCases: ['Regeln, die zusammenwirken', 'Rules that interact'],
    caseBlockTitle: ['Sperren sind nicht rückwirkend', 'A block is not retroactive'],
    caseBlockDetail: ['Enrico verhindert neue Reliquien. Roswithas bereits angelegte Asche bleibt trotzdem wirksam. Ein gesperrter Anlegeversuch verbraucht keine Aktion.', 'Enrico blocks new relics. Roswitha\'s already attached ashes still work. A blocked attempt to attach a relic spends no action.'],
    caseCostTitle: ['Kosten aus Kartenkombinationen', 'Costs from card combinations'],
    caseCostDetail: ['Irma entfernt einen beliebigen Aufklärer normalerweise für 4 Opfer. Roswithas Asche reduziert diese Opferkosten auf 0; die Aktion bleibt erforderlich.', 'Irma normally removes any Enlightener for 4 sacrifices. Roswitha\'s ashes reduce that sacrifice cost to 0; the action is still required.'],
    casePrivateTitle: ['Lokaler Spielstand je Tab', 'Local progress in each tab'],
    casePrivateDetail: ['Regelkern und ausgewaehlte Originalgrafiken werden in deinen Browser geladen. Gegnerkarten sind nur in der Oberflaeche verdeckt. Diese Browser-Demo hat keinen Passwortschutz.', 'The engine and selected original artwork are loaded into your browser. Opponent cards are hidden in the interface only. This browser demo has no password protection.'],
    projectTitle: ['Quellcode-Inventar', 'Source inventory'],
    countingTitle: ['Was genau wurde gezählt?', 'What exactly was counted?'],
    sourceCounting: ['Nichtleere Zeilen und Dateien im Python-Quellcode von Regelkern, Simulation und Oberfläche. Kommentare und Dokumentationsstrings sind enthalten; Tests, Skripte, Grafiken, Berichte und Abhängigkeiten nicht.', 'Non-empty lines and files in the Python source for the rules engine, simulation and interface. Comments and docstrings are included; tests, scripts, artwork, reports and dependencies are not.'],
    decisionCounting: ['Aktive Einträge im verbindlichen Entscheidungsdokument. Abgelöste Einträge werden nicht mitgezählt. Die Zahl belegt Dokumentation, nicht die vollständige Umsetzung aller Regeln.', 'Active entries in the binding decision document. Superseded entries are excluded. This counts documentation, not complete implementation of every rule.'],
    countingLimit: ['Eine Quellcode-Inventur, keine Zeitmessung, Qualitätsnote oder aktuelle Vollsuite-Abnahme.', 'A source inventory, not hours worked, a quality score or a current full-suite pass.'],
    sessionMetricsTitle: ['Dein aktueller Verlauf', 'Your current trace'],
    traceTitle: ['Technische Details: Ereignisstatistik', 'Technical details: event statistics'],
    events: ['Jeder ausgeführte Zug erzeugt Ereignisse. Die vorbereiteten Szenenwechsel stehen ausdrücklich im Verlauf.', 'Every completed move produces events. Prepared scene transitions are explicitly recorded in the trace.'],
    considered: ['Barrierefreiheit mitgedacht', 'Accessibility considered'],
    techAccess: ['So setzt diese Demo Zugänglichkeit um: mit Tastatur, lesbaren Karten und verständlichen Rückmeldungen.', 'How this demo makes play accessible: keyboard control, readable cards and clear feedback.'],
    showAccess: ['Über Barrierefreiheit', 'About Accessibility'],
    accessIntro: ['Zugänglichkeit gehört für mich zur Entwicklung, nicht erst zur fertigen Oberfläche.', 'Accessibility is part of my development process, not an afterthought.'],
    reduce: ['Bewegung reduzieren', 'Reduce motion'],
    textSize: ['Textgröße', 'Text size'], normalText: ['Normal', 'Normal'], largerText: ['Größer', 'Larger'],
    textSizeHint: ['18 % größere Schrift; die Kartengrafiken bleiben im Original.', '18% larger text; card artwork stays original.'],
    reading: ['Lesbarkeit', 'Reading'], clearCards: ['Symbole und Namen', 'Symbols and names'],
    clearCardsHint: ['Namen, Kartentypen und Auswahlstatus. Gleiche Darstellung in dieser Demo und ihrer Mini-Partie.', 'Names, card types and selection states. The same presentation here and in the mini-match.'],
    contrast: ['Kontrast', 'Contrast'], highContrast: ['Stärkerer Kontrast', 'Stronger contrast'],
    contrastHint: ['Dunklere Schrift, klarere Grenzen und kräftigerer Fokus. Originalbilder werden nicht umgefärbt.', 'Darker text, clearer boundaries and stronger focus. Original artwork is not recolored.'],
    motion: ['Bewegung', 'Motion'], followSystem: ['Systemeinstellung verwenden', 'Use system preference'],
    resetDisplay: ['Anzeigeeinstellungen zurücksetzen', 'Reset display settings'],
    accessSupport: ['Tastatur- und Screenreader-Unterstützung', 'Keyboard and screen-reader support'],
    keyboard: ['Tastaturbedienbare Schaltflächen und Dialoge mit sichtbarem Fokus.', 'Keyboard-operable buttons and dialogs with visible focus.'],
    values: ['Spielwerte als Text und Zahlen; der Sieger wird ausdrücklich benannt.', 'Game values as text and numbers; the winner is explicitly named.'],
    artwork: ['Benannte Kartengrafiken, eine Vergrößerungsansicht und Textmeldungen zu Spielaktionen.', 'Named card artwork, an enlargement view and text feedback for game actions.'],
    limit: ['Ein Anfang, kein Zertifikat: Eine vollständige Prüfung mit Screenreadern und Menschen mit unterschiedlichen Einschränkungen steht noch aus.', 'A starting point, not certification: a full review with screen readers and people with different disabilities is still outstanding.'],
    accessTitle: ['Ein Himmelreich für mehr Menschen.', 'A realm for more people.'],
    accessLead: ['Barrierefreiheit im Spiel, nicht nur auf dem Papier.', 'Accessibility in play, not just on paper.'],
    returnRealm: ['Zurück ins Himmelreich', 'Return to your realm'],
    keyboardTitle: ['Ein klarer Weg. Auch ohne Maus.', 'A clear path. Without a mouse.'],
    keyboardProof: ['Eine Karte auswählen. Bieten oder passen. Jeder Befehl hat einen Namen und einen sichtbaren Fokus.', 'Choose a card. Bid or pass. Each command has a name and a visible focus.'],
    sampleOnly: ['Darstellungsbeispiel. Verändert keine Partie.', 'Presentation example. Does not change a match.'],
    demoHand: ['Kartenhand', 'Your hand'], demoBid: ['Bieten', 'Bid'], demoPass: ['Passen', 'Pass'],
    bidPassKeys: ['Tastenkürzel für Bieten/Passen', 'Bid/Pass shortcuts'],
    demoReady: ['Beispiel bereit. Noch kein Spielzug.', 'Example ready. No game move.'],
    readingTitle: ['Mehr als ein Kartenbild.', 'More than card artwork.'],
    readingProof: ['Die Grafik bleibt original. Wirkung und Werte werden zusätzlich lesbar, auch beim Vergrößern.', 'The artwork stays original. Effects and values are also readable, including in the enlarged view.'],
    enlargeChant: ['Loblied vergrößern', 'Enlarge Chant'],
    chant: ['Loblied', 'Chant'], blessing: ['Segen', 'Blessing'],
    chantEffect: ['Taufe 3 Gläubige. Mit Chaos-Gesinnung: 4.', 'Baptize 3 believers. With Chaos alignment: 4.'],
    demoGain: ['+3 Gläubige', '+3 believers'], believers: ['Gläubige', 'believers'],
    displayTitle: ['Klarheit ist keine Farbe.', 'Clarity is not a color.'],
    displayProof: ['Zahlen und Statuswörter ergänzen Farbsignale. Der zusätzliche Kontrastmodus gilt für diese Webdemo.', 'Numbers and status words accompany color cues. The additional contrast mode belongs to this web demo.'],
    demoCurrent: ['✓ Dein Zug', '✓ Your turn'], demoBlocked: ['× Neue Reliquie gesperrt', '× New relic blocked'],
    motionTitle: ['Die Macht bleibt. Bewegung darf gehen.', 'Keep the power. Lose the motion.'],
    motionProof: ['Animationen respektieren die Systemeinstellung. Ohne Bewegung bleiben dieselben Karten, Werte und Entscheidungen sichtbar.', 'Animations follow the system preference. Without motion, the same cards, values and decisions remain visible.'],
    resetExample: ['Standardansicht wiederherstellen', 'Restore default view'],
    accessLimit: ['Die freigegebene Gestaltung verbindet Beispiele, Mini-Partie und Viewer. Einstellungen bleiben getrennt. Umfassende Screenreader- und Nutzerprüfung offen; keine Zertifizierung.', 'The approved design connects examples, the mini-match and the Viewer. Settings stay separate. Full screen-reader and user review pending; not certification.'],
  };
  const errors = {
    'Bitte anmelden.': 'Please sign in.', 'Deine Anmeldung ist abgelaufen.': 'Your session has expired.',
    'Der Spielstand hat sich geändert. Bitte erneut versuchen.': 'The game state has changed. Please try again.',
    'Keine Aktion mehr verfügbar.': 'No actions left.',
    'Diese Aktion ist in der aktuellen Szene nicht verfügbar.': 'This action is unavailable in the current scene.',
    'Wähle einen Mitgott oder beide.': 'Choose a fellow god or both.',
    'Diese Granatenaktion ist gerade nicht möglich.': 'This grenade action is currently unavailable.',
    'Du bist beim Bieten gerade nicht dran.': 'It is not your turn to bid.',
    'Wähle eine verfügbare Wahrheitskarte.': 'Choose an available Truth card.',
    'Diese Wahrheitskarte wurde bereits geboten.': 'This Truth card has already been bid.',
    'Ungültige Anfrage.': 'Invalid request.', 'Ungültige Sitzungsbestätigung.': 'Invalid session confirmation.',
  };
  return {
    get: () => language, text,
    set(value) {
      if (!['en', 'de'].includes(value)) return;
      language = value;
      try { localStorage.setItem('believe-in-me-language', value); } catch (_) {}
      const url = new URL(location.href); url.searchParams.set('lang', value);
      history.replaceState(null, '', url);
    },
    name: (key, de, full = false) => language === 'en' ? (full ? artNames[key] : names[key]) || de : de,
    art: key => language === 'en' && (Object.hasOwn(names, key) || /^truth_p\d_\d+$/.test(key)) ? `${key}_en` : key,
    scene: state => language === 'en' ? scenes[state.stage] || [state.title || state.stage, state.prompt || ''] : [state.title || state.stage, state.prompt || ''],
    feedback: row => language === 'en' && row.feedback_message
      ? interpolate(feedback[row.feedback_message.key] || '', row.feedback_message.values) : row.feedback,
    error: message => language === 'en' ? errors[message] || 'The move could not be completed. Please try again.' : message,
    apply() {
      document.documentElement.lang = language;
      document.querySelectorAll('[data-copy]').forEach(node => { node.textContent = text(...copy[node.dataset.copy]); });
      document.querySelectorAll('[data-copy-label]').forEach(node => { node.setAttribute('aria-label', text(...copy[node.dataset.copyLabel])); });
      document.querySelectorAll('[data-language]').forEach(node => { node.value = language; });
      document.querySelector('.accessibility-control').title = text(...copy.accessibility);
      document.querySelector('#restart').title = text(...copy.restart);
      document.querySelector('#logout').title = text(...copy.logout);
    },
  };
})();
