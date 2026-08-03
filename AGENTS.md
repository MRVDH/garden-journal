# AGENTS.md

Notes for anyone working on this repo, human or agent. Everything here is
something you cannot work out by reading the code, so it is worth the two minutes.
`CLAUDE.md` is a symlink to this file, so Claude Code reads it as well.

## Getting set up

`scripts/setup` creates `.venv` from the pins in `requirements-dev.txt`. Run
everything from the repo root:

```bash
.venv/bin/python -m pytest -q          # the whole suite, a handful of seconds
.venv/bin/ruff format . && .venv/bin/ruff check .
.venv/bin/python scripts/validate.py   # the dataset against its schema, as CI does
scripts/develop                        # a throwaway Home Assistant on :8123
```

The two Home Assistant pins go together. `pytest-homeassistant-custom-component`
tracks one core release, and mismatching them produces import errors that read
like your own code is broken.

## The dev Home Assistant

`scripts/develop` runs a real Home Assistant against `config/`, which is
gitignored. Deleting that directory resets the instance, including onboarding and
the user account, so prefer removing plants to wiping it.

- **Only one process can bind :8123.** An instance left running from earlier keeps
  serving the dataset and the code it started with, so you can spend a long time
  editing files and reloading a browser that is talking to an older build. Check
  for a running `hass` before concluding that a change had no effect.
- **There is no hot reload.** Any Python change needs a restart. Reloading the
  config entry re-reads `species.yaml` but does not re-import modules.
- **Bump `_MODULE_VERSION` in `panel.py` whenever the panel's JavaScript changes.**
  It is the cache-buster on the module URL. Skip it and the browser serves the old
  module, which looks exactly like your change not working.
- **A panel URL opened directly returns 403.** The panel needs the Home Assistant
  frontend shell to authenticate, so open `/` and use the sidebar. Each 403 also
  raises a "Login attempt failed" notification, which is yours, not a bug.
- **Entity ids are slugged from the translated name** the first time an entity
  registers. A plant added while the instance runs in English keeps English ids
  after you switch to Dutch, and a language change needs a restart. Settle the
  language before adding plants you intend to keep.

## Tests

`pytest-homeassistant-custom-component` gives the tests a real `hass`. Four
ordering rules, each of which fails in a way that does not point at the cause:

- **Set up the config entry before building a WebSocket client.** The aiohttp
  router freezes once the client starts the app, and a later setup fails with
  "Cannot register a resource into frozen router" followed by a wall of unrelated
  dependency errors.
- **Build the WebSocket client before freezing time.** Its token check runs against
  the real clock.
- **Persistent notifications are not entities.** Assert on them by patching
  `homeassistant.components.persistent_notification.async_create`.
- `tests/conftest.py` unloads any loaded entry at teardown, because entities
  register a midnight timer and the event loop is checked for stragglers.

`manifest.json` declares `http`, `panel_custom` and `websocket_api` as
dependencies. Without them `hass.http` is absent under test.

## How changes land

**Nothing goes straight onto `main`.** Every change, however small, starts on a
branch and lands through a pull request. A one-line fix is not an exception: the
point is that CI has run and someone has read the diff before it becomes the
default branch.

- Branch names say what kind of change it is: `feat/care-seasons`, `fix/stale-panel-cache`,
  `docs/branch-and-pr-workflow`, `refactor/drop-variant`.
- Run the four commands above before opening the PR. CI runs them too, so a red PR
  is a round trip you did not need.
- A tag is cut on `main` after the PR merges, never on a branch. `manifest.json`'s
  version and the tag have to agree, and CI fails a tag where they do not.

## Conventions

- **Comments describe what the code does now.** No ticket references, and nothing
  about what the code used to do or which change fixed what. That belongs in the
  commit message.
- Docstrings everywhere, which ruff enforces. The lint selection is a subset of
  Home Assistant core's own; the comment in `pyproject.toml` says what was left out
  and why.
- **Check Home Assistant behaviour against the installed source in `.venv` or the
  official docs rather than from memory.** The API surface moves between releases,
  and a confident wrong claim about it has cost real debugging time here.

## Settled decisions

Each of these was argued through once and is easy to propose again from a clean
reading of the code. Reopen any of them on new evidence, not on first impression.

- **Windows are inline on every row, with no shared blocks.** Deduplicating the
  handful of repeated timings would cost a second file, reference fields, either/or
  validation and orphan checks. `scripts/validate.py --duplicates` reports the
  repetition, which is the evidence to revisit on.
- **Rows are flat, with no rule indirection.** Contributors think in plants, and
  published pruning advice is written per plant.
- **A genus-level entry is a row with no `species`**, not a special key the loader
  has to parse.
- **Ambiguity is computed, never flagged.** If the rows under a genus resolve to
  more than one distinct set of advice, the flow asks. A hand-maintained
  "needs_species" flag is state someone eventually forgets to set.
- **Timing is re-resolved from the stored key on every load.** A dataset update is
  how corrections reach people, so freezing the resolved windows at add time would
  block the mechanism they exist for.
- **Growing habit does not get its own axis.** Where habit changes what you cut but
  not when, the difference goes in the window description. It earns two rows and a
  question only when it splits the timing.
- **Continuous care is a state, not a calendar event.** A months-long all-day event
  would cover the pruning windows and hold the calendar on all summer. See the
  `CareNowBinarySensor` docstring.
- **A calendar, and no `todo` entity.** With the windows on a calendar, reminders
  are an ordinary automation and need no code here.
- **No last-pruned tracking.** It needs a service call, state restore and a UI to
  trigger it, and it turns this into a task tracker, which other integrations
  already do well.
- **Photos are linked, never bundled.** Keeps the repo small and redistributes
  nobody's image.

## The dataset

`custom_components/garden_journal/data/species.yaml` is **CC BY-SA 4.0** while
the code is MIT. Keep that boundary in mind before moving text between them.

- **Every row cites a Dutch source for its timing.** Do not add or change a window
  without one. Where a source is silent, for instance a continuous-care season with
  no months named, say in the row's comment that the dates are interpretation.
- Where the timing is genuinely uncertain, the safer window wins. For a plant that
  flowers on old wood, cutting too early costs a season's flowers, so a later date
  is the lower-risk error.
- Photos are linked from Wikimedia Commons, never copied. Fetching them needs a
  descriptive `User-Agent` naming the tool and a URL: Wikimedia's robot policy
  refuses a generic agent with HTTP 429 however few requests you make, which looks
  exactly like rate limiting and is not.
- After editing `brand/icon.svg`, run `scripts/render_icon.py` and commit the PNGs,
  which are what Home Assistant and HACS read. It needs cairosvg, kept out of
  `requirements-dev.txt` so CI never needs a rasteriser. Judge an icon change at
  48px as well as at 256px, because that is roughly the size the integration list
  draws it at.
- `scripts/check_icon.py` measures the rendered PNGs and fails when the artwork is
  off centre, which CI runs on every pull request. It reads the committed files
  rather than the SVG, so it needs no rasteriser, only the Pillow that arrives with
  homeassistant. It exists because the artwork once shipped 11px right and 19px
  below centre with a 52px left margin against 29px on the right, and nobody sees
  that on a rounded square until it is pointed out.
