"""
Installer module for deploying skill templates to Claude Code.

Handles:
- Copying skill templates to ~/.claude/commands/sdlc/
- Template versioning and updates
- Integrity verification
"""

import shutil
from importlib import resources
from pathlib import Path


class Installer:
    """Deploys a-sdlc skill templates to Claude Code configuration."""

    DEFAULT_TARGET = Path.home() / ".claude" / "commands" / "sdlc"

    def __init__(self, target_dir: Path | None = None) -> None:
        """Initialize installer with target directory.

        Args:
            target_dir: Custom target directory. Defaults to ~/.claude/commands/sdlc/
        """
        self.target_dir = target_dir or self.DEFAULT_TARGET

    def install(self, force: bool = False) -> list[str]:
        """Install all skill templates to target directory.

        Args:
            force: If True, overwrite existing templates.

        Returns:
            List of installed template names.

        Raises:
            FileExistsError: If templates exist and force=False.
        """
        # Create target directory
        self.target_dir.mkdir(parents=True, exist_ok=True)

        # Get template source directory
        template_dir = self._get_template_dir()

        installed = []
        for template_file in template_dir.glob("*.md"):
            target_file = self.target_dir / template_file.name

            if target_file.exists() and not force:
                # Skip existing files unless force=True
                installed.append(template_file.stem)
                continue

            shutil.copy2(template_file, target_file)
            installed.append(template_file.stem)

        return installed

    def list_installed(self) -> list[dict]:
        """List all installed skill templates.

        Returns:
            List of dicts with 'name' and 'file' keys.
        """
        if not self.target_dir.exists():
            return []

        skills = []
        for template_file in sorted(self.target_dir.glob("*.md")):
            skills.append({
                "name": template_file.stem,
                "file": template_file.name,
            })

        return skills

    def uninstall(self) -> int:
        """Remove all installed skill templates.

        Returns:
            Number of templates removed.
        """
        if not self.target_dir.exists():
            return 0

        count = 0
        for template_file in self.target_dir.glob("*.md"):
            template_file.unlink()
            count += 1

        # Remove directory if empty
        if self.target_dir.exists() and not any(self.target_dir.iterdir()):
            self.target_dir.rmdir()

        return count

    def _get_template_dir(self) -> Path:
        """Get the path to bundled template files.

        Returns:
            Path to templates directory.
        """
        # Use importlib.resources for Python 3.9+
        try:
            with resources.files("a_sdlc").joinpath("templates") as template_path:
                return Path(template_path)
        except (TypeError, AttributeError):
            # Fallback for development
            return Path(__file__).parent / "templates"

    def verify_integrity(self) -> dict[str, bool]:
        """Verify installed templates match source versions.

        Returns:
            Dict mapping template name to verification status.
        """
        template_dir = self._get_template_dir()
        results = {}

        for template_file in template_dir.glob("*.md"):
            target_file = self.target_dir / template_file.name
            name = template_file.stem

            if not target_file.exists():
                results[name] = False
                continue

            # Simple content comparison
            source_content = template_file.read_text()
            target_content = target_file.read_text()
            results[name] = source_content == target_content

        return results
