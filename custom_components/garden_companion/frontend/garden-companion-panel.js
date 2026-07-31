/*
 * Garden Companion browse panel.
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
    loading: "Loading",
    loadingMore: "Loading more",
    plants: (n) => `${n} plant${n === 1 ? "" : "s"}`,
    more: (n) => `Scroll for ${n} more`,
    noPhoto: "No photo",
    photo: (credit) => `Photo: ${credit}`,
    planted: "Planted",
    plantedTimes: (n) => `Planted ${n}x`,
    plantedTitle: "You have this in your garden",
    plantedTitleTimes: (n) => `You have ${n} of these in your garden`,
    addPlant: (name) => `Add ${name} to my garden`,
    addAnother: (name) => `Add another ${name}`,
    nameLabel: "Name for this plant",
    nameHint: "This name labels the plant's device and entities. You can change it later.",
    add: "Add",
    cancel: "Cancel",
    close: "Close",
    pruning: "Pruning",
    source: "Source of this timing",
    loadFailed: "Could not load plants",
    addFailed: "Could not add the plant",
    months: [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ],
    range: (from, to) => `${from} to ${to}`,
  },
  nl: {
    search: "Zoek planten",
    loading: "Laden",
    loadingMore: "Meer laden",
    plants: (n) => `${n} plant${n === 1 ? "" : "en"}`,
    more: (n) => `Scroll voor nog ${n}`,
    noPhoto: "Geen foto",
    photo: (credit) => `Foto: ${credit}`,
    planted: "Geplant",
    plantedTimes: (n) => `${n}x geplant`,
    plantedTitle: "Deze staat in je tuin",
    plantedTitleTimes: (n) => `Hiervan staan er ${n} in je tuin`,
    addPlant: (name) => `${name} toevoegen aan mijn tuin`,
    addAnother: (name) => `Nog een ${name} toevoegen`,
    nameLabel: "Naam voor deze plant",
    nameHint: "Deze naam komt op het apparaat en de entiteiten van de plant. Je kunt hem later aanpassen.",
    add: "Toevoegen",
    cancel: "Annuleren",
    close: "Sluiten",
    pruning: "Snoeien",
    source: "Bron van deze timing",
    loadFailed: "Kon de planten niet laden",
    addFailed: "Kon de plant niet toevoegen",
    months: [
      "januari", "februari", "maart", "april", "mei", "juni",
      "juli", "augustus", "september", "oktober", "november", "december",
    ],
    range: (from, to) => `${from} tot ${to}`,
  },
};

class GardenCompanionPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
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
      this._load({ reset: true });
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
          padding: 16px 20px;
          font-size: 20px;
          font-weight: 500;
        }
        .toolbar { padding: 16px 20px 4px; }
        input[type="search"] {
          width: 100%;
          max-width: 420px;
          box-sizing: border-box;
          padding: 10px 12px;
          font-size: 15px;
          color: var(--primary-text-color, #212121);
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 8px;
        }
        .count { padding: 8px 20px; font-size: 13px; color: var(--secondary-text-color, #727272); }
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
           image, and stops short of the add button. */
        .credit {
          position: absolute;
          left: 0;
          right: 56px;
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
        .add {
          position: absolute;
          right: 10px;
          bottom: -20px;
          width: 40px;
          height: 40px;
          border-radius: 50%;
          border: none;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: center;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
          box-shadow: 0 2px 6px rgba(0,0,0,.3);
        }
        .add svg { width: 22px; height: 22px; fill: currentColor; }
        .add:hover { filter: brightness(1.08); }
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
        .common { font-size: 16px; font-weight: 500; padding-right: 40px; }
        .botanical { font-size: 13px; font-style: italic; color: var(--secondary-text-color, #727272); }
        .hint { font-size: 12px; color: var(--secondary-text-color, #727272); }
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
        .dialog a { color: var(--primary-color, #03a9f4); font-size: 13px; word-break: break-all; }
        .field { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
        .field label { font-size: 13px; font-weight: 500; }
        .field input {
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
        .error { margin: 16px 20px; color: var(--error-color, #db4437); }
        .end { height: 24px; }
        .more { padding: 0 20px 28px; font-size: 13px; color: var(--secondary-text-color, #727272); }
      </style>
      <header>Garden Companion</header>
      <div class="toolbar">
        <input type="search" autocomplete="off">
      </div>
      <div class="count"></div>
      <div class="error" hidden></div>
      <div class="grid"></div>
      <div class="end"></div>
      <div class="more" hidden></div>
      <div class="dialog-host"></div>
    `;
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
      type: "garden_companion/plants",
      limit: PAGE_SIZE,
      offset: reset ? 0 : this._plants.length,
    };
    if (this._query.trim()) message.query = this._query.trim();

    // Adding or changing a plant reloads the integration, which leaves a short
    // window where the dataset cannot be read, so a not-loaded answer is waited
    // out rather than shown as a failure.
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        const result = await this._hass.connection.sendMessagePromise(message);
        this._plants = reset ? result.plants : this._plants.concat(result.plants);
        this._total = result.total;
        this._error = null;
        break;
      } catch (err) {
        if (err && err.code === "not_loaded" && attempt < 5) {
          await new Promise((resolve) => setTimeout(resolve, 400));
          continue;
        }
        this._error = err && err.message ? err.message : this._t("loadFailed");
        break;
      }
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
        type: "garden_companion/add_plant",
        key: plant.key,
        name,
      });
      this._closeDialog();
      await this._load({ reset: true });
    } catch (err) {
      this._error = err && err.message ? err.message : this._t("addFailed");
      this._render();
    }
  }

  _render() {
    if (!this._built) return;
    const count = this.shadowRoot.querySelector(".count");
    const error = this.shadowRoot.querySelector(".error");
    const grid = this.shadowRoot.querySelector(".grid");
    const more = this.shadowRoot.querySelector(".more");

    error.hidden = this._error === null;
    error.textContent = this._error || "";

    count.textContent =
      this._loading && this._plants.length === 0
        ? this._t("loading")
        : this._t("plants")(this._total);

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
    card.addEventListener("click", () => this._openDialog(plant));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        this._openDialog(plant);
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
    frame.appendChild(this._addButton(plant));
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

    if (plant.distinguish) {
      const hint = document.createElement("div");
      hint.className = "hint";
      hint.textContent = plant.distinguish;
      body.appendChild(hint);
    }

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

  _addButton(plant) {
    const button = document.createElement("button");
    button.className = "add";
    const label = plant.added
      ? this._t("addAnother")(plant.common)
      : this._t("addPlant")(plant.common);
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>';
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      this._openDialog(plant);
    });
    return button;
  }

  _monthDay(value) {
    const [month, day] = value.split("-").map(Number);
    return `${day} ${this._t("months")[month - 1]}`;
  }

  _openDialog(plant) {
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
    dialog.setAttribute("aria-label", plant.common);

    const hero = document.createElement("div");
    hero.className = "hero";
    if (plant.photo) {
      const img = document.createElement("img");
      img.alt = plant.common;
      img.dataset.src = plant.photo;
      const cached = this._photos.get(plant.photo);
      if (cached) img.src = cached;
      else this._loadPhoto(plant.photo);
      hero.appendChild(img);
      if (plant.credit) {
        const credit = document.createElement("div");
        credit.className = "credit";
        credit.textContent = this._t("photo")(plant.credit);
        hero.appendChild(credit);
      }
    } else {
      const empty = document.createElement("div");
      empty.className = "noimg";
      empty.textContent = this._t("noPhoto");
      hero.appendChild(empty);
    }
    if (plant.added) hero.appendChild(this._ownedBadge(plant));
    dialog.appendChild(hero);

    const content = document.createElement("div");
    content.className = "content";

    const title = document.createElement("h2");
    title.textContent = plant.common;
    content.appendChild(title);

    const sub = document.createElement("p");
    sub.className = "sub";
    sub.textContent = plant.botanical;
    content.appendChild(sub);

    if (plant.distinguish) {
      const note = document.createElement("p");
      note.className = "note";
      note.textContent = plant.distinguish;
      content.appendChild(note);
    }

    if (plant.windows && plant.windows.length) {
      const heading = document.createElement("h3");
      heading.textContent = this._t("pruning");
      content.appendChild(heading);
      for (const window of plant.windows) {
        const block = document.createElement("div");
        block.className = "window";
        const when = document.createElement("div");
        when.className = "when";
        when.textContent = this._t("range")(
          this._monthDay(window.start),
          this._monthDay(window.end),
        );
        const what = document.createElement("div");
        what.className = "what";
        what.textContent = window.description;
        block.append(when, what);
        content.appendChild(block);
      }
    }

    if (plant.source) {
      const heading = document.createElement("h3");
      heading.textContent = this._t("source");
      const link = document.createElement("a");
      link.href = plant.source;
      link.target = "_blank";
      link.rel = "noreferrer noopener";
      link.textContent = plant.source;
      content.append(heading, link);
    }

    const field = document.createElement("div");
    field.className = "field";
    const label = document.createElement("label");
    label.textContent = this._t("nameLabel");
    const input = document.createElement("input");
    input.type = "text";
    input.value = plant.common;
    label.htmlFor = "plant-name";
    input.id = "plant-name";
    const hint = document.createElement("p");
    hint.className = "note";
    hint.textContent = this._t("nameHint");
    field.append(label, input, hint);
    content.appendChild(field);

    const actions = document.createElement("div");
    actions.className = "actions-row";
    const cancel = document.createElement("button");
    cancel.className = "secondary";
    cancel.textContent = this._t("cancel");
    cancel.addEventListener("click", () => this._closeDialog());
    const confirm = document.createElement("button");
    confirm.textContent = this._t("add");
    confirm.addEventListener("click", () => this._add(plant, input.value));
    actions.append(cancel, confirm);
    content.appendChild(actions);

    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") this._add(plant, input.value);
    });

    dialog.appendChild(content);
    backdrop.appendChild(dialog);
    host.appendChild(backdrop);

    this._escape = (event) => {
      if (event.key === "Escape") this._closeDialog();
    };
    window.addEventListener("keydown", this._escape);
    setTimeout(() => input.focus(), 0);
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

customElements.define("garden-companion-panel", GardenCompanionPanel);
