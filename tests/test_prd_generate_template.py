"""Tests for prd-generate template behaviors.

Validates that the prd-generate.md template contains the open question gate
(Step 4.5) with correct structure, config gating, and override logging.
"""

from pathlib import Path

import pytest


class TestOpenQuestionGateTemplateContent:
    """Verify prd-generate.md contains Step 4.5 Open Question Gate."""

    @pytest.fixture(autouse=True)
    def load_template(self):
        """Load the prd-generate template content."""
        template_path = (
            Path(__file__).parent.parent
            / "src"
            / "a_sdlc"
            / "templates"
            / "prd-generate.md"
        )
        self.content = template_path.read_text(encoding="utf-8")

    def test_step_4_5_exists_between_4_4_and_5(self):
        """Step 4.5 exists between Step 4.4 and Step 5."""
        idx_4_4 = self.content.index("### 4.5. Open Question Gate")
        idx_4_4_header = self.content.index("#### 4.4: Final Confirmation")
        idx_5 = self.content.index("### 5. Save PRD")
        assert idx_4_4_header < idx_4_4 < idx_5

    def test_quality_enabled_gating(self):
        """Step 4.5 checks quality.enabled and skips when disabled."""
        # Must reference quality.enabled
        assert "quality.enabled" in self.content
        # Must have skip logic when quality not enabled
        assert "Open question gate: skipped (quality not enabled)" in self.content

    def test_open_questions_scan(self):
        """Step 4.5 scans for ## Open Questions section with bullet items."""
        assert "## Open Questions" in self.content
        assert "open_questions" in self.content

    def test_ask_user_question_blocks_on_open_questions(self):
        """When open questions exist, AskUserQuestion blocks progression."""
        # The gate section must contain AskUserQuestion
        gate_start = self.content.index("### 4.5. Open Question Gate")
        gate_end = self.content.index("### 5. Save PRD")
        gate_content = self.content[gate_start:gate_end]
        assert "AskUserQuestion" in gate_content
        assert "unresolved open questions" in gate_content

    def test_resolve_now_option_loops_back(self):
        """'Resolve now' option loops back to edit the Open Questions section."""
        gate_start = self.content.index("### 4.5. Open Question Gate")
        gate_end = self.content.index("### 5. Save PRD")
        gate_content = self.content[gate_start:gate_end]
        assert "Resolve now" in gate_content
        assert "Loop back to Step 4.2" in gate_content

    def test_override_logs_correction(self):
        """Override option logs via log_correction with open-question-override category."""
        gate_start = self.content.index("### 4.5. Open Question Gate")
        gate_end = self.content.index("### 5. Save PRD")
        gate_content = self.content[gate_start:gate_end]
        assert "log_correction" in gate_content
        assert 'category="open-question-override"' in gate_content

    def test_quality_disabled_skips_entirely(self):
        """When quality disabled, the step is skipped entirely."""
        gate_start = self.content.index("### 4.5. Open Question Gate")
        gate_end = self.content.index("### 5. Save PRD")
        gate_content = self.content[gate_start:gate_end]
        assert "quality.enabled" in gate_content
        assert "false" in gate_content.lower()

    def test_gate_independent_of_challenge_system(self):
        """Gate operates independently of challenge system status."""
        gate_start = self.content.index("### 4.5. Open Question Gate")
        gate_end = self.content.index("### 5. Save PRD")
        gate_content = self.content[gate_start:gate_end]
        # Must state independence from challenge system
        assert "independently" in gate_content.lower()
        # Must NOT require challenge.enabled
        assert "challenge.enabled" not in gate_content
        assert "challenge.gates" not in gate_content

    def test_step_4_4_save_routes_to_4_5(self):
        """Step 4.4 Save option routes to Step 4.5, not directly to Step 5."""
        # Find the 4.4 section
        idx_4_4 = self.content.index("#### 4.4: Final Confirmation")
        idx_4_5 = self.content.index("### 4.5. Open Question Gate")
        section_4_4 = self.content[idx_4_4:idx_4_5]
        assert "Proceed to Step 4.5" in section_4_4

    def test_override_option_exists(self):
        """Override option exists in AskUserQuestion."""
        gate_start = self.content.index("### 4.5. Open Question Gate")
        gate_end = self.content.index("### 5. Save PRD")
        gate_content = self.content[gate_start:gate_end]
        assert "Override" in gate_content

    def test_prd_cannot_be_ready_with_open_questions(self):
        """Template states PRD cannot be set to 'ready' with unresolved open questions."""
        gate_start = self.content.index("### 4.5. Open Question Gate")
        gate_end = self.content.index("### 5. Save PRD")
        gate_content = self.content[gate_start:gate_end]
        assert "ready" in gate_content.lower()
        assert "cannot" in gate_content.lower()
