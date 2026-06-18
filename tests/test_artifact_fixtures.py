"""Integrity tests for the frozen pre-migration markdown fixtures.

The files under ``tests/fixtures/pre_migration/`` are byte-exact captures of
the markdown scan artifacts taken BEFORE any HTML artifact generation code
landed (PRD SDLC-P0041, design DD-11). They are the uncontaminated baseline
for the AC-004 / NFR-002 byte-overhead gate (revised 2026-06-10): each
generated HTML artifact must satisfy max(baseline * 1.8, baseline + 6 KiB)
per file and the five-artifact corpus must stay <= baseline total * 1.6.

The fixtures were copied from the canonical git blobs of ``example-artifacts/``
(LF line endings, the repository-stored bytes) and are protected from
line-ending conversion by a ``-text`` rule in ``.gitattributes``.

These fixtures are FROZEN. They must never be refreshed, regenerated, or
reformatted. Expected byte sizes and SHA-256 checksums are read dynamically
from ``baseline_sizes.json`` rather than hardcoded here.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pre_migration"
BASELINE_PATH = FIXTURE_DIR / "baseline_sizes.json"

EXPECTED_FIXTURE_NAMES = [
    "architecture.md",
    "codebase-summary.md",
    "data-model.md",
    "directory-structure.md",
    "key-workflows.md",
]


def _load_baseline() -> dict[str, dict[str, Any]]:
    with BASELINE_PATH.open(encoding="utf-8") as fh:
        baseline: dict[str, dict[str, Any]] = json.load(fh)
    return baseline


def test_baseline_sizes_recorded() -> None:
    """baseline_sizes.json records bytes + sha256 for all 5 frozen fixtures."""
    baseline = _load_baseline()

    assert sorted(baseline) == sorted(EXPECTED_FIXTURE_NAMES), (
        "baseline_sizes.json must contain exactly the 5 frozen pre-migration "
        f"fixtures; got {sorted(baseline)}"
    )

    for name, entry in baseline.items():
        assert isinstance(entry.get("bytes"), int) and entry["bytes"] > 0, (
            f"baseline entry for {name} must record a positive byte count"
        )
        sha256 = entry.get("sha256")
        assert (
            isinstance(sha256, str)
            and len(sha256) == 64
            and all(c in "0123456789abcdef" for c in sha256)
        ), f"baseline entry for {name} must record a lowercase hex SHA-256 digest"


def test_fixtures_frozen_checksums() -> None:
    """Every frozen fixture still matches its recorded size and SHA-256."""
    baseline = _load_baseline()

    for name in EXPECTED_FIXTURE_NAMES:
        fixture_path = FIXTURE_DIR / name
        assert fixture_path.is_file(), (
            f"Frozen fixture {name} is missing from {FIXTURE_DIR}. "
            "Pre-migration fixtures are frozen baselines and must be restored, "
            "not regenerated."
        )

        data = fixture_path.read_bytes()
        actual_sha256 = hashlib.sha256(data).hexdigest()
        expected = baseline[name]

        assert len(data) == expected["bytes"] and actual_sha256 == expected["sha256"], (
            f"Frozen fixture {name} has been modified "
            f"(expected {expected['bytes']} bytes / sha256 {expected['sha256']}, "
            f"got {len(data)} bytes / sha256 {actual_sha256}). "
            "These pre-migration fixtures are FROZEN baselines for the AC-004 "
            "byte-overhead gate and must NOT be refreshed, regenerated, or "
            "reformatted. Restore the original byte-exact content instead of "
            "updating baseline_sizes.json."
        )
