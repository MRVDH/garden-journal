---
name: create-release
description: Cut a new Garden Journal release. Use when publishing a new version, bumping the integration version, or tagging. Covers the version bump, the tag, and the GitHub release HACS installs from.
---

# Cutting a release

A release is three things that have to agree: the version in `manifest.json`, a
git tag `vX.Y.Z`, and a GitHub Release. HACS installs from the **Release**, so a
tag on its own is not enough. CI has a `Tag matches manifest` job that fails a tag
whose version does not equal the manifest, so the order below is not optional.

## Pick the version

Semantic versioning. Pre-1.0, so:

- **patch** (`0.1.0` -> `0.1.1`) for dataset additions, corrections and fixes.
- **minor** (`0.1.x` -> `0.2.0`) for a new feature or a change in how something
  behaves.

If you are unsure, patch is the safe default while the project is pre-1.0.

## Steps

The version bump goes through a pull request like any other change; nothing lands
on `main` directly. The tag is cut on `main` **after** the PR merges, never on the
branch.

1. **Branch and bump.** On a fresh branch (`chore/release-X.Y.Z`), set the version
   in `custom_components/garden_journal/manifest.json`:

   ```json
   "version": "0.1.1"
   ```

2. **PR it.** Commit, push, open a PR. Let CI go green, then merge and delete the
   branch. Update your local `main`.

3. **Confirm main carries the new version** before tagging, so the tag cannot
   disagree with the manifest:

   ```bash
   python3 -c "import json; print(json.load(open('custom_components/garden_journal/manifest.json'))['version'])"
   ```

4. **Tag on main** with an annotated tag whose name is the version with a `v`
   prefix:

   ```bash
   git tag -a v0.1.1 -m "Garden Journal 0.1.1"
   git push origin v0.1.1
   ```

5. **Create the release with GitHub's generated notes.** Do not hand-write them:

   ```bash
   gh release create v0.1.1 --generate-notes --verify-tag --latest
   ```

   `--generate-notes` builds the notes from the pull requests merged since the last
   release, which is why PR titles are worth getting right. `--verify-tag` refuses
   to invent a tag if the push in step 4 did not land.

   **If `--generate-notes` is not available** (an older `gh`, or the command
   errors), stop and create the release by hand in the GitHub UI with its
   "Generate release notes" button. Do not fall back to writing the notes
   yourself.

6. **Verify the tag build is green**, in particular `Tag matches manifest`, which
   only runs on tags and is the last thing that can catch a version mismatch:

   ```bash
   gh run list --limit 1
   ```

## Gotchas learned the hard way

- **Tag only after `main`'s CI is green.** A tag pushed onto a red commit points
  at a broken build. Moving a published tag is possible but messy; tag once, on a
  commit you have seen pass.
- **The manifest and the tag must match exactly.** `v0.1.1` needs manifest
  `0.1.1`. The CI job exists because this went wrong once.
- **A tag is not a release.** HACS reads Releases. If you tag but do not create a
  release, HACS keeps installing the previous version, or the default branch.
- **No config migration is needed for a dataset release.** Stored plants are
  re-resolved from the dataset on every load, so corrected timing reaches plants
  people already added. The release notes can say so plainly.
