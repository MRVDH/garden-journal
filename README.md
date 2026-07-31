# Garden Companion

A Home Assistant integration that tells you when to prune the plants in your
garden, with timing tuned to the Dutch climate.

You enter your plants once. Each one gets a device with the date it should next
be pruned, a sensor that turns on while a pruning window is open, a photo, and a
line of advice in Dutch or English explaining what to actually do. Every plant's
windows also land on one calendar, so reminders are a normal Home Assistant
automation rather than anything this integration has to build.

Timing comes from a dataset that ships with the integration. Every plant's
windows are taken from a cited Dutch horticultural source, because pruning advice
that is confidently wrong is worse than no advice.

## What you get per plant

| Entity | What it does |
|---|---|
| `sensor.<plant>_next_pruning` | The date this plant should next be pruned, with the window's end date and what to do as attributes |
| `binary_sensor.<plant>_prune_now` | On while today falls inside a pruning window |
| `image.<plant>_photo` | A photo, so you can check you picked the right plant |
| `calendar.garden_companion` | Every plant's windows as all-day events, one calendar for the whole garden |

Everything is computed locally at midnight. Nothing polls, and the only network
request is Home Assistant fetching a plant photo once.

## Requirements

Home Assistant 2026.7.0 or newer.

## Installing

Through HACS as a custom repository:

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add `https://github.com/MRVDH/garden-companion` with category **Integration**.
3. Download **Garden Companion**, then restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration** and search for
   Garden Companion.

Or copy `custom_components/garden_companion` into your `config/custom_components`
directory and restart.

## Adding plants

Two ways, whichever suits you.

**Browse the Garden Companion panel** in the sidebar. It shows every plant in the
dataset as a card with its photo, common name, botanical name and pruning dates,
with a search box over the top. Click a plant, give it a name, and it is added.
Cards for plants you already have say so. Photos are fetched by Home Assistant
rather than by your browser, so looking at the panel does not tell Wikimedia
anything about you.

**Or add from the integration page**, which is the same flow Home Assistant uses
for everything else. Pick a plant from the list, or type a botanical or common
name, in Dutch or English: `Hydrangea`, `blauwe regen` and `rose` all work, and a
partial name like `hortensia` finds every hydrangea. This is also the route for a
plant that is not in the dataset.

Some names cannot be answered on their own. Hydrangeas are the clear case: a
panicle hydrangea is cut hard in spring and a velvet hydrangea must not be cut
back at all, so typing `hortensia` asks which one you have. A rose asks whether
it is freestanding or trained against a wall, because that changes when it is
pruned. Names that resolve to the same timing never ask: `laurier` matches both
cherry laurel and bay, and they are pruned alike.

If a plant is not in the dataset yet, you can still add it: either borrow the
timing of a plant that is pruned the same way, or enter your own windows.

## The dataset

`custom_components/garden_companion/data/species.yaml` holds one record per
plant, keyed on genus, species and variant. Corrections arrive by updating that
file: timing is looked up fresh on every restart, so a fixed month reaches
plants you already added without any migration.

Adding or correcting a plant is a pull request against that file. `scripts/validate.py`
checks it against the schema and runs in CI. It has two report modes,
`--duplicates` and `--uncredited`, that are informational rather than pass or
fail.

## Licence

Two licences, because code and data are different things:

- The code is **MIT**, see [LICENSE](LICENSE).
- The dataset in `custom_components/garden_companion/data/` is
  **CC BY-SA 4.0**, see
  [data/LICENSE](custom_components/garden_companion/data/LICENSE). Reuse it, and
  share your version alike.

Neither licence covers the linked photos. Those are freely licensed Wikimedia
Commons files that stay under their own terms, recorded per photo in the dataset
with author and licence. Nothing is redistributed here, only linked.
