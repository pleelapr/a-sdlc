"""Contract test for the shipped example artifacts.

The HTML files in ``example-artifacts/`` are produced by following the
documented scan.md recipes (scaffold -> fill <main> -> validate) and serve as
the documentation's own acceptance test. This test runs the shipped validator
against them, pinning the examples to the artifact contract permanently: any
contract change that invalidates the examples (or vice versa) fails here.
"""

from pathlib import Path

from a_sdlc.artifacts.validator import validate_directory

EXAMPLE_ARTIFACTS_DIR = Path(__file__).parent.parent / "example-artifacts"

EXPECTED_HTML_FILES = [
    "architecture.html",
    "codebase-summary.html",
    "data-model.html",
    "directory-structure.html",
    "index.html",
    "key-workflows.html",
]


def test_example_artifacts_pass_validator() -> None:
    """All 6 example HTML artifacts validate with zero errors."""
    results, _skipped = validate_directory(EXAMPLE_ARTIFACTS_DIR)

    validated_files = sorted(result.file for result in results)
    assert validated_files == EXPECTED_HTML_FILES

    failures = {
        result.file: result.errors for result in results if result.errors
    }
    assert not failures, f"Example artifacts failed validation: {failures}"
    assert all(result.passed for result in results)
