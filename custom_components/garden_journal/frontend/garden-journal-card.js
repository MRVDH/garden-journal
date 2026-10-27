/*
 * Garden Journal dashboard card.
 *
 * A compact list for a dashboard: what needs doing now (pruning windows that are
 * open and care seasons that are running) and which windows open in the coming
 * days. Tapping the card opens the Garden Journal panel, where the detail lives.
 *
 * Like the panel, this is a plain custom element with no build step. The
 * integration loads it on every dashboard, so it registers itself in the card
 * picker and needs no resource added by hand. Its data comes from the same
 * `garden_journal/garden` command the panel uses.
 *
 *   type: custom:garden-journal-card
 *   days: 30        # how far ahead "Coming up" looks, default 30
 *   title: Garden   # optional, defaults to "Garden Journal"
 */

const PANEL_PATH = "/garden_journal";
const DEFAULT_DAYS = 30;
// In spring most of a large garden opens at once, which would make the card
// longer than the dashboard around it. The panel has the full list.
const MAX_ROWS = 5;
// The list changes when a plant is added or removed and when the day rolls over.
// A day change is caught as soon as Home Assistant updates the card; this covers
// plants changed elsewhere while the dashboard stays open.
const REFRESH_MS = 30 * 60 * 1000;
// After a failed fetch, how long Home Assistant's updates wait before the next
// try. They come several times a second, and the integration may stay unloaded.
const RETRY_MS = 30 * 1000;
const DAY_MS = 86400000;

const STRINGS = {
  en: {
    title: "Garden Journal",
    now: "Now",
    comingUp: "Coming up",
    prune: "Prune",
    care: "Care",
    until: (date) => `until ${date}`,
    today: "today",
    tomorrow: "tomorrow",
    inDays: (n) => `in ${n} days`,
    nothingNow: "Nothing to prune or care for today",
    nothingSoon: (n) => `Nothing opens in the next ${n} days`,
    more: (n) => `and ${n} more`,
    loading: "Loading",
    notLoaded: "Garden Journal is not loaded",
    loadFailed: "Could not load the garden",
    open: "Open Garden Journal",
    daysAhead: "Coming up: days ahead",
    daysUnit: "days",
  },
  nl: {
    title: "Garden Journal",
    now: "Nu",
    comingUp: "Binnenkort",
    prune: "Snoeien",
    care: "Onderhoud",
    until: (date) => `tot ${date}`,
    today: "vandaag",
    tomorrow: "morgen",
    inDays: (n) => `over ${n} dagen`,
    nothingNow: "Vandaag hoeft er niets gesnoeid of onderhouden te worden",
    nothingSoon: (n) => `De komende ${n} dagen begint er niets`,
    more: (n) => `en nog ${n}`,
    loading: "Laden",
    notLoaded: "Garden Journal is niet geladen",
    loadFailed: "Kon de tuin niet laden",
    open: "Garden Journal openen",
    daysAhead: "Binnenkort: dagen vooruit",
    daysUnit: "dagen",
  },
};

/* Look a string up in a language, falling back to English. */
function lookup(language, key) {
  const table = STRINGS[language] || STRINGS[language.split("-")[0]];
  return (table && table[key]) || STRINGS.en[key];
}

class GardenJournalCard extends HTMLElement {
  constructor() {
    super();
    this._config = { days: DEFAULT_DAYS };
    this._hass = null;
    this._plants = null;
    this._error = null;
    this._fetchedDay = null;
    this._fetching = false;
    this._retryAt = 0;
    this._timer = null;
  }

  /* What the card picker inserts when the card is added from the UI. */
  static getStubConfig() {
    return { days: DEFAULT_DAYS };
  }

  /*
   * The visual editor: Home Assistant builds the form from this schema. It gets
   * no hass here, so the language comes from the frontend's root element. The
   * title label is left to Home Assistant, which translates "title" itself.
   */
  static getConfigForm() {
    const root = document.querySelector("home-assistant");
    const t = (key) => lookup((root && root.hass && root.hass.language) || "en", key);
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        {
          name: "days",
          default: DEFAULT_DAYS,
          selector: {
            number: { min: 1, max: 365, mode: "box", unit_of_measurement: t("daysUnit") },
          },
        },
      ],
      computeLabel: (schema) => (schema.name === "days" ? t("daysAhead") : undefined),
    };
  }

  setConfig(config) {
    const days = config.days === undefined ? DEFAULT_DAYS : Number(config.days);
    if (!Number.isInteger(days) || days < 1) {
      throw new Error("days must be a whole number of at least 1");
    }
    this._config = { ...config, days };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Home Assistant sets this on every state change, so only a new day, the
    // first set or a due retry fetches; the timer covers the rest.
    if (this._stale()) this._refresh();
  }

  connectedCallback() {
    if (!this._timer) this._timer = setInterval(() => this._refresh(), REFRESH_MS);
    if (this._hass && this._stale()) this._refresh();
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
  }

  /* Roughly one row per line shown plus the headers, for the masonry layout. */
  getCardSize() {
    const { now, soon } = this._lists();
    const lines = (jobs) => Math.max(Math.min(jobs.length, MAX_ROWS + 1), 1);
    return 2 + lines(now) + lines(soon);
  }

  _t(key) {
    return lookup((this._hass && this._hass.language) || "en", key);
  }

  _dayKey() {
    return new Date().toDateString();
  }

  /* Whether the list is not from today, and a failed fetch is not still cooling down. */
  _stale() {
    return this._fetchedDay !== this._dayKey() && Date.now() >= this._retryAt;
  }

  async _refresh() {
    if (!this._hass || this._fetching) return;
    this._fetching = true;
    try {
      const result = await this._hass.connection.sendMessagePromise({
        type: "garden_journal/garden",
      });
      this._plants = result.plants;
      this._error = null;
      this._fetchedDay = this._dayKey();
      this._retryAt = 0;
    } catch (err) {
      // A reload after a plant change briefly reports not_loaded; the first
      // update after RETRY_MS tries again, since the day key was not recorded.
      this._retryAt = Date.now() + RETRY_MS;
      this._error = err && err.code === "not_loaded" ? this._t("notLoaded") : this._t("loadFailed");
    }
    this._fetching = false;
    this._render();
  }

  /* Whole days from today to an ISO date; negative if already past. */
  _daysUntil(iso) {
    const [year, month, day] = iso.split("-").map(Number);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    return Math.round((new Date(year, month - 1, day) - today) / DAY_MS);
  }

  /*
   * The next date each pruning window opens, after today, as YYYY-MM-DD. A
   * window that opens today is already open, so its next opening is a year on;
   * the same goes for one that started earlier this year, including a window
   * that wraps past New Year and is still open.
   */
  _nextStarts(plant) {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    return (plant.windows || []).map((span) => {
      const [month, day] = span.start.split("-").map(Number);
      const thisYear = new Date(now.getFullYear(), month - 1, day);
      const year = thisYear > now ? now.getFullYear() : now.getFullYear() + 1;
      return `${year}-${pad(month)}-${pad(day)}`;
    });
  }

  _date(iso) {
    const [year, month, day] = iso.split("-").map(Number);
    const language = (this._hass && this._hass.language) || "en";
    try {
      return new Date(year, month - 1, day).toLocaleDateString(language, {
        day: "numeric",
        month: "short",
      });
    } catch {
      return iso;
    }
  }

  _relative(iso) {
    const days = this._daysUntil(iso);
    if (days <= 0) return this._t("today");
    if (days === 1) return this._t("tomorrow");
    return this._t("inDays")(days);
  }

  /*
   * "Now" holds one row per open job, so a plant that is being pruned and
   * deadheaded at once shows both. "Coming up" is pruning windows only: care is
   * a standing state rather than a date to plan for, the same split the panel
   * and the calendar make. Each pruning window gets its own row, so a plant
   * can be in "Now" for one window and in "Coming up" for another.
   */
  _lists() {
    const now = [];
    const soon = [];
    for (const plant of this._plants || []) {
      if (plant.prune_now && plant.end) {
        now.push({ plant, kind: "prune", detail: this._t("until")(this._date(plant.end)) });
      }
      if (plant.care_now) {
        const until = plant.care_end ? this._t("until")(this._date(plant.care_end)) : "";
        now.push({ plant, kind: "care", detail: until });
      }
      for (const start of this._nextStarts(plant)) {
        const days = this._daysUntil(start);
        if (days <= this._config.days) {
          soon.push({
            plant,
            kind: "soon",
            days,
            detail: `${this._relative(start)}, ${this._date(start)}`,
          });
        }
      }
    }
    now.sort((a, b) => (a.kind === b.kind ? 0 : a.kind === "prune" ? -1 : 1));
    soon.sort((a, b) => a.days - b.days);
    return { now, soon };
  }

  _open() {
    history.pushState(null, "", PANEL_PATH);
    window.dispatchEvent(new CustomEvent("location-changed", { detail: { replace: false } }));
  }

  _render() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `
        <style>
          ha-card { display: block; padding: 4px 0 8px; cursor: pointer; }
          ha-card:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
          .title { padding: 12px 16px 4px; font-size: 20px; font-weight: 500; }
          .head {
            padding: 10px 16px 4px;
            font-size: 12px;
            font-weight: 600;
            letter-spacing: .04em;
            text-transform: uppercase;
            color: var(--secondary-text-color, #727272);
          }
          .row { display: flex; align-items: center; gap: 12px; padding: 6px 16px; }
          .chip {
            flex: 0 0 auto;
            min-width: 64px;
            box-sizing: border-box;
            text-align: center;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 12px;
            font-weight: 500;
          }
          .chip.prune { color: #fff; background: var(--success-color, #0b8043); }
          .chip.care { color: var(--success-color, #43a047); border: 1px solid currentColor; }
          .chip.soon { color: var(--primary-color, #03a9f4); border: 1px solid currentColor; }
          .text { min-width: 0; display: flex; flex-direction: column; }
          .name { font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .detail { font-size: 12px; color: var(--secondary-text-color, #727272); }
          .empty, .status { padding: 4px 16px 6px; font-size: 13px; color: var(--secondary-text-color, #727272); }
          .more { padding: 4px 16px 6px 92px; font-size: 13px; color: var(--secondary-text-color, #727272); }
          .status.error { color: var(--error-color, #db4437); }
        </style>
        <ha-card tabindex="0" role="button"><div class="body"></div></ha-card>
      `;
      const card = this.shadowRoot.querySelector("ha-card");
      card.addEventListener("click", () => this._open());
      card.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          this._open();
        }
      });
    }

    const card = this.shadowRoot.querySelector("ha-card");
    card.setAttribute("aria-label", this._t("open"));
    const body = this.shadowRoot.querySelector(".body");
    body.textContent = "";

    const title = document.createElement("div");
    title.className = "title";
    title.textContent = this._config.title || this._t("title");
    body.appendChild(title);

    if (this._plants === null) {
      body.appendChild(this._line(this._error || this._t("loading"), this._error ? "status error" : "status"));
      return;
    }

    const { now, soon } = this._lists();
    body.appendChild(this._line(this._t("now"), "head"));
    if (now.length) this._rows(body, now);
    else body.appendChild(this._line(this._t("nothingNow"), "empty"));

    body.appendChild(this._line(this._t("comingUp"), "head"));
    if (soon.length) this._rows(body, soon);
    else body.appendChild(this._line(this._t("nothingSoon")(this._config.days), "empty"));

    // A failed refresh keeps the last good list and says so underneath.
    if (this._error) body.appendChild(this._line(this._error, "status error"));
  }

  /*
   * The first rows of a list and a count of the rest. Six rows take the same
   * space as five and a "1 more" line, so a list is only cut when that saves a
   * row.
   */
  _rows(body, jobs) {
    const shown = jobs.length > MAX_ROWS + 1 ? jobs.slice(0, MAX_ROWS) : jobs;
    for (const job of shown) body.appendChild(this._row(job));
    if (shown.length < jobs.length) {
      body.appendChild(this._line(this._t("more")(jobs.length - shown.length), "more"));
    }
  }

  _line(text, className) {
    const line = document.createElement("div");
    line.className = className;
    line.textContent = text;
    return line;
  }

  _row({ plant, kind, detail }) {
    const row = document.createElement("div");
    row.className = "row";
    const chip = document.createElement("span");
    chip.className = `chip ${kind}`;
    chip.textContent = kind === "care" ? this._t("care") : this._t("prune");
    const text = document.createElement("div");
    text.className = "text";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = plant.name;
    text.appendChild(name);
    if (detail) text.appendChild(this._line(detail, "detail"));
    row.append(chip, text);
    return row;
  }
}

// A browser holding an older copy of the module from before an upgrade may load
// both; defining the element twice throws, so the second copy steps aside.
if (!customElements.get("garden-journal-card")) {
  customElements.define("garden-journal-card", GardenJournalCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "garden-journal-card",
    name: "Garden Journal",
    description: "What to prune or care for now, and what comes up in the next days.",
    preview: true,
  });
}
