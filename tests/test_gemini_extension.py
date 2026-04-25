"""Tests for Gemini CLI extension builder."""

import json

from a_sdlc import __version__
from a_sdlc.gemini_extension import build_extension_dir, generate_manifest


class TestGenerateManifest:
    """Tests for generate_manifest()."""

    def test_has_required_keys(self):
        manifest = generate_manifest()
        assert "name" in manifest
        assert "version" in manifest
        assert "description" in manifest
        assert "mcpServers" in manifest

    def test_name_is_a_sdlc(self):
        manifest = generate_manifest()
        assert manifest["name"] == "a-sdlc"

    def test_version_matches_package(self):
        manifest = generate_manifest()
        assert manifest["version"] == __version__

    def test_has_asdlc_mcp_server(self):
        manifest = generate_manifest()
        assert "asdlc" in manifest["mcpServers"]

    def test_mcp_server_uses_uvx(self):
        manifest = generate_manifest()
        asdlc = manifest["mcpServers"]["asdlc"]
        assert asdlc["command"] == "uvx"
        assert asdlc["args"] == ["a-sdlc", "serve"]

    def test_has_context_file_name(self):
        manifest = generate_manifest()
        assert manifest["contextFileName"] == "GEMINI.md"


class TestBuildExtensionDir:
    """Tests for build_extension_dir()."""

    def test_creates_output_directory(self, tmp_path):
        output = tmp_path / "ext"
        build_extension_dir(output)
        assert output.exists()

    def test_creates_manifest(self, tmp_path):
        output = tmp_path / "ext"
        build_extension_dir(output)
        manifest_path = output / "gemini-extension.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["name"] == "a-sdlc"

    def test_creates_commands_dir(self, tmp_path):
        output = tmp_path / "ext"
        build_extension_dir(output)
        commands_dir = output / "commands" / "sdlc"
        assert commands_dir.exists()

    def test_creates_toml_files(self, tmp_path):
        output = tmp_path / "ext"
        build_extension_dir(output)
        toml_files = list((output / "commands" / "sdlc").glob("*.toml"))
        assert len(toml_files) >= 40

    def test_creates_gemini_md(self, tmp_path):
        output = tmp_path / "ext"
        build_extension_dir(output)
        gemini_md = output / "GEMINI.md"
        assert gemini_md.exists()
        content = gemini_md.read_text()
        assert "Gemini CLI" in content

    def test_gemini_md_has_no_placeholders(self, tmp_path):
        output = tmp_path / "ext"
        build_extension_dir(output)
        content = (output / "GEMINI.md").read_text()
        assert "{{PROJECT_OVERVIEW}}" not in content
        assert "{{DEVELOPMENT_COMMANDS}}" not in content

    def test_manifest_is_valid_json(self, tmp_path):
        output = tmp_path / "ext"
        build_extension_dir(output)
        manifest_path = output / "gemini-extension.json"
        manifest = json.loads(manifest_path.read_text())
        assert isinstance(manifest, dict)

    def test_idempotent(self, tmp_path):
        output = tmp_path / "ext"
        build_extension_dir(output)
        # Run again — should not error
        build_extension_dir(output)
        assert (output / "gemini-extension.json").exists()

    def test_returns_output_dir(self, tmp_path):
        output = tmp_path / "ext"
        result = build_extension_dir(output)
        assert result == output
