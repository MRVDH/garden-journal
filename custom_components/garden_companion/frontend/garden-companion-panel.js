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
        }
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
        .body { padding: 14px 14px 14px; display: flex; flex-direction: column; gap: 4px; flex: 1; }
        .common { font-size: 16px; font-weight: 500; padding-right: 40px; }
        .botanical { font-size: 13px; font-style: italic; color: var(--secondary-text-color, #727272); }
        .hint { font-size: 12px; color: var(--secondary-text-color, #727272); }
        .added { font-size: 12px; color: var(--secondary-text-color, #727272); }
        .naming { display: flex; gap: 8px; width: 100%; margin-top: 8px; }
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
        .naming button {
          font: inherit;
          font-size: 14px;
          padding: 7px 12px;
          border: none;
          border-radius: 6px;
          cursor: pointer;
          background: var(--primary-color, #03a9f4);
          color: var(--text-primary-color, #fff);
        }
        .naming button.secondary { background: transparent; color: var(--primary-color, #03a9f4); }
        .error { margin: 16px 20px; color: var(--error-color, #db4437); }
        .end { height: 24px; }
        .more { padding: 0 20px 28px; font-size: 13px; color: var(--secondary-text-color, #727272); }
      </style>
      <header>Garden Companion</header>
      <div class="toolbar">
        <input type="search" placeholder="Search plants" autocomplete="off">
      </div>
      <div class="count"></div>
      <div class="error" hidden></div>
      <div class="grid"></div>
      <div class="end"></div>
      <div class="more" hidden></div>
    `;
    const search = this.shadowRoot.querySelector("input[type=search]");
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
      this._naming = null;
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
        this._error = err && err.message ? err.message : "Could not load plants";
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
      this._naming = null;
      await this._load({ reset: true });
    } catch (err) {
      this._error = err && err.message ? err.message : "Could not add the plant";
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

    if (this._loading && this._plants.length === 0) {
      count.textContent = "Loading";
    } else {
      count.textContent = `${this._total} plant${this._total === 1 ? "" : "s"}`;
    }

    const remaining = this._total - this._plants.length;
    more.hidden = remaining <= 0;
    more.textContent = this._loading
      ? "Loading more"
      : `Scroll for ${remaining} more`;

    grid.textContent = "";
    for (const plant of this._plants) {
      grid.appendChild(this._card(plant));
    }
  }

  _card(plant) {
    const card = document.createElement("div");
    card.className = "card";

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
        credit.textContent = `Photo: ${plant.credit}`;
        credit.title = plant.credit;
        frame.appendChild(credit);
      }
    } else {
      const empty = document.createElement("div");
      empty.className = "photo empty";
      empty.textContent = "No photo";
      frame.appendChild(empty);
    }

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

    if (plant.added) {
      const added = document.createElement("div");
      added.className = "added";
      added.textContent = "In your garden";
      body.appendChild(added);
    }

    if (this._naming === plant.key) body.appendChild(this._namingRow(plant));

    card.appendChild(body);
    return card;
  }

  _addButton(plant) {
    const button = document.createElement("button");
    button.className = "add";
    const label = plant.added
      ? `Add another ${plant.common}`
      : `Add ${plant.common} to my garden`;
    button.title = label;
    button.setAttribute("aria-label", label);
    button.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>';
    button.addEventListener("click", () => {
      this._naming = this._naming === plant.key ? null : plant.key;
      this._render();
    });
    return button;
  }

  _namingRow(plant) {
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
    setTimeout(() => input.focus(), 0);
    return wrap;
  }
}

customElements.define("garden-companion-panel", GardenCompanionPanel);
