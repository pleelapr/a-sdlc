"""Tests for prd-split template quality gate behavior.

Validates that prd-split.md Step 5.5.5 has config-gated traceability
enforcement: quality.enabled=true removes the 'Acknowledged' bypass,
quality.enabled=false preserves it.

Also validates Step 5.5.6 granularity check: flags under-split
(task_count < fr_count * 0.5) and over-split (task_count > fr_count * 3)
with config-gated blocking behavior.
"""

from pathlib import Path

import pytest

TEMPLATE_PATH = (
    Path(__file__).parent.parent
    / "src"
    / "a_sdlc"
    / "templates"
    / "prd-split.md"
)


class TestTraceabilityGateTemplateContent:
    """Verify prd-split.md Step 5.5.5 contains config-gated traceability enforcement."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        """Load the prd-split template content."""
        self.content = TEMPLATE_PATH.read_text(encoding="utf-8")
        # Extract Step 5.5.5 section (ends at 5.5.6)
        start = self.content.index("**5.5.5: Present Results**")
        end = self.content.index("**5.5.6:")
        self.section = self.content[start:end]

    def test_step_5_5_5_exists(self):
        """Step 5.5.5 exists in the template."""
        assert "**5.5.5: Present Results**" in self.content

    def test_quality_enabled_check(self):
        """Step 5.5.5 checks quality.enabled from config."""
        assert "quality.enabled" in self.section

    def test_quality_enabled_removes_acknowledged(self):
        """When quality.enabled is true, 'Acknowledged' option is NOT available."""
        # Find the quality-enabled block
        quality_true_start = self.section.index("quality.enabled is true")
        # Find the next AskUserQuestion block after the quality-true marker
        ask_start = self.section.index("AskUserQuestion", quality_true_start)
        # Find the closing of this AskUserQuestion block
        ask_end = self.section.index("})", ask_start) + 2
        quality_enabled_ask = self.section[ask_start:ask_end]
        assert "Acknowledged" not in quality_enabled_ask

    def test_quality_enabled_has_three_options(self):
        """When quality.enabled is true, only 3 options exist: Add tasks, Fix traceability, Cancel."""
        quality_true_start = self.section.index("quality.enabled is true")
        ask_start = self.section.index("AskUserQuestion", quality_true_start)
        ask_end = self.section.index("})", ask_start) + 2
        quality_enabled_ask = self.section[ask_start:ask_end]
        assert "Add tasks" in quality_enabled_ask
        assert "Fix traceability" in quality_enabled_ask
        assert "Cancel" in quality_enabled_ask

    def test_quality_disabled_preserves_acknowledged(self):
        """When quality.enabled is false/absent, 'Acknowledged' option remains."""
        quality_false_start = self.section.index("quality.enabled is false")
        ask_start = self.section.index("AskUserQuestion", quality_false_start)
        ask_end = self.section.index("})", ask_start) + 2
        quality_disabled_ask = self.section[ask_start:ask_end]
        assert "Acknowledged" in quality_disabled_ask

    def test_quality_disabled_has_four_options(self):
        """When quality.enabled is false/absent, all 4 options exist."""
        quality_false_start = self.section.index("quality.enabled is false")
        ask_start = self.section.index("AskUserQuestion", quality_false_start)
        ask_end = self.section.index("})", ask_start) + 2
        quality_disabled_ask = self.section[ask_start:ask_end]
        assert "Add tasks" in quality_disabled_ask
        assert "Fix traceability" in quality_disabled_ask
        assert "Acknowledged" in quality_disabled_ask
        assert "Cancel" in quality_disabled_ask

    def test_quality_enabled_mentions_blocking(self):
        """When quality.enabled is true, the template states gaps are blocking."""
        quality_true_start = self.section.index("quality.enabled is true")
        quality_false_start = self.section.index("quality.enabled is false")
        quality_enabled_text = self.section[quality_true_start:quality_false_start]
        assert "blocking" in quality_enabled_text.lower()

    def test_cancel_option_always_available(self):
        """Cancel option is available in both quality-enabled and quality-disabled modes (NFR-003)."""
        # Quality enabled block
        quality_true_start = self.section.index("quality.enabled is true")
        ask_start_enabled = self.section.index("AskUserQuestion", quality_true_start)
        ask_end_enabled = self.section.index("})", ask_start_enabled) + 2
        quality_enabled_ask = self.section[ask_start_enabled:ask_end_enabled]

        # Quality disabled block
        quality_false_start = self.section.index("quality.enabled is false")
        ask_start_disabled = self.section.index("AskUserQuestion", quality_false_start)
        ask_end_disabled = self.section.index("})", ask_start_disabled) + 2
        quality_disabled_ask = self.section[ask_start_disabled:ask_end_disabled]

        assert "Cancel" in quality_enabled_ask
        assert "Cancel" in quality_disabled_ask

    def test_config_yaml_referenced(self):
        """Step 5.5.5 references .sdlc/config.yaml for quality config."""
        assert ".sdlc/config.yaml" in self.section

    def test_two_ask_user_question_blocks(self):
        """Step 5.5.5 has exactly two AskUserQuestion blocks (one per quality mode)."""
        count = self.section.count("AskUserQuestion")
        assert count == 2, f"Expected 2 AskUserQuestion blocks, found {count}"


class TestGranularityCheckTemplateContent:
    """Verify prd-split.md Step 5.5.6 contains granularity check logic."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        """Load the prd-split template content and extract Step 5.5.6 section."""
        self.content = TEMPLATE_PATH.read_text(encoding="utf-8")
        # Extract Step 5.5.6 section (ends at 5.5.7)
        start = self.content.index("**5.5.6: Granularity Check**")
        end = self.content.index("**5.5.7:")
        self.section = self.content[start:end]

    def test_step_5_5_6_exists(self):
        """Step 5.5.6 Granularity Check exists in the template."""
        assert "**5.5.6: Granularity Check**" in self.content

    def test_step_5_5_6_after_5_5_5(self):
        """Step 5.5.6 appears after Step 5.5.5 in the template."""
        pos_5_5_5 = self.content.index("**5.5.5: Present Results**")
        pos_5_5_6 = self.content.index("**5.5.6: Granularity Check**")
        assert pos_5_5_6 > pos_5_5_5

    def test_under_split_threshold(self):
        """Under-split detection uses task_count < fr_count * 0.5."""
        assert "task_count < fr_count * 0.5" in self.section

    def test_over_split_threshold(self):
        """Over-split detection uses task_count > fr_count * 3."""
        assert "task_count > fr_count * 3" in self.section

    def test_quality_enabled_check(self):
        """Step 5.5.6 checks quality.enabled from config."""
        assert "quality.enabled" in self.section

    def test_quality_enabled_blocks_with_ask_user(self):
        """When quality.enabled is true, AskUserQuestion blocks on granularity mismatch."""
        quality_true_start = self.section.index("quality.enabled is true")
        # Find the AskUserQuestion block and extract until the closing ```
        ask_start = self.section.index("AskUserQuestion", quality_true_start)
        ask_end = self.section.index("```", ask_start)
        quality_enabled_ask = self.section[ask_start:ask_end]
        assert "Adjust tasks" in quality_enabled_ask
        assert "Override" in quality_enabled_ask

    def test_override_option_available(self):
        """Override option is available for NFR-003 compliance."""
        quality_true_start = self.section.index("quality.enabled is true")
        ask_start = self.section.index("AskUserQuestion", quality_true_start)
        ask_end = self.section.index("```", ask_start)
        quality_enabled_ask = self.section[ask_start:ask_end]
        assert "Override" in quality_enabled_ask

    def test_quality_disabled_advisory_only(self):
        """When quality.enabled is false, only advisory note is shown (no AskUserQuestion)."""
        quality_false_start = self.section.index("quality.enabled is false")
        # After this point, there should be advisory text, not an AskUserQuestion
        remaining = self.section[quality_false_start:]
        assert "advisory" in remaining.lower()

    def test_pass_case_message(self):
        """Pass case displays confirmation when ratio is within bounds."""
        assert "Granularity check passed" in self.section

    def test_config_yaml_referenced(self):
        """Step 5.5.6 references .sdlc/config.yaml for quality config."""
        assert ".sdlc/config.yaml" in self.section

    def test_fr_count_zero_skip(self):
        """When fr_count is 0, the check is skipped."""
        assert "fr_count" in self.section
        assert "skip" in self.section.lower()

    def test_step_5_5_7_is_log_corrections(self):
        """Existing Step 5.5.6 was renumbered to 5.5.7 (Log Quality Gate Corrections)."""
        assert "**5.5.7: Log Quality Gate Corrections**" in self.content
