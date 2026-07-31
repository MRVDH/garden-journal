/*
 * Garden Companion browse panel.
 *
 * Plain custom element with no dependencies and no build step, so the file that
 * ships is the file that was written. Home Assistant sets `hass`, `narrow` and
 * `panel` properties on the element.
 *
 * Searching goes to the server and comes back bounded, so the grid does not
 * depend on the whole dataset fitting in one response. Photos are fetched from
 * Home Assistant with the auth header and turned into blob URLs, which keeps the
 * browser off the remote host and works where an <img src> could not send a
 * token.
 */

const DEBOUNCE_MS = 250;

class GardenCompanionPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._plants = [];
    this._total = 0;
    this._query = "";
    this._loading = false;
    this._error = null;
    this._naming = null;
    this._photos = new Map();
    this._timer = null;
    this._built = false;
    this._generation = 0;
  }

  set hass(hass) {
    const first = this._hass === null;
    this._hass = hass;
    if (first) {
      this._build();
      this._load();
    }
  }

  set panel(_panel) {
    // Home Assistant sets this; the panel takes no config.
  }

  set narrow(narrow) {
    this._narrow = narrow;
  }

  disconnectedCallback() {
    for (const url of this._photos.values()) URL.revokeObjectURL(url);
    this._photos.clear();
    if (this._timer) clearTimeout(this._timer);
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
          padding: 12px 20px 32px;
          grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
        }
        .card {
          background: var(--card-background-color, #fff);
          border-radius: 12px;
          overflow: hidden;
          box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0,0,0,.16));
          display: flex;
          flex-direction: column;
        }
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
        .body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
        .common { font-size: 16px; font-weight: 500; }
        .botanical { font-size: 13px; font-style: italic; color: var(--secondary-text-color, #727272); }
        .hint { font-size: 12px; color: var(--secondary-text-color, #727272); }
        .windows { font-size: 12px; margin: 4px 0 0; padding-left: 16px; }
        .windows li { margin-bottom: 2px; }
        .credit { font-size: 11px; color: var(--secondary-text-color, #727272); }
        .actions { margin-top: auto; padding-top: 10px; display: flex; gap: 8px; align-items: center; }
        button {
          font: inherit;
          font-size: 14px;
          padding: 8px 14px;
          border-radius: 8px;
          border: none;
          cursor: pointer;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
        }
        button.secondary { background: transparent; color: var(--primary-color, #03a9f4); }
        button:disabled { opacity: .55; cursor: default; }
        .added { font-size: 13px; color: var(--secondary-text-color, #727272); }
        .naming { display: flex; gap: 8px; width: 100%; }
        .naming input {
          flex: 1;
          min-width: 0;
          padding: 7px 10px;
          font: inherit;
          font-size: 14px;
          color: var(--primary-text-color, #212121);
          background: var(--card-background-color, #fff);
          border: 1px solid var(--divider-color, #e0e0e0);
          border-radius: 6px;
        }
        .error { margin: 16px 20px; color: var(--error-color, #db4437); }
      </style>
      <header>Garden Companion</header>
      <div class="toolbar">
        <input type="search" placeholder="Search plants" autocomplete="off">
      </div>
      <div class="count"></div>
      <div class="error" hidden></div>
      <div class="grid"></div>
    `;
    const search = this.shadowRoot.querySelector("input[type=search]");
    search.addEventListener("input", () => {
      this._query = search.value;
      if (this._timer) clearTimeout(this._timer);
      this._timer = setTimeout(() => this._load(), DEBOUNCE_MS);
    });
  }

  async _load() {
    if (!this._hass) return;
    this._loading = true;
    this._error = null;
    this._render();
    const message = { type: "garden_companion/plants" };
    if (this._query.trim()) message.query = this._query.trim();
    // Adding or changing a plant reloads the integration, which leaves a short
    // window where the dataset cannot be read, so a not-loaded answer is waited
    // out rather than shown as a failure.
    for (let attempt = 0; attempt < 6; attempt++) {
      try {
        const result = await this._hass.connection.sendMessagePromise(message);
        this._plants = result.plants;
        this._total = result.total;
        this._error = null;
        break;
      } catch (err) {
        if (err && err.code === "not_loaded" && attempt < 5) {
          await new Promise((resolve) => setTimeout(resolve, 400));
          continue;
        }
        this._error = err && err.message ? err.message : "Could not load plants";
        this._plants = [];
        this._total = 0;
        break;
      }
    }
    this._loading = false;
    this._render();
    this._loadPhotos();
  }

  async _loadPhotos() {
    // Home Assistant fetches each photo from the remote host one at a time, so
    // asking for them in order keeps the queue short and the grid fills top down.
    const generation = ++this._generation;
    for (const plant of this._plants) {
      if (generation !== this._generation) return;
      if (!plant.photo || this._photos.has(plant.photo)) continue;
      try {
        const response = await fetch(plant.photo, {
          headers: { Authorization: `Bearer ${this._hass.auth.data.access_token}` },
        });
        if (!response.ok) continue;
        const url = URL.createObjectURL(await response.blob());
        this._photos.set(plant.photo, url);
        const img = this.shadowRoot.querySelector(`img[data-src="${plant.photo}"]`);
        if (img) img.src = url;
      } catch {
        // A photo that will not load leaves its placeholder in place.
      }
    }
  }

  async _add(plant, name) {
    try {
      await this._hass.connection.sendMessagePromise({
        type: "garden_companion/add_plant",
        key: plant.key,
        name,
      });
      this._naming = null;
      await this._load();
    } catch (err) {
      this._error = err && err.message ? err.message : "Could not add the plant";
      this._render();
    }
  }

  _monthDay(value) {
    const [month, day] = value.split("-").map(Number);
    const months = [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ];
    return `${day} ${months[month - 1]}`;
  }

  _render() {
    if (!this._built) return;
    const count = this.shadowRoot.querySelector(".count");
    const error = this.shadowRoot.querySelector(".error");
    const grid = this.shadowRoot.querySelector(".grid");

    error.hidden = this._error === null;
    error.textContent = this._error || "";

    if (this._loading) {
      count.textContent = "Loading";
    } else if (this._total > this._plants.length) {
      count.textContent = `Showing ${this._plants.length} of ${this._total} plants, narrow the search to see the rest`;
    } else {
      count.textContent = `${this._total} plant${this._total === 1 ? "" : "s"}`;
    }

    grid.textContent = "";
    for (const plant of this._plants) {
      grid.appendChild(this._card(plant));
    }
  }

  _card(plant) {
    const card = document.createElement("div");
    card.className = "card";

    if (plant.photo) {
      const img = document.createElement("img");
      img.className = "photo";
      img.alt = plant.common;
      img.dataset.src = plant.photo;
      const cached = this._photos.get(plant.photo);
      if (cached) img.src = cached;
      card.appendChild(img);
    } else {
      const empty = document.createElement("div");
      empty.className = "photo empty";
      empty.textContent = "No photo";
      card.appendChild(empty);
    }

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

    const windows = document.createElement("ul");
    windows.className = "windows";
    for (const window of plant.windows) {
      const item = document.createElement("li");
      item.textContent = `${this._monthDay(window.start)} to ${this._monthDay(window.end)}`;
      item.title = window.description;
      windows.appendChild(item);
    }
    body.appendChild(windows);

    if (plant.credit) {
      const credit = document.createElement("div");
      credit.className = "credit";
      credit.textContent = `Photo: ${plant.credit}`;
      body.appendChild(credit);
    }

    body.appendChild(this._actions(plant));
    card.appendChild(body);
    return card;
  }

  _actions(plant) {
    const actions = document.createElement("div");
    actions.className = "actions";

    if (this._naming === plant.key) {
      const wrap = document.createElement("div");
      wrap.className = "naming";
      const input = document.createElement("input");
      input.type = "text";
      input.value = plant.common;
      input.setAttribute("aria-label", "Name for this plant");
      const confirm = document.createElement("button");
      confirm.textContent = "Add";
      const cancel = document.createElement("button");
      cancel.className = "secondary";
      cancel.textContent = "Cancel";
      confirm.addEventListener("click", () => this._add(plant, input.value));
      cancel.addEventListener("click", () => {
        this._naming = null;
        this._render();
      });
      input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") this._add(plant, input.value);
      });
      wrap.append(input, confirm, cancel);
      actions.appendChild(wrap);
      setTimeout(() => input.focus(), 0);
      return actions;
    }

    const button = document.createElement("button");
    button.textContent = plant.added ? "Add another" : "Add to my garden";
    if (plant.added) button.className = "secondary";
    button.addEventListener("click", () => {
      this._naming = plant.key;
      this._render();
    });
    actions.appendChild(button);

    if (plant.added) {
      const added = document.createElement("span");
      added.className = "added";
      added.textContent = "In your garden";
      actions.appendChild(added);
    }
    return actions;
  }
}

customElements.define("garden-companion-panel", GardenCompanionPanel);
