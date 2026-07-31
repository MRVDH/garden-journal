"""Tests for the standalone dataset validator's report modes (step 11).

The validator is run as a subprocess, the way CI invokes it, so its own
Home-Assistant-free import path is exercised as shipped and does not collide with
the packaged `models` module imported elsewhere in the suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_VALIDATE = Path(__file__).resolve().parents[1] / "scripts" / "validate.py"


def _run(path: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    """Run the validator against a dataset file and capture its output."""
    return subprocess.run(
        [sys.executable, str(_VALIDATE), *flags, str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


_SHARED = """
- genus: Ilex
  species: crenata
  names: {nl: [Japanse hulst], en: [Box-leaved holly]}
  source: https://example.org
  windows:
    - when: {start: "05-15", end: "06-15"}
      description: {nl: Snoei, en: Trim}
- genus: Ligustrum
  names: {nl: [Liguster], en: [Privet]}
  source: https://example.org
  windows:
    - when: {start: "05-15", end: "06-15"}
      description: {nl: Snoei, en: Trim}
- genus: Buxus
  names: {nl: [Buxus], en: [Box]}
  source: https://example.org
  windows:
    - when: {start: "05-15", end: "06-15"}
      description: {nl: Anders, en: Different}
"""

_PHOTOS = """
- genus: Lavandula
  names: {nl: [Lavendel], en: [Lavender]}
  source: https://example.org
  image: {url: "https://example.org/l.jpg", author: A. Photographer}
  windows:
    - when: {start: "08-01", end: "08-31"}
      description: {nl: Snoei, en: Trim}
- genus: Wisteria
  names: {nl: [Blauwe regen], en: [Wisteria]}
  source: https://example.org
  image: {url: "https://example.org/w.jpg", author: B. Photographer, licence: CC BY-SA 4.0}
  windows:
    - when: {start: "07-15", end: "08-31"}
      description: {nl: Snoei, en: Trim}
"""


def test_duplicates_groups_identical_blocks_only(tmp_path: Path) -> None:
    """Rows with an identical window set are grouped; matching dates alone are not."""
    dataset = tmp_path / "species.yaml"
    dataset.write_text(_SHARED, encoding="utf-8")

    result = _run(dataset, "--duplicates")
    assert result.returncode == 0
    assert "1 repeated window block(s):" in result.stdout
    assert "Ilex crenata, Ligustrum" in result.stdout
    assert "Buxus" not in result.stdout.split("repeated window block(s):", 1)[1]


def test_uncredited_lists_photos_missing_credit(tmp_path: Path) -> None:
    """A photo without a licence is reported; a fully credited photo is not."""
    dataset = tmp_path / "species.yaml"
    dataset.write_text(_PHOTOS, encoding="utf-8")

    result = _run(dataset, "--uncredited")
    assert result.returncode == 0
    assert "1 photo(s) without full credit:" in result.stdout
    assert "Lavandula" in result.stdout
    assert "Wisteria" not in result.stdout.split("without full credit:", 1)[1]
