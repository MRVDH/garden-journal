---
name: add-a-plant
description: Add a plant to the Garden Journal dataset, or correct one. Use when editing species.yaml, adding a species, sourcing pruning timing, or finding a plant photo. Covers sourcing, the schema, photos, and verification.
---

# Adding a plant to the dataset

A row in `custom_components/garden_journal/data/species.yaml` tells people when to
cut a plant, so the bar is that every claim is either cited or visibly marked as a
reading. Getting the horticulture wrong is the one failure that makes this
integration worse than not existing, and no test can catch it. Work through the
four parts below, then land it as a pull request.

## 1. Timing, from a Dutch source you actually read

- **Cite a Dutch horticultural page for every window.** Open it and read it. A
  search summary is not a source; it paraphrases and it guesses.
- **When the page gives a season, not a month, the fortnight is your reading.**
  Put the dates in anyway (the integration needs `MM-DD`), and say in a comment
  above the row that the window is a reading rather than a citation, so the next
  reader knows which part to trust. This is normal; several rows are like this.
- **When sources disagree, the safer window wins.** For a plant that flowers on
  old wood, cutting too early costs a season's flowers, so the later date is the
  lower-risk error. Say which way you erred in the comment.
- **Descriptions go in both `nl` and `en`, kept in step.** If you change one,
  change the other to match.

## 2. The schema

- **Rows key on `(genus, species)`.** A genus-level row that covers the whole
  genus omits `species`.
- **Ambiguity is computed, never flagged.** If two species under one genus resolve
  to different timing, searching the genus asks which one you have; if they agree,
  it does not. You do not declare this. It means: if a new species genuinely
  differs from its siblings in *when* it is cut, add it as its own row and the
  question appears on its own. If it differs only in *what* you cut, put that in
  the description and keep one row.
- **`care` is for season-long jobs, not windows.** Deadheading, cutting suckers:
  work that runs for months and is triggered by a spent flower rather than a date.
  It becomes a "care now" sensor, not a calendar event.
- **Put the row in the right section** and match the file's existing layout and
  wrapping.

## 3. Photos

- **Wikimedia Commons only, freely licensed.** CC BY, CC BY-SA, CC0 or public
  domain. Never NC or ND: the dataset links to the file and cannot carry a
  non-commercial or no-derivatives image.
- **Take author and licence from the Commons API, not by eye.** Query the API's
  `extmetadata` so the credit is what Commons records, not a guess.
- **Look at the image before you trust it.** A filename does not prove the picture
  is of the plant, or that it is a usable shot. Reject studio cut-outs, a hand in
  frame, a plant that is not visibly the species. Files are sometimes mislabeled
  on Commons: one file named for one species can show another, so check the leaf
  or flower against what the plant should look like.
- **Verify the URL loads** at the width the dataset requests (`width=600`) before
  committing it, reading it out of the file rather than from your notes.
- **Use a descriptive User-Agent** naming your tool and a contact URL. Wikimedia's
  robot policy refuses a generic agent with HTTP 429 however few requests you
  make, which looks exactly like rate limiting and is not.

A starting point for both the search and the check (fill in your own tool name and
repository in the User-Agent):

```python
import urllib.parse, urllib.request, json

AGENT = "YourTool/0.1 (dataset photo sourcing; https://github.com/you/your-repo)"


def commons_search(term, limit=8):
    """Freely licensed file candidates for a search term, with licence and author."""
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f'filetype:bitmap "{term}"',
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "extmetadata",
        "iiextmetadatafilter": "LicenseShortName|Artist",
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def loads_ok(filename, width=600):
    """True when the Special:FilePath URL returns 200 at the given width."""
    path = urllib.parse.quote(filename, safe="()")
    url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{path}?width={width}"
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status == 200
    except Exception:
        return False
```

The `url` in the row is the same `Special:FilePath` form; the `page` is the
`File:` page it came from.

## 4. Verify, then PR

```bash
.venv/bin/python scripts/validate.py     # schema + the record count
.venv/bin/python -m pytest -q
.venv/bin/ruff format . && .venv/bin/ruff check .
```

- **Read the record count `validate.py` prints.** It is the check that catches a
  row you dropped or fat-fingered: if you added one plant, the count should go up
  by one. A silently missing row shows up nowhere else.
- **Check the behaviour, not just that it parses.** If you added a species that
  makes a genus ambiguous, confirm the genus now asks and the common names people
  type still resolve to the plant you meant.
- **Land it as a pull request** against `species.yaml`. CI runs the same checks.
