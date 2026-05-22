"""Tests for ContentBackend abstraction, LocalContentBackend, S3ContentBackend,
and ContentManager backend delegation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a_sdlc.core.content import (
    ContentBackend,
    ContentManager,
    LocalContentBackend,
    S3ContentBackend,
    get_content_manager,
)

# ============================================================================
# ContentBackend ABC tests
# ============================================================================


class TestContentBackendABC:
    """Verify that ContentBackend is a proper abstract base class."""

    def test_cannot_instantiate_directly(self):
        """ContentBackend cannot be instantiated."""
        with pytest.raises(TypeError):
            ContentBackend()  # type: ignore[abstract]

    def test_subclass_must_implement_all_methods(self):
        """A subclass missing any abstract method cannot be instantiated."""

        class IncompleteBackend(ContentBackend):
            def read_content(self, file_path: str) -> str | None:
                return None

        with pytest.raises(TypeError):
            IncompleteBackend()  # type: ignore[abstract]

    def test_complete_subclass_can_be_instantiated(self):
        """A subclass implementing all abstract methods can be instantiated."""

        class StubBackend(ContentBackend):
            def read_content(self, fp: str) -> str | None:
                return None

            def write_content(self, fp: str, content: str) -> str:
                return fp

            def delete_content(self, fp: str) -> bool:
                return False

            def list_content(self, d: str, suffix: str = ".md") -> list[str]:
                return []

            def exists(self, fp: str) -> bool:
                return False

        backend = StubBackend()
        assert isinstance(backend, ContentBackend)


# ============================================================================
# LocalContentBackend tests
# ============================================================================


class TestLocalContentBackend:
    """Tests for the local filesystem backend."""

    @pytest.fixture
    def backend(self, tmp_path: Path) -> LocalContentBackend:
        return LocalContentBackend()

    # -- read_content --------------------------------------------------------

    def test_read_existing_file(self, backend: LocalContentBackend, tmp_path: Path):
        fp = tmp_path / "test.md"
        fp.write_text("hello world", encoding="utf-8")
        assert backend.read_content(str(fp)) == "hello world"

    def test_read_nonexistent_file(self, backend: LocalContentBackend, tmp_path: Path):
        fp = tmp_path / "missing.md"
        assert backend.read_content(str(fp)) is None

    # -- write_content -------------------------------------------------------

    def test_write_creates_file(self, backend: LocalContentBackend, tmp_path: Path):
        fp = tmp_path / "output.md"
        result = backend.write_content(str(fp), "content here")
        assert result == str(fp)
        assert fp.read_text(encoding="utf-8") == "content here"

    def test_write_creates_parent_dirs(self, backend: LocalContentBackend, tmp_path: Path):
        fp = tmp_path / "a" / "b" / "c.md"
        backend.write_content(str(fp), "nested")
        assert fp.exists()
        assert fp.read_text(encoding="utf-8") == "nested"

    def test_write_overwrites_existing(self, backend: LocalContentBackend, tmp_path: Path):
        fp = tmp_path / "overwrite.md"
        backend.write_content(str(fp), "v1")
        backend.write_content(str(fp), "v2")
        assert fp.read_text(encoding="utf-8") == "v2"

    # -- delete_content ------------------------------------------------------

    def test_delete_existing_file(self, backend: LocalContentBackend, tmp_path: Path):
        fp = tmp_path / "del.md"
        fp.write_text("bye", encoding="utf-8")
        assert backend.delete_content(str(fp)) is True
        assert not fp.exists()

    def test_delete_nonexistent_file(self, backend: LocalContentBackend, tmp_path: Path):
        fp = tmp_path / "nope.md"
        assert backend.delete_content(str(fp)) is False

    # -- list_content --------------------------------------------------------

    def test_list_empty_directory(self, backend: LocalContentBackend, tmp_path: Path):
        d = tmp_path / "empty"
        d.mkdir()
        assert backend.list_content(str(d)) == []

    def test_list_nonexistent_directory(self, backend: LocalContentBackend, tmp_path: Path):
        d = tmp_path / "nonexistent"
        assert backend.list_content(str(d)) == []

    def test_list_filters_by_suffix(self, backend: LocalContentBackend, tmp_path: Path):
        (tmp_path / "a.md").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "c.md").write_text("c")
        result = backend.list_content(str(tmp_path), suffix=".md")
        assert len(result) == 2
        assert all(r.endswith(".md") for r in result)

    def test_list_returns_sorted(self, backend: LocalContentBackend, tmp_path: Path):
        for name in ("z.md", "a.md", "m.md"):
            (tmp_path / name).write_text(name)
        result = backend.list_content(str(tmp_path))
        basenames = [Path(p).name for p in result]
        assert basenames == ["a.md", "m.md", "z.md"]

    # -- exists --------------------------------------------------------------

    def test_exists_true(self, backend: LocalContentBackend, tmp_path: Path):
        fp = tmp_path / "present.md"
        fp.write_text("here")
        assert backend.exists(str(fp)) is True

    def test_exists_false(self, backend: LocalContentBackend, tmp_path: Path):
        assert backend.exists(str(tmp_path / "absent.md")) is False


# ============================================================================
# S3ContentBackend tests (moto)
# ============================================================================

try:
    import boto3
    from moto import mock_aws

    _HAS_MOTO = True
except ImportError:
    _HAS_MOTO = False

needs_moto = pytest.mark.skipif(not _HAS_MOTO, reason="moto and/or boto3 not installed")

BUCKET = "test-content-bucket"
BASE_PATH = "/home/user/.a-sdlc/content"


@needs_moto
class TestS3ContentBackend:
    """Tests for the S3 storage backend using moto mock."""

    @pytest.fixture
    def s3_backend(self):
        with mock_aws():
            # Create the bucket
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket=BUCKET)
            backend = S3ContentBackend(
                bucket=BUCKET,
                base_path=BASE_PATH,
            )
            yield backend

    # -- path helpers --------------------------------------------------------

    def test_to_key_strips_base_path(self, s3_backend: S3ContentBackend):
        result = s3_backend._to_key(f"{BASE_PATH}/proj/prds/P0001.md")
        assert result == "proj/prds/P0001.md"

    def test_to_key_handles_no_base(self):
        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket=BUCKET)
            backend = S3ContentBackend(bucket=BUCKET)
            result = backend._to_key("proj/prds/P0001.md")
            assert result == "proj/prds/P0001.md"

    def test_dir_to_prefix(self, s3_backend: S3ContentBackend):
        result = s3_backend._dir_to_prefix(f"{BASE_PATH}/proj/prds")
        assert result == "proj/prds/"

    # -- write & read --------------------------------------------------------

    def test_write_and_read(self, s3_backend: S3ContentBackend):
        fp = f"{BASE_PATH}/proj/prds/P0001.md"
        s3_backend.write_content(fp, "# My PRD\n\nContent here")
        content = s3_backend.read_content(fp)
        assert content == "# My PRD\n\nContent here"

    def test_read_nonexistent(self, s3_backend: S3ContentBackend):
        fp = f"{BASE_PATH}/proj/prds/MISSING.md"
        assert s3_backend.read_content(fp) is None

    def test_write_returns_path(self, s3_backend: S3ContentBackend):
        fp = f"{BASE_PATH}/proj/tasks/T001.md"
        result = s3_backend.write_content(fp, "task content")
        assert result == fp

    # -- delete --------------------------------------------------------------

    def test_delete_existing(self, s3_backend: S3ContentBackend):
        fp = f"{BASE_PATH}/proj/prds/DEL.md"
        s3_backend.write_content(fp, "to delete")
        assert s3_backend.delete_content(fp) is True
        assert s3_backend.read_content(fp) is None

    def test_delete_nonexistent(self, s3_backend: S3ContentBackend):
        fp = f"{BASE_PATH}/proj/prds/NOPE.md"
        assert s3_backend.delete_content(fp) is False

    # -- exists --------------------------------------------------------------

    def test_exists_true(self, s3_backend: S3ContentBackend):
        fp = f"{BASE_PATH}/proj/prds/EXISTS.md"
        s3_backend.write_content(fp, "present")
        assert s3_backend.exists(fp) is True

    def test_exists_false(self, s3_backend: S3ContentBackend):
        fp = f"{BASE_PATH}/proj/prds/GHOST.md"
        assert s3_backend.exists(fp) is False

    # -- list_content --------------------------------------------------------

    def test_list_content_empty(self, s3_backend: S3ContentBackend):
        result = s3_backend.list_content(f"{BASE_PATH}/empty")
        assert result == []

    def test_list_content_with_files(self, s3_backend: S3ContentBackend):
        for name in ("A.md", "B.md", "C.md"):
            s3_backend.write_content(f"{BASE_PATH}/proj/prds/{name}", f"# {name}")
        result = s3_backend.list_content(f"{BASE_PATH}/proj/prds")
        assert len(result) == 3
        basenames = [k.split("/")[-1] for k in result]
        assert basenames == ["A.md", "B.md", "C.md"]

    def test_list_content_filters_suffix(self, s3_backend: S3ContentBackend):
        s3_backend.write_content(f"{BASE_PATH}/proj/mix/a.md", "md")
        s3_backend.write_content(f"{BASE_PATH}/proj/mix/b.txt", "txt")
        result = s3_backend.list_content(f"{BASE_PATH}/proj/mix", suffix=".md")
        assert len(result) == 1
        assert result[0].endswith(".md")

    def test_list_content_only_direct_children(self, s3_backend: S3ContentBackend):
        s3_backend.write_content(f"{BASE_PATH}/proj/prds/direct.md", "direct")
        s3_backend.write_content(f"{BASE_PATH}/proj/prds/sub/nested.md", "nested")
        result = s3_backend.list_content(f"{BASE_PATH}/proj/prds")
        assert len(result) == 1
        assert result[0].endswith("direct.md")

    # -- import error --------------------------------------------------------

    def test_import_error_without_boto3(self, monkeypatch):
        """Verify helpful error when boto3 is missing."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError, match="boto3 is required"):
            S3ContentBackend(bucket="test")


# ============================================================================
# ContentManager backend delegation tests
# ============================================================================


class TestContentManagerWithLocalBackend:
    """Test that ContentManager delegates to LocalContentBackend correctly."""

    @pytest.fixture
    def cm(self, tmp_path: Path) -> ContentManager:
        return ContentManager(base_path=tmp_path)

    def test_default_backend_is_local(self, cm: ContentManager):
        assert isinstance(cm.backend, LocalContentBackend)

    def test_backend_property(self, cm: ContentManager):
        assert cm.backend is cm._backend

    def test_read_write_roundtrip(self, cm: ContentManager):
        fp = cm.get_prd_path("proj", "P001")
        cm.write_content(fp, "hello")
        assert cm.read_content(fp) == "hello"

    def test_delete_delegates(self, cm: ContentManager):
        fp = cm.get_task_path("proj", "T001")
        cm.write_content(fp, "task")
        assert cm.delete_content(fp) is True
        assert cm.read_content(fp) is None

    def test_write_prd_delegates(self, cm: ContentManager):
        path = cm.write_prd("proj", "P001", "My PRD", "content")
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "# My PRD" in text

    def test_write_task_delegates(self, cm: ContentManager):
        path = cm.write_task("proj", "T001", "My Task")
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "# T001: My Task" in text

    def test_task_file_exists_delegates(self, cm: ContentManager):
        assert cm.task_file_exists("proj", "T001") is False
        cm.write_task("proj", "T001", "Task")
        assert cm.task_file_exists("proj", "T001") is True

    def test_list_prd_files_delegates(self, cm: ContentManager):
        assert cm.list_prd_files("proj") == []
        cm.write_prd("proj", "P001", "PRD1", "")
        cm.write_prd("proj", "P002", "PRD2", "")
        result = cm.list_prd_files("proj")
        assert len(result) == 2

    def test_list_task_files_delegates(self, cm: ContentManager):
        cm.write_task("proj", "T001", "Task1")
        cm.write_task("proj", "T002", "Task2")
        result = cm.list_task_files("proj")
        assert len(result) == 2

    def test_list_design_files_delegates(self, cm: ContentManager):
        cm.write_design("proj", "P001", "design")
        result = cm.list_design_files("proj")
        assert len(result) == 1

    def test_delete_project_content(self, cm: ContentManager):
        cm.write_prd("proj", "P001", "PRD", "")
        cm.write_task("proj", "T001", "Task")
        assert cm.delete_project_content("proj") is True
        assert cm.list_prd_files("proj") == []
        assert cm.list_task_files("proj") == []

    def test_delete_project_content_nonexistent(self, cm: ContentManager):
        assert cm.delete_project_content("nonexistent") is False


class TestContentManagerWithCustomBackend:
    """Test that ContentManager properly delegates to a custom backend."""

    def test_uses_injected_backend(self, tmp_path: Path):
        backend = LocalContentBackend()
        cm = ContentManager(base_path=tmp_path, backend=backend)
        assert cm.backend is backend

    def test_write_and_read_via_custom_backend(self, tmp_path: Path):
        backend = LocalContentBackend()
        cm = ContentManager(base_path=tmp_path, backend=backend)
        fp = cm.get_prd_path("proj", "P001")
        cm.write_content(fp, "custom backend content")
        assert cm.read_content(fp) == "custom backend content"


@needs_moto
class TestContentManagerWithS3Backend:
    """Integration: ContentManager with S3ContentBackend using moto."""

    @pytest.fixture
    def cm(self, tmp_path: Path):
        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket=BUCKET)
            backend = S3ContentBackend(
                bucket=BUCKET,
                base_path=str(tmp_path),
            )
            cm = ContentManager(base_path=tmp_path, backend=backend)
            yield cm

    def test_write_and_read_prd(self, cm: ContentManager):
        path = cm.write_prd("proj", "P001", "Title", "body")
        content = cm.read_content(path)
        assert content is not None
        assert "# Title" in content

    def test_write_and_read_task(self, cm: ContentManager):
        path = cm.write_task("proj", "T001", "My Task", "desc")
        content = cm.read_content(path)
        assert content is not None
        assert "T001" in content

    def test_delete_content(self, cm: ContentManager):
        path = cm.write_prd("proj", "P001", "Title", "body")
        assert cm.delete_content(path) is True
        assert cm.read_content(path) is None

    def test_task_file_exists(self, cm: ContentManager):
        assert cm.task_file_exists("proj", "T001") is False
        cm.write_task("proj", "T001", "Task")
        assert cm.task_file_exists("proj", "T001") is True

    def test_write_task_skip_if_exists(self, cm: ContentManager):
        cm.write_task("proj", "T001", "Original")
        original_content = cm.read_content(cm.get_task_path("proj", "T001"))
        cm.write_task("proj", "T001", "Overwritten", skip_if_exists=True)
        current_content = cm.read_content(cm.get_task_path("proj", "T001"))
        assert current_content == original_content


# ============================================================================
# Singleton / backward compatibility tests
# ============================================================================


class TestGetContentManagerSingleton:
    """Verify that get_content_manager() singleton still works."""

    def test_returns_content_manager(self):
        import a_sdlc.core.content as mod

        old = mod._content_manager
        try:
            mod._content_manager = None
            cm = get_content_manager()
            assert isinstance(cm, ContentManager)
            assert isinstance(cm.backend, LocalContentBackend)
        finally:
            mod._content_manager = old

    def test_returns_same_instance(self):
        import a_sdlc.core.content as mod

        old = mod._content_manager
        try:
            mod._content_manager = None
            cm1 = get_content_manager()
            cm2 = get_content_manager()
            assert cm1 is cm2
        finally:
            mod._content_manager = old


class TestBackwardCompatibleImports:
    """Verify that all existing import patterns still work."""

    def test_import_content_manager(self):
        from a_sdlc.core.content import ContentManager  # noqa: F811
        assert ContentManager is not None

    def test_import_get_content_manager(self):
        from a_sdlc.core.content import get_content_manager  # noqa: F811
        assert callable(get_content_manager)

    def test_import_get_data_dir(self):
        from a_sdlc.core.content import get_data_dir
        assert callable(get_data_dir)

    def test_import_content_backend(self):
        from a_sdlc.core.content import ContentBackend  # noqa: F811
        assert ContentBackend is not None

    def test_import_local_backend(self):
        from a_sdlc.core.content import LocalContentBackend  # noqa: F811
        assert LocalContentBackend is not None

    def test_import_s3_backend(self):
        from a_sdlc.core.content import S3ContentBackend  # noqa: F811
        assert S3ContentBackend is not None

    def test_core_init_exports(self):
        from a_sdlc.core import ContentManager, get_content_manager  # noqa: F811
        assert ContentManager is not None
        assert callable(get_content_manager)


# ============================================================================
# ContentManager preserves existing behavior tests
# ============================================================================


class TestContentManagerPreservesExistingBehavior:
    """Verify refactored ContentManager produces identical results to the original."""

    @pytest.fixture
    def cm(self, tmp_path: Path) -> ContentManager:
        return ContentManager(base_path=tmp_path)

    def test_write_prd_with_empty_content(self, cm: ContentManager):
        path = cm.write_prd("proj", "P001", "My Title", "")
        text = path.read_text(encoding="utf-8")
        assert text == "# My Title\n\n"

    def test_write_prd_with_content_no_header(self, cm: ContentManager):
        path = cm.write_prd("proj", "P001", "My Title", "Some body text")
        text = path.read_text(encoding="utf-8")
        assert text == "# My Title\n\nSome body text"

    def test_write_prd_with_header_content(self, cm: ContentManager):
        path = cm.write_prd("proj", "P001", "My Title", "# Custom Header\n\nContent")
        text = path.read_text(encoding="utf-8")
        assert text == "# Custom Header\n\nContent"

    def test_write_task_simple(self, cm: ContentManager):
        path = cm.write_task(
            "proj", "T001", "Test Task",
            description="Do something",
            priority="high",
            status="pending",
            component="api",
            prd_id="P001",
        )
        text = path.read_text(encoding="utf-8")
        assert "# T001: Test Task" in text
        assert "**Status:** pending" in text
        assert "**Priority:** high" in text
        assert "**Component:** api" in text
        assert "**PRD:** P001" in text
        assert "Do something" in text

    def test_write_task_rich_content(self, cm: ContentManager):
        rich = "# T001: Rich Task\n\n## Section\n\nContent here"
        path = cm.write_task("proj", "T001", "Rich Task", description=rich)
        text = path.read_text(encoding="utf-8")
        assert text == rich

    def test_write_task_skip_if_exists(self, cm: ContentManager):
        cm.write_task("proj", "T001", "First Version")
        first_content = cm.read_task("proj", "T001")
        cm.write_task("proj", "T001", "Second Version", skip_if_exists=True)
        second_content = cm.read_task("proj", "T001")
        assert first_content == second_content

    def test_parse_task_content(self, cm: ContentManager):
        content = """# T001: Test

**Status:** in_progress
**Priority:** high
**Component:** api
**PRD:** P001
**Dependencies:** T000

## Description

Build the thing
"""
        result = cm.parse_task_content(content)
        assert result["status"] == " in_progress"
        assert result["priority"] == " high"
        assert result["component"] == " api"
        assert result["prd_id"] == " P001"
        assert result["dependencies"] == ["T000"]
        assert "Build the thing" in result["description"]

    def test_design_lifecycle(self, cm: ContentManager):
        path = cm.write_design("proj", "P001", "# Design\n\nArch")
        assert path.exists()
        content = cm.read_design("proj", "P001")
        assert content == "# Design\n\nArch"
        assert cm.delete_design("proj", "P001") is True
        assert cm.read_design("proj", "P001") is None

    def test_get_prd_dir_creates_directory(self, cm: ContentManager):
        prd_dir = cm.get_prd_dir("proj")
        assert prd_dir.exists()
        assert prd_dir.name == "prds"

    def test_get_task_dir_creates_directory(self, cm: ContentManager):
        task_dir = cm.get_task_dir("proj")
        assert task_dir.exists()
        assert task_dir.name == "tasks"

    def test_ensure_dirs_creates_base(self, tmp_path: Path):
        base = tmp_path / "sub" / "content"
        ContentManager(base_path=base)
        assert base.exists()
