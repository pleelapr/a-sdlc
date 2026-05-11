"""Tests for prd-architect template behaviors.

Validates that the prd-architect.md template contains the file path
verification gate (Step 2.4) with correct structure, config gating,
Glob-based verification, AskUserQuestion gate, and override logging.
"""

from pathlib import Path

import pytest


class TestFilePathVerificationGateTemplateContent:
    """Verify prd-architect.md contains Step 2.4 File Path Verification."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        """Load the prd-architect template content."""
        template_path = (
            Path(__file__).parent.parent
            / "src"
            / "a_sdlc"
            / "templates"
            / "prd-architect.md"
        )
        self.content = template_path.read_text(encoding="utf-8")

    def test_step_2_4_exists_after_step_2_3(self):
        """Step 2.4 exists after Step 2.3 (Identify Constraints)."""
        idx_2_3 = self.content.index("#### 2.3: Identify Constraints")
        idx_2_4 = self.content.index("#### 2.4: File Path Verification")
        assert idx_2_3 < idx_2_4

    def test_step_2_4_exists_before_round_table(self):
        """Step 2.4 exists before the Round-Table section."""
        idx_2_4 = self.content.index("#### 2.4: File Path Verification")
        idx_round_table = self.content.index(
            "### Round-Table: Architecture Review"
        )
        assert idx_2_4 < idx_round_table

    def test_step_2_4_exists_before_step_3(self):
        """Step 2.4 exists before Step 3 (Generate ADR Sections)."""
        idx_2_4 = self.content.index("#### 2.4: File Path Verification")
        idx_3 = self.content.index("### 3. Generate ADR Sections")
        assert idx_2_4 < idx_3

    def test_quality_enabled_gating(self):
        """Step 2.4 checks quality.enabled and skips when disabled."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "quality.enabled" in gate_content
        assert (
            "File path verification: skipped (quality not enabled)"
            in gate_content
        )

    def test_quality_disabled_skips_entirely(self):
        """When quality disabled, the step is skipped entirely."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "quality.enabled" in gate_content
        assert "false" in gate_content.lower()
        assert "skipped" in gate_content.lower()

    def test_glob_based_verification(self):
        """Step 2.4 uses Glob to verify file paths."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "Glob" in gate_content
        assert "cited_paths" in gate_content

    def test_line_number_stripping(self):
        """Step 2.4 strips line numbers before verification."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "line number" in gate_content.lower()
        assert "strip" in gate_content.lower()

    def test_invalid_paths_trigger_ask_user_question(self):
        """Invalid paths trigger AskUserQuestion gate."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "AskUserQuestion" in gate_content
        assert "invalid_paths" in gate_content

    def test_fix_paths_option_returns_to_step_2_2(self):
        """'Fix paths' option returns to Step 2.2 for re-analysis."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "Fix paths" in gate_content
        assert "Step 2.2" in gate_content

    def test_override_option_exists(self):
        """Override option exists in AskUserQuestion."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "Override" in gate_content
        assert "keep invalid paths" in gate_content

    def test_override_logs_correction(self):
        """Override option logs via log_correction with filepath-override category."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "log_correction" in gate_content
        assert 'category="filepath-override"' in gate_content

    def test_all_valid_paths_proceeds(self):
        """When all paths are valid, verification passes and proceeds."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "all" in gate_content.lower()
        assert "verified" in gate_content.lower()

    def test_fr_004_and_ac_004_traced(self):
        """Step 2.4 references FR-004 and AC-004."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "FR-004" in gate_content
        assert "AC-004" in gate_content

    def test_nfr_003_override_traced(self):
        """Step 2.4 references NFR-003 for the override option."""
        gate_start = self.content.index("#### 2.4: File Path Verification")
        gate_end = self.content.index(
            "### Round-Table: Architecture Review"
        )
        gate_content = self.content[gate_start:gate_end]
        assert "NFR-003" in gate_content
