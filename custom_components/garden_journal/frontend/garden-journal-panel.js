/*
 * Garden Journal browse panel.
 *
 * Plain custom element with no dependencies and no build step, so the file that
 * ships is the file that was written. Home Assistant sets `hass`, `narrow` and
 * `panel` properties on the element.
 *
 * Searching goes to the server and comes back one page at a time, and scrolling
 * to the end asks for the next page, so the panel never holds the whole dataset.
 * Photos load only once their card is on screen, and are fetched from Home
 * Assistant with the auth header, which keeps the browser off the remote host and
 * works where an <img src> could not send a token.
 */

const DEBOUNCE_MS = 250;
const PAGE_SIZE = 24;

/*
 * The panel's own strings. A custom panel is not covered by the integration's
 * translation files, which Home Assistant loads for config flows and entities,
 * so the few strings this page owns live here and are picked by hass.language.
 * Anything unknown falls back to English.
 */
const STRINGS = {
  en: {
    search: "Search plants",
    loadingMore: "Loading more",
    more: (n) => `Scroll for ${n} more`,
    noPhoto: "No photo",
    photo: (credit) => `Photo: ${credit}`,
    planted: "Planted",
    plantedTimes: (n) => `Planted ${n}x`,
    plantedTitle: "You have this in your garden",
    plantedTitleTimes: (n) => `You have ${n} of these in your garden`,
    nameLabel: "Name for this plant",
    nameHint: "This name labels the plant's device and entities. You can change it later.",
    add: "Add",
    cancel: "Cancel",
    close: "Close",
    pruning: "Pruning",
    care: "Ongoing care",
    careOpen: "now",
    careNow: "Ongoing care",
    source: "Source",
    loadFailed: "Could not load plants",
    addFailed: "Could not add the plant",
    months: [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ],
    range: (from, to) => `${from} to ${to}`,
    myGarden: "My garden",
    addPlantTitle: "Add a plant",
    addPlantButton: "Add plant",
    back: "Back to my garden",
    emptyGarden: "No plants yet. Add your first one to get pruning dates.",
    pruneNow: "Prune now",
    nextPruning: "Next pruning",
    until: (date) => `until ${date}`,
    unknownTiming: "Timing unknown, needs attention",
    secComingSoon: "Coming up soon",
    secAttention: "Needs attention",
    secOther: "Everything else",
    nothingToPrune: "Nothing needs pruning today",
    noCareOpen: "No care jobs open right now",
    inDays: (n) => `in ${n} days`,
    today: "today",
    tomorrow: "tomorrow",
    openDevice: "Open in Home Assistant",
    save: "Save",
    remove: "Remove",
    confirmRemove: (name) => `Remove ${name} and its entities?`,
    confirmYes: "Yes, remove",
    saved: "Name changed",
    manualPlant: "Added by hand, not from the dataset",
    renameFailed: "Could not rename the plant",
    removeFailed: "Could not remove the plant",
    notInList: "Add by hand",
    manualTitle: "Add a plant by hand",
    manualIntro:
      "For a plant the dataset does not cover yet. Home Assistant will offer you a snippet to contribute it back.",
    botanicalLabel: "Botanical name",
    botanicalHint: "For example Buxus sempervirens. Genus first.",
    timingLabel: "Pruning timing",
    timingBorrow: "Prune it like another plant",
    timingOwn: "Write the timing myself",
    borrowLabel: "Pruned like",
    borrowSearch: "Search a plant",
    noMatches: "No plant matched that name",
    needBorrow: "Pick a plant from the results",
    windowStart: "From",
    windowEnd: "Until",
    windowWhat: "What to do",
    addWindow: "Add another period",
    removeWindow: "Remove this period",
    optional: "Source and photo (optional)",
    sourceLabel: "Source URL",
    imageLabel: "Photo URL",
    day: "Day",
    month: "Month",
    manualFailed: "Could not add the plant",
    needBotanical: "Give a botanical name",
    needWindow: "Give at least one pruning period, with what to do",
    badDate: "That is not a real date. There is no 31 February, and 29 February cannot be used.",
  },
  nl: {
    search: "Zoek planten",
    loadingMore: "Meer laden",
    more: (n) => `Scroll voor nog ${n}`,
    noPhoto: "Geen foto",
    photo: (credit) => `Foto: ${credit}`,
    planted: "Geplant",
    plantedTimes: (n) => `${n}x geplant`,
    plantedTitle: "Deze staat in je tuin",
    plantedTitleTimes: (n) => `Hiervan staan er ${n} in je tuin`,
    nameLabel: "Naam voor deze plant",
    nameHint: "Deze naam komt op het apparaat en de entiteiten van de plant. Je kunt hem later aanpassen.",
    add: "Toevoegen",
    cancel: "Annuleren",
    close: "Sluiten",
    pruning: "Snoeien",
    care: "Doorlopend onderhoud",
    careOpen: "nu",
    careNow: "Doorlopend onderhoud",
    source: "Bron",
    loadFailed: "Kon de planten niet laden",
    addFailed: "Kon de plant niet toevoegen",
    months: [
      "januari", "februari", "maart", "april", "mei", "juni",
      "juli", "augustus", "september", "oktober", "november", "december",
    ],
    range: (from, to) => `${from} tot ${to}`,
    myGarden: "Mijn tuin",
    addPlantTitle: "Plant toevoegen",
    addPlantButton: "Plant toevoegen",
    back: "Terug naar mijn tuin",
    emptyGarden: "Nog geen planten. Voeg je eerste toe voor snoeidata.",
    pruneNow: "Nu snoeien",
    nextPruning: "Volgende snoei",
    until: (date) => `tot ${date}`,
    unknownTiming: "Timing onbekend, vraagt aandacht",
    secComingSoon: "Binnenkort",
    secAttention: "Vraagt aandacht",
    secOther: "Overige planten",
    nothingToPrune: "Vandaag hoeft er niets gesnoeid te worden",
    noCareOpen: "Geen doorlopend onderhoud op dit moment",
    inDays: (n) => `over ${n} dagen`,
    today: "vandaag",
    tomorrow: "morgen",
    openDevice: "Openen in Home Assistant",
    save: "Opslaan",
    remove: "Verwijderen",
    confirmRemove: (name) => `${name} en de entiteiten verwijderen?`,
    confirmYes: "Ja, verwijderen",
    saved: "Naam gewijzigd",
    manualPlant: "Handmatig toegevoegd, niet uit de dataset",
    renameFailed: "Kon de plant niet hernoemen",
    removeFailed: "Kon de plant niet verwijderen",
    notInList: "Handmatig invoeren",
    manualTitle: "Plant handmatig toevoegen",
    manualIntro:
      "Voor een plant die nog niet in de dataset staat. Home Assistant geeft je daarna een stukje YAML om hem terug te delen.",
    botanicalLabel: "Botanische naam",
    botanicalHint: "Bijvoorbeeld Buxus sempervirens. Geslacht eerst.",
    timingLabel: "Snoeitiming",
    timingBorrow: "Snoei hem als een andere plant",
    timingOwn: "Zelf de timing invullen",
    borrowLabel: "Gesnoeid als",
    borrowSearch: "Zoek een plant",
    noMatches: "Geen plant gevonden met die naam",
    needBorrow: "Kies een plant uit de resultaten",
    windowStart: "Van",
    windowEnd: "Tot",
    windowWhat: "Wat te doen",
    addWindow: "Nog een periode toevoegen",
    removeWindow: "Deze periode verwijderen",
    optional: "Bron en foto (optioneel)",
    sourceLabel: "Bron-URL",
    imageLabel: "Foto-URL",
    day: "Dag",
    month: "Maand",
    manualFailed: "Kon de plant niet toevoegen",
    needBotanical: "Geef een botanische naam",
    needWindow: "Geef minstens één snoeiperiode, met wat je doet",
    badDate: "Dat is geen bestaande datum. 31 februari bestaat niet, en 29 februari kan niet worden gebruikt.",
  },
};

class GardenJournalPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    // "garden" lists the plants you have; "catalogue" browses the dataset to add
    // one. The garden is the page, adding is something you go and do.
    this._view = "garden";
    this._garden = [];
    this._gardenLoaded = false;
    this._plants = [];
    this._total = 0;
    this._query = "";
    this._loading = false;
    this._error = null;
    this._escape = null;
    this._photos = new Map();
    this._pending = new Set();
    this._timer = null;
    this._built = false;
    this._generation = 0;
  }

  set hass(hass) {
    const first = this._hass === null;
    this._hass = hass;
    if (first) {
      this._build();
      this._loadGarden();
    }
  }

  /* Look a string up in the user's language, falling back to English. */
  _t(key) {
    const language = (this._hass && this._hass.language) || "en";
    const table = STRINGS[language] || STRINGS[language.split("-")[0]];
    return (table && table[key]) || STRINGS.en[key];
  }

  set panel(_panel) {
    // Home Assistant sets this; the panel takes no config.
  }

  set narrow(narrow) {
    this._narrow = narrow;
  }

  disconnectedCallback() {
    this._closeDialog();
    for (const url of this._photos.values()) URL.revokeObjectURL(url);
    this._photos.clear();
    if (this._timer) clearTimeout(this._timer);
    if (this._photoWatcher) this._photoWatcher.disconnect();
    if (this._endWatcher) this._endWatcher.disconnect();
  }

  _build() {
    if (this._built) return;
    this._built = true;
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `
      <style>
        /* A class that sets display beats the browser's own [hidden] rule, and
           several blocks here are flex, so hiding is made to win outright. */
        [hidden] { display: none !important; }
        :host {
          display: block;
          background: var(--primary-background-color, #f5f5f5);
          color: var(--primary-text-color, #212121);
          min-height: 100vh;
          font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
        }
        header {
          background: var(--app-header-background-color, var(--primary-color, #03a9f4));
          color: var(--app-header-text-color, #fff);
          padding: 12px 20px;
          display: flex;
          align-items: center;
          gap: 12px;
          min-height: 40px;
        }
        header .title { font-size: 20px; font-weight: 500; flex: 1; }
        header button {
          font: inherit;
          cursor: pointer;
          color: inherit;
          background: transparent;
          border: none;
        }
        header .back { display: flex; padding: 4px; border-radius: 50%; }
        header .back svg { width: 24px; height: 24px; fill: currentColor; }
        header .back:hover { background: rgba(255,255,255,.16); }
        header .primary-action {
          font-size: 14px;
          font-weight: 500;
          padding: 8px 14px;
          border-radius: 8px;
          background: rgba(255,255,255,.18);
        }
        header .primary-action:hover { background: rgba(255,255,255,.3); }

        /* My garden: a dashboard of task sections, the urgent ones on top. */
        .garden-list { display: flex; flex-direction: column; gap: 26px; padding: 16px 20px 32px; }
        .section { display: flex; flex-direction: column; gap: 10px; }
        /* One column on a phone (the list that reads well there), flowing into
           more columns as the panel widens on desktop so the space is used
           without losing anything. auto-fill keeps it responsive to the panel
           width, sidebar included, with no hard breakpoint. */
        .section .rows {
          display: grid;
          gap: 10px;
          grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
        }
        .section-title { display: flex; align-items: baseline; gap: 8px; }
        .section-title .label {
          font-size: 13px;
          font-weight: 600;
          text-transform: uppercase;
          letter-spacing: .04em;
          color: var(--secondary-text-color, #727272);
        }
        .section-title .count {
          font-size: 12px;
          font-weight: 600;
          line-height: 1;
          padding: 2px 8px;
          border-radius: 999px;
          color: var(--secondary-text-color, #727272);
          background: var(--secondary-background-color, #e8e8e8);
        }
        .section-empty { margin: 0; color: var(--secondary-text-color, #727272); font-size: 14px; }
        /* Prune-now is the loudest header; care echoes the outlined-green flag;
           attention carries the warning tone. The rest stay neutral. */
        .section-prune .section-title .label { color: var(--success-color, #0b8043); }
        .section-prune .section-title .count { color: #fff; background: var(--success-color, #0b8043); }
        .section-care .section-title .label { color: var(--success-color, #43a047); }
        .section-attention .section-title .label { color: var(--warning-color, #b26a00); }
        .plant {
          display: flex;
          align-items: center;
          gap: 14px;
          padding: 10px 14px 10px 10px;
          background: var(--card-background-color, #fff);
          border-radius: 12px;
          box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,.16));
        }
        .plant .thumb {
          width: 64px;
          height: 64px;
          border-radius: 8px;
          object-fit: cover;
          flex: 0 0 auto;
          background: var(--secondary-background-color, #e8e8e8);
        }
        .plant .about { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
        .plant .name { font-size: 16px; font-weight: 500; }
        .plant .latin { font-size: 12px; font-style: italic; color: var(--secondary-text-color, #727272); }
        .plant .when { font-size: 13px; color: var(--secondary-text-color, #727272); }
        /* Care advice can run long; keep it to one line so rows stay even. */
        .plant .when.care { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .plant .flag {
          align-self: flex-start;
          margin-top: 2px;
          display: inline-flex;
          align-items: center;
          gap: 4px;
          padding: 3px 9px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 500;
          color: #fff;
          background: var(--success-color, #0b8043);
        }
        .plant .flag.attention { background: var(--warning-color, #ffa600); color: #000; }
        /* Care is a standing job, not a deadline, so it is outlined where
           prune-now is filled. Same green as the dialog's care block, so the two
           surfaces agree; a divider-coloured border was too faint to read. */
        .plant .flag.care {
          background: none;
          color: var(--success-color, #43a047);
          border: 1px solid currentColor;
        }
        .plant { cursor: pointer; }
        .plant:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
        .plant .chevron { display: flex; color: var(--secondary-text-color, #727272); }
        .plant .chevron svg { width: 22px; height: 22px; fill: currentColor; }
        .empty { margin: 28px 20px; color: var(--secondary-text-color, #727272); font-size: 15px; }
        .toolbar {
          padding: 16px 20px 8px;
          display: flex;
          align-items: center;
          gap: 16px;
        }
        input[type="search"] {
          flex: 1 1 auto;
          min-width: 0;
          max-width: 420px;
          box-sizing: border-box;
          padding: 10px 12px;
          font-size: 15px;
          color: var(--primary-text-color, #212121);
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
        }
        .grid {
          display: grid;
          gap: 16px;
          padding: 12px 20px 8px;
          grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
        }
        .card {
          background: var(--card-background-color, #fff);
          border-radius: 12px;
          overflow: hidden;
          box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,.16));
          display: flex;
          flex-direction: column;
          cursor: pointer;
        }
        .card:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
        .frame { position: relative; }
        .photo {
          aspect-ratio: 4 / 3;
          background: var(--secondary-background-color, #e8e8e8);
          object-fit: cover;
          width: 100%;
          display: block;
        }
        .photo.empty {
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 13px;
          color: var(--secondary-text-color, #727272);
        }
        /* Credit sits on the photo, over a wash dark enough to read against any
           image. */
        .credit {
          position: absolute;
          left: 0;
          right: 0;
          bottom: 0;
          padding: 14px 10px 6px;
          font-size: 11px;
          line-height: 1.3;
          color: #fff;
          text-shadow: 0 1px 2px rgba(0,0,0,.6);
          background: linear-gradient(to top, rgba(0,0,0,.62), rgba(0,0,0,0));
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        /* A badge on the photo, so what you own reads as a status rather than as
           another line of description. */
        .owned {
          position: absolute;
          top: 10px;
          left: 10px;
          display: flex;
          align-items: center;
          gap: 4px;
          padding: 4px 9px 4px 6px;
          border-radius: 999px;
          font-size: 12px;
          font-weight: 500;
          color: #fff;
          background: var(--success-color, #0b8043);
          box-shadow: 0 1px 3px rgba(0,0,0,.35);
        }
        .owned svg { width: 15px; height: 15px; fill: currentColor; }
        .body { padding: 14px 14px 14px; display: flex; flex-direction: column; gap: 4px; flex: 1; }
        .common { font-size: 16px; font-weight: 500; }
        .botanical { font-size: 13px; font-style: italic; color: var(--secondary-text-color, #727272); }
        /* The detail dialog: room for the photo, the advice and a name field,
           which a 240px card could not give the input without squeezing it. */
        .backdrop {
          position: fixed;
          inset: 0;
          z-index: 10;
          background: rgba(0,0,0,.55);
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 16px;
        }
        .dialog {
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          border-radius: 14px;
          width: min(520px, 100%);
          max-height: min(88vh, 900px);
          overflow: auto;
          box-shadow: 0 12px 32px rgba(0,0,0,.4);
        }
        .dialog .hero { position: relative; }
        .dialog .hero img, .dialog .hero .noimg {
          width: 100%;
          aspect-ratio: 16 / 10;
          object-fit: cover;
          display: block;
          background: var(--secondary-background-color, #e8e8e8);
        }
        .dialog .hero .noimg { display: flex; align-items: center; justify-content: center; font-size: 14px; color: var(--secondary-text-color, #727272); }
        .dialog .hero .credit { right: 0; }
        .dialog .content { padding: 18px 20px 20px; display: flex; flex-direction: column; gap: 12px; }
        .dialog h2 { margin: 0; font-size: 21px; font-weight: 500; }
        .dialog .sub { margin: 0; font-size: 14px; font-style: italic; color: var(--secondary-text-color, #727272); }
        .dialog .note { margin: 0; font-size: 13px; color: var(--secondary-text-color, #727272); }
        .dialog h3 {
          margin: 6px 0 0;
          font-size: 12px;
          font-weight: 600;
          letter-spacing: .06em;
          text-transform: uppercase;
          color: var(--secondary-text-color, #727272);
        }
        .window { border-left: 3px solid var(--primary-color, #03a9f4); padding-left: 12px; }
        .window .when { font-size: 14px; font-weight: 500; }
        .window .what { font-size: 13px; line-height: 1.45; color: var(--secondary-text-color, #727272); }
        /* Continuous care is a season, not a date, so it gets its own colour to
           stop it reading as another pruning job. */
        .window.care { border-left-color: var(--success-color, #43a047); }
        .window.care .when { display: flex; align-items: center; gap: 6px; }
        .window.care .open {
          font-size: 11px;
          font-weight: 600;
          letter-spacing: .04em;
          text-transform: uppercase;
          color: var(--success-color, #43a047);
        }
        .dialog a { color: var(--primary-color, #03a9f4); font-size: 13px; word-break: break-all; }
        .field { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
        .field label { font-size: 13px; font-weight: 500; }
        /* Direct children only: a radio nested in this field keeps its own size. */
        .field > input {
          width: 100%;
          box-sizing: border-box;
          padding: 10px 12px;
          font: inherit;
          font-size: 15px;
          color: var(--primary-text-color, #212121);
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #bdbdbd);
          border-radius: 8px;
        }
        .actions-row { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
        .actions-row button {
          font: inherit;
          font-size: 15px;
          padding: 10px 18px;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
        }
        .actions-row button.secondary { background: transparent; color: var(--primary-color, #03a9f4); }
        .actions-row button.danger { background: transparent; color: var(--error-color, #db4437); }
        .actions-row.spread { justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .actions-row .right { display: flex; gap: 8px; margin-left: auto; }
        .actions-row .confirm { flex: 1 1 100%; margin: 0; color: var(--primary-text-color, #212121); }

        /* Adding a plant the dataset does not cover. */
        .manual-entry { padding: 0 20px 32px; }
        button.link {
          font: inherit;
          font-size: 14px;
          padding: 0;
          border: none;
          background: none;
          cursor: pointer;
          text-decoration: underline;
          color: var(--primary-color, #03a9f4);
        }
        .dialog select, .dialog input[type="number"] {
          font: inherit;
          font-size: 15px;
          padding: 9px 10px;
          color: var(--primary-text-color, #212121);
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #bdbdbd);
          border-radius: 8px;
        }
        .modes { display: flex; flex-direction: column; gap: 6px; }
        .borrow-input {
          width: 100%;
          box-sizing: border-box;
          padding: 10px 12px;
          font: inherit;
          font-size: 15px;
          color: var(--primary-text-color, #212121);
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #bdbdbd);
          border-radius: 8px;
        }
        .results {
          display: flex;
          flex-direction: column;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
          overflow: hidden;
        }
        .results .note { margin: 0; padding: 10px 12px; }
        button.hit {
          font: inherit;
          font-size: 14px;
          text-align: left;
          padding: 10px 12px;
          border: none;
          cursor: pointer;
          background: transparent;
          color: var(--primary-text-color, #212121);
        }
        button.hit:hover { background: var(--secondary-background-color, #eee); }
        .mode { display: flex; align-items: center; gap: 8px; font-size: 14px; cursor: pointer; }
        .windows-editor { display: flex; flex-direction: column; gap: 10px; }
        .window-row {
          position: relative;
          display: flex;
          flex-wrap: wrap;
          align-items: flex-end;
          gap: 8px;
          padding: 10px 44px 10px 10px;
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 10px;
        }
        .date-group { display: flex; align-items: center; gap: 6px; }
        .date-group .small { font-size: 12px; color: var(--secondary-text-color, #727272); min-width: 26px; }
        .date-group input[type="number"] { width: 64px; }
        .what-input {
          flex: 1 1 100%;
          box-sizing: border-box;
          padding: 9px 10px;
          font: inherit;
          font-size: 15px;
          color: var(--primary-text-color, #212121);
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #bdbdbd);
          border-radius: 8px;
        }
        /* Top right of its own box, so it reads as belonging to that period. */
        button.drop {
          position: absolute;
          top: 6px;
          right: 6px;
          font-size: 18px;
          line-height: 1;
          width: 30px;
          height: 30px;
          padding: 0;
          border: none;
          border-radius: 50%;
          cursor: pointer;
          background: transparent;
          color: var(--error-color, #db4437);
        }
        button.drop:hover { background: rgba(219,68,55,.12); }
        button.add-window {
          align-self: flex-start;
          font: inherit;
          font-size: 14px;
          padding: 8px 12px;
          border: none;
          border-radius: 8px;
          cursor: pointer;
          background: transparent;
          color: var(--primary-color, #03a9f4);
        }
        .problem { color: var(--error-color, #db4437); }
        .error { margin: 16px 20px; color: var(--error-color, #db4437); }
        .end { height: 24px; }
        .more { padding: 0 20px 28px; font-size: 13px; color: var(--secondary-text-color, #727272); }
      </style>
      <header>
        <button class="back" hidden aria-label="back">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20z"/></svg>
        </button>
        <span class="title"></span>
        <button class="primary-action" hidden></button>
      </header>
      <div class="error" hidden></div>

      <section class="view-garden">
        <div class="garden-list"></div>
        <p class="empty" hidden></p>
      </section>

      <section class="view-catalogue" hidden>
        <div class="toolbar">
          <input type="search" autocomplete="off">
          <button class="link manual"></button>
        </div>
        <div class="grid"></div>
        <div class="end"></div>
        <div class="more" hidden></div>
      </section>

      <div class="dialog-host"></div>
    `;
    this.shadowRoot
      .querySelector("header .back")
      .addEventListener("click", () => this._show("garden"));
    this.shadowRoot
      .querySelector("header .primary-action")
      .addEventListener("click", () => this._show("catalogue"));

    const manual = this.shadowRoot.querySelector("button.manual");
    manual.textContent = this._t("notInList");
    manual.addEventListener("click", () => this._openManualDialog());

    const search = this.shadowRoot.querySelector("input[type=search]");
    search.placeholder = this._t("search");
    search.addEventListener("input", () => {
      this._query = search.value;
      if (this._timer) clearTimeout(this._timer);
      this._timer = setTimeout(() => this._load({ reset: true }), DEBOUNCE_MS);
    });

    // Photos load when their card scrolls into view.
    this._photoWatcher = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          this._photoWatcher.unobserve(entry.target);
          this._loadPhoto(entry.target.dataset.src);
        }
      },
      { rootMargin: "300px" },
    );

    // Reaching the end of the grid asks for the next page.
    this._endWatcher = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) this._loadMore();
      },
      { rootMargin: "400px" },
    );
    this._endWatcher.observe(this.shadowRoot.querySelector(".end"));
  }

  _show(view) {
    this._view = view;
    this._error = null;
    this._closeDialog();
    if (view === "catalogue" && this._plants.length === 0) this._load({ reset: true });
    else this._render();
    window.scrollTo(0, 0);
  }

  /* Ask the server for a list, waiting out the reload that follows a change. */
  async _request(message) {
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        return await this._hass.connection.sendMessagePromise(message);
      } catch (err) {
        if (err && err.code === "not_loaded" && attempt < 5) {
          await new Promise((resolve) => setTimeout(resolve, 400));
          continue;
        }
        throw err;
      }
    }
    return null;
  }

  async _loadGarden() {
    if (!this._hass) return;
    this._loading = true;
    this._render();
    try {
      const result = await this._request({ type: "garden_journal/garden" });
      this._garden = result.plants;
      this._gardenLoaded = true;
      this._error = null;
    } catch (err) {
      this._error = err && err.message ? err.message : this._t("loadFailed");
    }
    this._loading = false;
    this._render();
  }

  async _load({ reset } = {}) {
    if (!this._hass) return;
    if (reset) {
      this._plants = [];
      this._total = 0;
    }
    this._loading = true;
    this._error = null;
    this._render();

    const message = {
      type: "garden_journal/plants",
      limit: PAGE_SIZE,
      offset: reset ? 0 : this._plants.length,
    };
    if (this._query.trim()) message.query = this._query.trim();

    try {
      const result = await this._request(message);
      this._plants = reset ? result.plants : this._plants.concat(result.plants);
      this._total = result.total;
      this._error = null;
    } catch (err) {
      this._error = err && err.message ? err.message : this._t("loadFailed");
    }
    this._loading = false;
    this._render();
    this._rearmEndWatcher();
  }

  _loadMore() {
    if (this._loading || this._plants.length >= this._total) return;
    this._load();
  }

  /*
   * An IntersectionObserver reports changes, so a sentinel that stays in view
   * after a page is appended never reports again and the grid stops filling.
   * Re-observing asks for a fresh report, which loads the next page while the
   * sentinel is still visible and settles once it is pushed off screen or the
   * rows run out.
   */
  _rearmEndWatcher() {
    if (!this._endWatcher) return;
    if (this._plants.length >= this._total) return;
    const end = this.shadowRoot.querySelector(".end");
    this._endWatcher.unobserve(end);
    this._endWatcher.observe(end);
  }

  async _loadPhoto(src) {
    if (!src || this._photos.has(src) || this._pending.has(src)) return;
    this._pending.add(src);
    try {
      const response = await fetch(src, {
        headers: { Authorization: `Bearer ${this._hass.auth.data.access_token}` },
      });
      if (!response.ok) return;
      const url = URL.createObjectURL(await response.blob());
      this._photos.set(src, url);
      for (const img of this.shadowRoot.querySelectorAll(`img[data-src="${src}"]`)) {
        img.src = url;
      }
    } catch {
      // A photo that will not load leaves its placeholder in place.
    } finally {
      this._pending.delete(src);
    }
  }

  async _add(plant, name) {
    try {
      await this._hass.connection.sendMessagePromise({
        type: "garden_journal/add_plant",
        key: plant.key,
        name,
      });
      this._closeDialog();
      // Back to the garden, which is where the plant now is.
      this._view = "garden";
      await Promise.all([this._loadGarden(), this._load({ reset: true })]);
    } catch (err) {
      this._error = err && err.message ? err.message : this._t("addFailed");
      this._render();
    }
  }

  _render() {
    if (!this._built) return;
    const sr = this.shadowRoot;
    const error = sr.querySelector(".error");
    error.hidden = this._error === null;
    error.textContent = this._error || "";

    const catalogue = this._view === "catalogue";
    sr.querySelector(".title").textContent = catalogue
      ? this._t("addPlantTitle")
      : this._t("myGarden");
    sr.querySelector("header .back").hidden = !catalogue;
    const action = sr.querySelector("header .primary-action");
    action.hidden = catalogue;
    action.textContent = this._t("addPlantButton");
    sr.querySelector(".view-garden").hidden = catalogue;
    sr.querySelector(".view-catalogue").hidden = !catalogue;

    if (catalogue) this._renderCatalogue();
    else this._renderGarden();
  }

  /*
   * The garden is a dashboard, not one list: plants are sorted into task
   * sections so the page answers "what do I prune now", "what care is open", and
   * "what is coming up" at a glance rather than making you scan a flat column.
   * Server sort (urgent first) is preserved within each section. A plant that is
   * both pruning-now and care-open is listed in both, because each section is a
   * complete answer to its own question.
   */
  _renderGarden() {
    const list = this.shadowRoot.querySelector(".garden-list");
    const empty = this.shadowRoot.querySelector(".empty");
    list.textContent = "";
    const nothing = this._gardenLoaded && this._garden.length === 0;
    empty.hidden = !nothing;
    empty.textContent = nothing ? this._t("emptyGarden") : "";
    if (!this._gardenLoaded || nothing) return;

    const SOON_DAYS = 30;
    const pruneNow = [];
    const careNow = [];
    const soon = [];
    const attention = [];
    const other = [];
    for (const plant of this._garden) {
      // Unresolved timing has no date to bucket on, so it stands on its own.
      if (plant.needs_attention || !plant.next) {
        attention.push(plant);
        continue;
      }
      const isSoon = !plant.prune_now && this._daysUntil(plant.next) <= SOON_DAYS;
      if (plant.prune_now) pruneNow.push(plant);
      if (plant.care_now) careNow.push(plant);
      if (isSoon) soon.push(plant);
      // "Everything else" is only the idle plants: nothing open, nothing soon.
      if (!plant.prune_now && !plant.care_now && !isSoon) other.push(plant);
    }

    // The two "now" sections always show, with a reassuring line when empty, so
    // an on-top-of-it garden reads as done rather than looking broken.
    list.appendChild(
      this._section(this._t("pruneNow"), pruneNow, "prune", this._t("nothingToPrune")),
    );
    list.appendChild(
      this._section(this._t("careNow"), careNow, "care", this._t("noCareOpen")),
    );
    // The rest only appear when they hold something.
    if (soon.length) list.appendChild(this._section(this._t("secComingSoon"), soon, "soon"));
    if (attention.length) {
      list.appendChild(this._section(this._t("secAttention"), attention, "attention"));
    }
    if (other.length) list.appendChild(this._section(this._t("secOther"), other, "other"));
  }

  /* A titled section: a header with a count, then its rows or an empty line. */
  _section(title, plants, kind, emptyText) {
    const section = document.createElement("section");
    section.className = `section section-${kind}`;

    const head = document.createElement("div");
    head.className = "section-title";
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = title;
    const count = document.createElement("span");
    count.className = "count";
    count.textContent = String(plants.length);
    head.append(label, count);
    section.appendChild(head);

    if (plants.length === 0) {
      const note = document.createElement("p");
      note.className = "section-empty";
      note.textContent = emptyText || "";
      section.appendChild(note);
      return section;
    }

    const rows = document.createElement("div");
    rows.className = "rows";
    for (const plant of plants) rows.appendChild(this._plantRow(plant, kind));
    section.appendChild(rows);
    return section;
  }

  /* Whole days from today to an ISO date; negative if already past. */
  _daysUntil(iso) {
    if (!iso) return null;
    const [year, month, day] = iso.split("-").map(Number);
    const then = new Date(year, month - 1, day);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round((then - today) / 86400000);
  }

  /* A relative label for an upcoming date: today, tomorrow, or in N days. */
  _relative(iso) {
    const days = this._daysUntil(iso);
    if (days === null) return "";
    if (days <= 0) return this._t("today");
    if (days === 1) return this._t("tomorrow");
    return this._t("inDays")(days);
  }

  _plantRow(plant, context) {
    const row = document.createElement("div");
    row.className = "plant";
    row.tabIndex = 0;
    row.setAttribute("role", "button");
    row.setAttribute("aria-label", plant.name);
    row.addEventListener("click", () => this._openGardenDialog(plant));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this._openGardenDialog(plant);
      }
    });

    const thumb = document.createElement("img");
    thumb.className = "thumb";
    thumb.alt = "";
    thumb.loading = "lazy";
    thumb.decoding = "async";
    // Through the cached photo proxy (immutable + ETag), not the image entity's
    // rotating token, so a reload serves thumbnails from the browser cache
    // instead of refetching every one. Loaded when the row scrolls into view.
    if (plant.photo) {
      thumb.dataset.src = plant.photo;
      const cached = this._photos.get(plant.photo);
      if (cached) thumb.src = cached;
      else this._photoWatcher.observe(thumb);
    }
    row.appendChild(thumb);

    const about = document.createElement("div");
    about.className = "about";
    const name = document.createElement("div");
    name.className = "name";
    name.textContent = plant.name;
    const latin = document.createElement("div");
    latin.className = "latin";
    latin.textContent = plant.botanical;
    about.append(name, latin);
    this._statusLine(about, plant, context);
    row.appendChild(about);

    const chevron = document.createElement("div");
    chevron.className = "chevron";
    chevron.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.59 16.59 13.17 12 8.59 7.41 10 6l6 6-6 6z"/></svg>';
    row.appendChild(chevron);
    return row;
  }

  /*
   * The one status line a row shows depends on the section it sits in, so each
   * row speaks to that section's question instead of stacking every flag. The
   * full advice rides along in the title tooltip.
   */
  _statusLine(about, plant, context) {
    if (context === "attention") {
      const flag = document.createElement("span");
      flag.className = "flag attention";
      flag.textContent = this._t("unknownTiming");
      about.appendChild(flag);
      return;
    }
    if (context === "prune") {
      const flag = document.createElement("span");
      flag.className = "flag";
      flag.textContent = this._t("pruneNow");
      about.appendChild(flag);
      const when = document.createElement("div");
      when.className = "when";
      when.textContent = this._t("until")(this._date(plant.end));
      when.title = plant.advice || "";
      about.appendChild(when);
      return;
    }
    if (context === "care") {
      // The end of the open season, shown like pruning's "until <date>" so both
      // sections read the same way.
      if (plant.care_end) {
        const until = document.createElement("div");
        until.className = "when";
        until.textContent = this._t("until")(this._date(plant.care_end));
        about.appendChild(until);
      }
      const text = plant.care.map((season) => season.description).join(" ");
      const advice = document.createElement("div");
      advice.className = "when care";
      advice.textContent = text;
      advice.title = text;
      about.appendChild(advice);
      return;
    }
    if (context === "soon") {
      const when = document.createElement("div");
      when.className = "when";
      when.textContent = `${this._relative(plant.next)}, ${this._date(plant.next)}`;
      when.title = plant.advice || "";
      about.appendChild(when);
      return;
    }
    // "other": idle plants, shown with their next pruning date.
    const when = document.createElement("div");
    when.className = "when";
    when.textContent = `${this._t("nextPruning")}: ${this._date(plant.next)}`;
    when.title = plant.advice || "";
    about.appendChild(when);
  }

  _date(iso) {
    if (!iso) return "";
    const [year, month, day] = iso.split("-").map(Number);
    const language = (this._hass && this._hass.language) || "en";
    try {
      return new Date(year, month - 1, day).toLocaleDateString(language, {
        day: "numeric",
        month: "long",
        year: "numeric",
      });
    } catch {
      return `${day} ${this._t("months")[month - 1]} ${year}`;
    }
  }

  _renderCatalogue() {
    const grid = this.shadowRoot.querySelector(".grid");
    const more = this.shadowRoot.querySelector(".more");

    const remaining = this._total - this._plants.length;
    more.hidden = remaining <= 0;
    more.textContent = this._loading
      ? this._t("loadingMore")
      : this._t("more")(remaining);

    grid.textContent = "";
    for (const plant of this._plants) {
      grid.appendChild(this._card(plant));
    }
  }

  _card(plant) {
    const card = document.createElement("div");
    card.className = "card";
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    card.setAttribute("aria-label", plant.common);
    card.addEventListener("click", () => this._openCatalogueDialog(plant));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this._openCatalogueDialog(plant);
      }
    });

    const frame = document.createElement("div");
    frame.className = "frame";

    if (plant.photo) {
      const img = document.createElement("img");
      img.className = "photo";
      img.alt = plant.common;
      img.dataset.src = plant.photo;
      const cached = this._photos.get(plant.photo);
      if (cached) {
        img.src = cached;
      } else {
        this._photoWatcher.observe(img);
      }
      frame.appendChild(img);

      if (plant.credit) {
        const credit = document.createElement("div");
        credit.className = "credit";
        credit.textContent = this._t("photo")(plant.credit);
        credit.title = plant.credit;
        frame.appendChild(credit);
      }
    } else {
      const empty = document.createElement("div");
      empty.className = "photo empty";
      empty.textContent = this._t("noPhoto");
      frame.appendChild(empty);
    }

    if (plant.added) frame.appendChild(this._ownedBadge(plant));
    card.appendChild(frame);

    const body = document.createElement("div");
    body.className = "body";

    const common = document.createElement("div");
    common.className = "common";
    common.textContent = plant.common;
    body.appendChild(common);

    const botanical = document.createElement("div");
    botanical.className = "botanical";
    botanical.textContent = plant.botanical;
    body.appendChild(botanical);

    card.appendChild(body);
    return card;
  }

  _ownedBadge(plant) {
    const badge = document.createElement("div");
    badge.className = "owned";
    badge.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>';
    const label = document.createElement("span");
    label.textContent =
      plant.added > 1 ? this._t("plantedTimes")(plant.added) : this._t("planted");
    badge.appendChild(label);
    badge.title =
      plant.added > 1
        ? this._t("plantedTitleTimes")(plant.added)
        : this._t("plantedTitle");
    return badge;
  }

  _monthDay(value) {
    const [month, day] = value.split("-").map(Number);
    return `${day} ${this._t("months")[month - 1]}`;
  }

  /*
   * One block of advice: a date range and what to do in it. Pruning windows and
   * care seasons look the same and mean different things, so care is marked, and
   * an open care season says so rather than making the reader compare dates.
   */
  _spanBlock(span, { care = false, open = false } = {}) {
    const block = document.createElement("div");
    block.className = care ? "window care" : "window";
    const when = document.createElement("div");
    when.className = "when";
    when.textContent = this._t("range")(
      this._monthDay(span.start),
      this._monthDay(span.end),
    );
    if (open) {
      const flag = document.createElement("span");
      flag.className = "open";
      flag.textContent = this._t("careOpen");
      when.appendChild(flag);
    }
    const what = document.createElement("div");
    what.className = "what";
    what.textContent = span.description;
    block.append(when, what);
    return block;
  }

  /*
   * Both dialogs show the same plant, so they share everything above the buttons:
   * the photo, the names, the pruning windows, the continuous care and the source.
   * Only the name field and the actions differ, which `build` fills in.
   */
  _openDialog({ title, botanical, hint, photoSrc, photoEntity, credit, windows, care, careNow, source, badge, nameValue, build }) {
    this._closeDialog();
    const host = this.shadowRoot.querySelector(".dialog-host");

    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) this._closeDialog();
    });

    const dialog = document.createElement("div");
    dialog.className = "dialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", title);

    const hero = document.createElement("div");
    hero.className = "hero";
    const picture =
      photoEntity &&
      this._hass.states[photoEntity] &&
      this._hass.states[photoEntity].attributes.entity_picture;
    if (photoSrc || picture) {
      const img = document.createElement("img");
      img.alt = title;
      if (picture) {
        img.src = picture;
      } else {
        img.dataset.src = photoSrc;
        const cached = this._photos.get(photoSrc);
        if (cached) img.src = cached;
        else this._loadPhoto(photoSrc);
      }
      hero.appendChild(img);
      if (credit) {
        const line = document.createElement("div");
        line.className = "credit";
        line.textContent = this._t("photo")(credit);
        hero.appendChild(line);
      }
    } else {
      const empty = document.createElement("div");
      empty.className = "noimg";
      empty.textContent = this._t("noPhoto");
      hero.appendChild(empty);
    }
    if (badge) hero.appendChild(badge);
    dialog.appendChild(hero);

    const content = document.createElement("div");
    content.className = "content";

    const heading = document.createElement("h2");
    heading.textContent = title;
    content.appendChild(heading);

    const sub = document.createElement("p");
    sub.className = "sub";
    sub.textContent = botanical;
    content.appendChild(sub);

    if (hint) {
      const note = document.createElement("p");
      note.className = "note";
      note.textContent = hint;
      content.appendChild(note);
    }

    if (windows && windows.length) {
      const label = document.createElement("h3");
      label.textContent = this._t("pruning");
      content.appendChild(label);
      for (const window of windows) {
        content.appendChild(this._spanBlock(window));
      }
    }

    if (care && care.length) {
      const label = document.createElement("h3");
      label.textContent = this._t("care");
      content.appendChild(label);
      for (const season of care) {
        content.appendChild(
          this._spanBlock(season, { care: true, open: Boolean(careNow) }),
        );
      }
    }

    if (source) {
      const label = document.createElement("h3");
      label.textContent = this._t("source");
      const link = document.createElement("a");
      link.href = source;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      link.textContent = source;
      content.append(label, link);
    }

    const field = document.createElement("div");
    field.className = "field";
    const label = document.createElement("label");
    label.textContent = this._t("nameLabel");
    label.htmlFor = "plant-name";
    const input = document.createElement("input");
    input.type = "text";
    input.id = "plant-name";
    input.value = nameValue;
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = this._t("nameHint");
    field.append(label, input, note);
    content.appendChild(field);

    content.appendChild(build(input, content));

    dialog.appendChild(content);
    backdrop.appendChild(dialog);
    host.appendChild(backdrop);

    this._escape = (event) => {
      if (event.key === "Escape") this._closeDialog();
    };
    window.addEventListener("keydown", this._escape);
    setTimeout(() => input.focus(), 0);
  }

  _openCatalogueDialog(plant) {
    this._openDialog({
      title: plant.common,
      botanical: plant.botanical,
      photoSrc: plant.photo,
      credit: plant.credit,
      windows: plant.windows,
      care: plant.care,
      source: plant.source,
      badge: plant.added ? this._ownedBadge(plant) : null,
      nameValue: plant.common,
      build: (input) => {
        const actions = document.createElement("div");
        actions.className = "actions-row";
        const cancel = document.createElement("button");
        cancel.className = "secondary";
        cancel.textContent = this._t("cancel");
        cancel.addEventListener("click", () => this._closeDialog());
        const confirm = document.createElement("button");
        confirm.textContent = this._t("add");
        confirm.addEventListener("click", () => this._add(plant, input.value));
        input.addEventListener("keydown", (event) => {
          if (event.key === "Enter") this._add(plant, input.value);
        });
        actions.append(cancel, confirm);
        return actions;
      },
    });
  }

  _openGardenDialog(plant) {
    this._openDialog({
      title: plant.name,
      botanical: plant.botanical,
      hint: plant.in_dataset ? null : this._t("manualPlant"),
      photoSrc: plant.photo,
      credit: plant.credit,
      windows: plant.windows,
      care: plant.care,
      careNow: plant.care_now,
      source: plant.source,
      badge: null,
      nameValue: plant.name,
      build: (input) => {
        const actions = document.createElement("div");
        actions.className = "actions-row spread";

        const remove = document.createElement("button");
        remove.className = "danger";
        remove.textContent = this._t("remove");

        const right = document.createElement("div");
        right.className = "right";
        const cancel = document.createElement("button");
        cancel.className = "secondary";
        cancel.textContent = this._t("cancel");
        cancel.addEventListener("click", () => this._closeDialog());
        const save = document.createElement("button");
        save.textContent = this._t("save");
        save.addEventListener("click", () => this._rename(plant, input.value));
        input.addEventListener("keydown", (event) => {
          if (event.key === "Enter") this._rename(plant, input.value);
        });
        right.append(cancel, save);

        // Confirming in place, rather than stacking a second dialog on this one.
        remove.addEventListener("click", () => {
          actions.textContent = "";
          const question = document.createElement("p");
          question.className = "note confirm";
          question.textContent = this._t("confirmRemove")(plant.name);
          const keep = document.createElement("button");
          keep.className = "secondary";
          keep.textContent = this._t("cancel");
          keep.addEventListener("click", () => this._closeDialog());
          const yes = document.createElement("button");
          yes.className = "danger";
          yes.textContent = this._t("confirmYes");
          yes.addEventListener("click", () => this._remove(plant));
          const row = document.createElement("div");
          row.className = "right";
          row.append(keep, yes);
          actions.append(question, row);
        });

        actions.append(remove, right);
        return actions;
      },
    });
  }

  /* A plant the dataset does not cover: named here, with timing borrowed or written. */
  _openManualDialog() {
    this._closeDialog();
    const host = this.shadowRoot.querySelector(".dialog-host");
    const backdrop = document.createElement("div");
    backdrop.className = "backdrop";
    backdrop.addEventListener("click", (event) => {
      if (event.target === backdrop) this._closeDialog();
    });

    const dialog = document.createElement("div");
    dialog.className = "dialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-label", this._t("manualTitle"));

    const content = document.createElement("div");
    content.className = "content";

    const heading = document.createElement("h2");
    heading.textContent = this._t("manualTitle");
    const intro = document.createElement("p");
    intro.className = "note";
    intro.textContent = this._t("manualIntro");
    content.append(heading, intro);

    const problem = document.createElement("p");
    problem.className = "note problem";
    problem.hidden = true;
    content.appendChild(problem);

    const name = this._textField(this._t("nameLabel"), "");
    const botanical = this._textField(
      this._t("botanicalLabel"),
      this._t("botanicalHint"),
    );
    content.append(name.wrap, botanical.wrap);

    // Borrowing or writing the timing, one or the other.
    const choice = document.createElement("div");
    choice.className = "field";
    const choiceLabel = document.createElement("label");
    choiceLabel.textContent = this._t("timingLabel");
    const modes = document.createElement("div");
    modes.className = "modes";
    const borrowMode = this._radio("timing", this._t("timingBorrow"), true);
    const ownMode = this._radio("timing", this._t("timingOwn"), false);
    modes.append(borrowMode.wrap, ownMode.wrap);
    choice.append(choiceLabel, modes);
    content.appendChild(choice);

    const borrow = this._borrowPicker();
    content.appendChild(borrow.wrap);

    const ownBox = document.createElement("div");
    ownBox.className = "windows-editor";
    ownBox.hidden = true;
    const rows = document.createElement("div");
    const addRow = document.createElement("button");
    addRow.className = "secondary add-window";
    addRow.textContent = this._t("addWindow");
    addRow.addEventListener("click", () => {
      rows.appendChild(this._windowRow(rows));
      this._syncWindowRows(rows);
    });
    ownBox.append(rows, addRow);
    rows.appendChild(this._windowRow(rows));
    this._syncWindowRows(rows);
    content.appendChild(ownBox);

    const source = this._textField(this._t("sourceLabel"), "");
    const image = this._textField(this._t("imageLabel"), "");
    const extras = document.createElement("div");
    extras.className = "field";
    const extrasLabel = document.createElement("h3");
    extrasLabel.textContent = this._t("optional");
    extras.append(extrasLabel, source.wrap, image.wrap);
    ownBox.appendChild(extras);

    const swap = () => {
      const own = ownMode.input.checked;
      ownBox.hidden = !own;
      borrow.wrap.hidden = own;
    };
    borrowMode.input.addEventListener("change", swap);
    ownMode.input.addEventListener("change", swap);

    const actions = document.createElement("div");
    actions.className = "actions-row";
    const cancel = document.createElement("button");
    cancel.className = "secondary";
    cancel.textContent = this._t("cancel");
    cancel.addEventListener("click", () => this._closeDialog());
    const confirm = document.createElement("button");
    confirm.textContent = this._t("add");
    confirm.addEventListener("click", () =>
      this._addManual({
        problem,
        name: name.input.value,
        botanical: botanical.input.value,
        own: ownMode.input.checked,
        borrowKey: borrow.key(),
        rows,
        source: source.input.value,
        imageUrl: image.input.value,
      }),
    );
    actions.append(cancel, confirm);
    content.appendChild(actions);

    dialog.appendChild(content);
    backdrop.appendChild(dialog);
    host.appendChild(backdrop);
    this._escape = (event) => {
      if (event.key === "Escape") this._closeDialog();
    };
    window.addEventListener("keydown", this._escape);
    setTimeout(() => name.input.focus(), 0);
  }

  /*
   * Picking a plant to borrow timing from, by searching rather than by listing.
   * The dataset is meant to grow, so the search runs on the server and only a
   * handful of matches come back. A key is only set by choosing a match, so a
   * half-typed name cannot pass for a choice.
   */
  _borrowPicker() {
    const wrap = document.createElement("div");
    wrap.className = "field borrow";
    const label = document.createElement("label");
    label.textContent = this._t("borrowLabel");
    const input = document.createElement("input");
    input.type = "search";
    input.className = "borrow-input";
    input.placeholder = this._t("borrowSearch");
    input.autocomplete = "off";
    const results = document.createElement("div");
    results.className = "results";
    results.hidden = true;
    wrap.append(label, input, results);

    let chosen = null;
    let timer = null;

    const show = (plants) => {
      results.textContent = "";
      if (!plants.length) {
        const none = document.createElement("p");
        none.className = "note";
        none.textContent = this._t("noMatches");
        results.appendChild(none);
      }
      for (const plant of plants) {
        const hit = document.createElement("button");
        hit.className = "hit";
        hit.textContent = `${plant.common} (${plant.botanical})`;
        hit.addEventListener("click", () => {
          chosen = plant.key;
          input.value = `${plant.common} (${plant.botanical})`;
          results.hidden = true;
        });
        results.appendChild(hit);
      }
      results.hidden = false;
    };

    const search = async () => {
      const query = input.value.trim();
      if (!query) {
        results.hidden = true;
        return;
      }
      try {
        const result = await this._request({
          type: "garden_journal/plants",
          query,
          limit: 8,
        });
        show(result.plants);
      } catch {
        results.hidden = true;
      }
    };

    input.addEventListener("input", () => {
      chosen = null;
      if (timer) clearTimeout(timer);
      timer = setTimeout(search, DEBOUNCE_MS);
    });

    return { wrap, key: () => chosen };
  }

  _textField(labelText, hintText) {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const label = document.createElement("label");
    label.textContent = labelText;
    const input = document.createElement("input");
    input.type = "text";
    wrap.append(label, input);
    if (hintText) {
      const hint = document.createElement("p");
      hint.className = "note";
      hint.textContent = hintText;
      wrap.appendChild(hint);
    }
    return { wrap, input };
  }

  _radio(group, labelText, checked) {
    const wrap = document.createElement("label");
    wrap.className = "mode";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = group;
    input.checked = checked;
    const text = document.createElement("span");
    text.textContent = labelText;
    wrap.append(input, text);
    return { wrap, input };
  }

  _monthSelect() {
    const select = document.createElement("select");
    this._t("months").forEach((month, index) => {
      const option = document.createElement("option");
      option.value = String(index + 1);
      option.textContent = month;
      select.appendChild(option);
    });
    return select;
  }

  _windowRow(container) {
    const row = document.createElement("div");
    row.className = "window-row";

    const build = (labelText) => {
      const group = document.createElement("div");
      group.className = "date-group";
      const label = document.createElement("span");
      label.className = "small";
      label.textContent = labelText;
      const month = this._monthSelect();
      const day = document.createElement("input");
      day.type = "number";
      day.min = "1";
      day.max = "31";
      day.value = "1";
      day.setAttribute("aria-label", this._t("day"));
      group.append(label, month, day);
      return { group, month, day };
    };

    const from = build(this._t("windowStart"));
    const until = build(this._t("windowEnd"));

    const what = document.createElement("input");
    what.type = "text";
    what.className = "what-input";
    what.placeholder = this._t("windowWhat");

    const drop = document.createElement("button");
    drop.className = "danger drop";
    drop.title = this._t("removeWindow");
    drop.setAttribute("aria-label", this._t("removeWindow"));
    drop.textContent = "×";
    drop.addEventListener("click", () => {
      row.remove();
      this._syncWindowRows(container);
    });

    row.append(from.group, until.group, what, drop);
    row._fields = { from, until, what };
    return row;
  }

  /* The first period is the plant's timing, so only the extras can be dropped. */
  _syncWindowRows(container) {
    container.querySelectorAll(".window-row").forEach((row, index) => {
      row.querySelector(".drop").hidden = index === 0;
    });
  }

  async _addManual({ problem, name, botanical, own, borrowKey, rows, source, imageUrl }) {
    const pad = (value) => String(value).padStart(2, "0");
    const fail = (key) => {
      problem.hidden = false;
      problem.textContent = this._t(key);
    };
    if (!name.trim() || !botanical.trim()) {
      fail("needBotanical");
      return;
    }

    const message = {
      type: "garden_journal/add_manual_plant",
      name: name.trim(),
      botanical: botanical.trim(),
    };

    if (own) {
      const windows = [];
      for (const row of rows.querySelectorAll(".window-row")) {
        const { from, until, what } = row._fields;
        if (!what.value.trim()) {
          fail("needWindow");
          return;
        }
        const days = [Number(from.day.value), Number(until.day.value)];
        if (days.some((day) => !Number.isInteger(day) || day < 1 || day > 31)) {
          fail("badDate");
          return;
        }
        windows.push({
          start: `${pad(from.month.value)}-${pad(from.day.value)}`,
          end: `${pad(until.month.value)}-${pad(until.day.value)}`,
          description: what.value.trim(),
        });
      }
      if (!windows.length) {
        fail("needWindow");
        return;
      }
      message.windows = windows;
      if (source.trim()) message.source = source.trim();
      if (imageUrl.trim()) message.image_url = imageUrl.trim();
    } else {
      if (!borrowKey) {
        fail("needBorrow");
        return;
      }
      message.borrow_key = borrowKey;
    }

    try {
      await this._hass.connection.sendMessagePromise(message);
      this._closeDialog();
      this._view = "garden";
      this._plants = [];
      await Promise.all([this._loadGarden(), this._load({ reset: true })]);
    } catch (err) {
      if (err && err.code === "invalid_date") fail("badDate");
      else if (err && err.code === "missing_description") fail("needWindow");
      else {
        problem.hidden = false;
        problem.textContent =
          err && err.message ? err.message : this._t("manualFailed");
      }
    }
  }

  async _rename(plant, name) {
    const trimmed = (name || "").trim();
    if (!trimmed) return;
    try {
      await this._hass.connection.sendMessagePromise({
        type: "garden_journal/rename_plant",
        subentry_id: plant.subentry_id,
        name: trimmed,
      });
      this._closeDialog();
      await this._loadGarden();
    } catch (err) {
      this._error = err && err.message ? err.message : this._t("renameFailed");
      this._render();
    }
  }

  async _remove(plant) {
    try {
      await this._hass.connection.sendMessagePromise({
        type: "garden_journal/remove_plant",
        subentry_id: plant.subentry_id,
      });
      this._closeDialog();
      this._plants = [];
      await this._loadGarden();
    } catch (err) {
      this._error = err && err.message ? err.message : this._t("removeFailed");
      this._render();
    }
  }

  _closeDialog() {
    const host = this.shadowRoot && this.shadowRoot.querySelector(".dialog-host");
    if (host) host.textContent = "";
    if (this._escape) {
      window.removeEventListener("keydown", this._escape);
      this._escape = null;
    }
  }
}

customElements.define("garden-journal-panel", GardenJournalPanel);
