"""Tests for SDLC-T00176: Routing + Team Gaps (P0027/P0028).

Covers:
- Three-tier routing in get_available_work (REM-006/007/015)
- Sprint-scoped teams (REM-011/012)
- Health config from YAML (REM-013)
- self_assess MCP tool (REM-008)
- auto_compose_team MCP tool (REM-014)
- enforce_team_health MCP tool (REM-016)
- Migration v12->v13 correctness
- Backward compatibility (no governance config = original behavior)
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from a_sdlc.core.database import SCHEMA_VERSION, Database

# =============================================================================
# Database Fixtures
# =============================================================================


@pytest.fixture
def temp_db():
    """Create a temporary database with current schema and test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = Database(db_path=db_path)
        db.create_project("test-project", "Test Project", "/tmp/test")
        db.create_sprint(
            sprint_id="TEST-S0001",
            project_id="test-project",
            title="Sprint 1",
            goal="Test sprint",
        )
        db.create_prd(
            prd_id="TEST-P0001",
            project_id="test-project",
            title="Test PRD",
            file_path="/tmp/test/prds/TEST-P0001.md",
            sprint_id="TEST-S0001",
        )
        # Create agents with different personas
        db.create_agent(
            agent_id="TEST-A001",
            project_id="test-project",
            persona_type="backend_engineer",
            display_name="Backend Agent",
        )
        db.create_agent(
            agent_id="TEST-A002",
            project_id="test-project",
            persona_type="frontend_engineer",
            display_name="Frontend Agent",
        )
        # Create tasks with different components and priorities
        db.create_task(
            task_id="TEST-T00001",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Backend API",
            file_path="/tmp/test/tasks/TEST-T00001.md",
            priority="high",
            component="backend",
        )
        db.create_task(
            task_id="TEST-T00002",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Frontend UI",
            file_path="/tmp/test/tasks/TEST-T00002.md",
            priority="medium",
            component="frontend",
        )
        db.create_task(
            task_id="TEST-T00003",
            project_id="test-project",
            prd_id="TEST-P0001",
            title="Critical Fix",
            file_path="/tmp/test/tasks/TEST-T00003.md",
            priority="critical",
            component="api",
        )
        yield db


# =============================================================================
# MCP Tool Fixtures
# =============================================================================


@pytest.fixture
def mock_db():
    """Mock the database singleton returned by get_db()."""
    with patch("a_sdlc.server.get_db") as mock:
        db = MagicMock()
        mock.return_value = db
        yield db


@pytest.fixture
def mock_project_id():
    """Mock _get_current_project_id to return a test project ID."""
    with patch("a_sdlc.server._get_current_project_id") as mock:
        mock.return_value = "test-project"
        yield mock


@pytest.fixture
def mock_no_project():
    """Mock _get_current_project_id to return None."""
    with patch("a_sdlc.server._get_current_project_id") as mock:
        mock.return_value = None
        yield mock


def _import_tool(name):
    """Import a tool function from the server module."""
    import a_sdlc.server as server_module
    return getattr(server_module, name)


# =============================================================================
# 1. Schema Version & Migration Tests
# =============================================================================


class TestSchemaVersion:
    """Test schema version is bumped and migration works."""

    def test_schema_version_is_14(self):
        assert SCHEMA_VERSION == 14

    def test_fresh_db_has_sprint_id_on_teams(self, temp_db):
        """Fresh database should have sprint_id column on agent_teams."""
        with temp_db.connection() as conn:
            info = conn.execute("PRAGMA table_info(agent_teams)").fetchall()
            columns = {row["name"] for row in info}
            assert "sprint_id" in columns

    def test_migration_v12_to_v13(self):
        """Migration from v12 adds sprint_id to agent_teams.
        Note: This also triggers v13->v14 migration if current version is 14.
        """
        import sqlite3

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "migrate.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")

            # Create a minimal v12 database
            conn.executescript("""
                CREATE TABLE schema_version (version INTEGER PRIMARY KEY);
                INSERT INTO schema_version (version) VALUES (12);

                CREATE TABLE projects (
                    id TEXT PRIMARY KEY,
                    shortname TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE execution_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT DEFAULT 'running',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE sprints (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    goal TEXT,
                    status TEXT DEFAULT 'planned',
                    external_id TEXT,
                    external_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE prds (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    sprint_id TEXT,
                    title TEXT NOT NULL,
                    file_path TEXT,
                    status TEXT DEFAULT 'draft',
                    source TEXT,
                    version TEXT DEFAULT '1.0.0',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ready_at TIMESTAMP,
                    split_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY (sprint_id) REFERENCES sprints(id) ON DELETE SET NULL
                );

                CREATE TABLE tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    prd_id TEXT,
                    title TEXT NOT NULL,
                    file_path TEXT,
                    status TEXT DEFAULT 'pending',
                    priority TEXT DEFAULT 'medium',
                    component TEXT,
                    assigned_agent_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY (prd_id) REFERENCES prds(id) ON DELETE SET NULL
                );

                CREATE TABLE agents (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    persona_type TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    permissions_profile TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_by TEXT,
                    team_id TEXT,
                    reports_to_agent_id TEXT,
                    hired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    suspended_at TIMESTAMP,
                    retired_at TIMESTAMP,
                    performance_score REAL DEFAULT 50.0,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                );

                CREATE TABLE agent_teams (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    lead_agent_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
                    FOREIGN KEY (lead_agent_id) REFERENCES agents(id) ON DELETE SET NULL
                );

                CREATE TABLE task_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    released_at TIMESTAMP,
                    status TEXT DEFAULT 'active',
                    release_reason TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE,
                    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
                );

                CREATE TABLE agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_agent_id TEXT NOT NULL,
                    to_agent_id TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    related_task_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_at TIMESTAMP
                );

                CREATE TABLE agent_performance (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_id TEXT NOT NULL,
                    sprint_id TEXT,
                    tasks_completed INTEGER DEFAULT 0,
                    tasks_failed INTEGER DEFAULT 0,
                    avg_quality_score REAL,
                    avg_completion_time_min REAL,
                    corrections_count INTEGER DEFAULT 0,
                    review_pass_rate REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(agent_id, sprint_id)
                );

                CREATE TABLE requirements (
                    id TEXT PRIMARY KEY,
                    prd_id TEXT NOT NULL,
                    req_type TEXT NOT NULL,
                    req_number TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    depth TEXT DEFAULT 'structural',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(prd_id, req_number)
                );

                CREATE TABLE requirement_links (
                    requirement_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (requirement_id, task_id)
                );

                CREATE TABLE ac_verifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    requirement_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    verified_by TEXT,
                    evidence_type TEXT,
                    evidence TEXT,
                    verified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(requirement_id, task_id)
                );

                CREATE TABLE challenge_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    artifact_type TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    round_number INTEGER NOT NULL,
                    objections TEXT,
                    responses TEXT,
                    verdict TEXT,
                    challenger_context TEXT,
                    status TEXT DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(artifact_type, artifact_id, round_number)
                );
            """)
            conn.close()

            # Open via Database class which triggers migration
            db = Database(db_path=db_path)

            # Verify sprint_id column exists
            with db.connection() as c:
                version = c.execute("SELECT version FROM schema_version").fetchone()[0]
                assert version == SCHEMA_VERSION

                info = c.execute("PRAGMA table_info(agent_teams)").fetchall()
                columns = {row["name"] for row in info}
                assert "sprint_id" in columns


# =============================================================================
# 2. Sprint-Scoped Team Tests (REM-011 / REM-012)
# =============================================================================


class TestSprintScopedTeams:
    """Test teams can be scoped to sprints."""

    def test_create_team_with_sprint_id(self, temp_db):
        """create_agent_team should accept sprint_id."""
        team = temp_db.create_agent_team(
            name="Sprint Team",
            project_id="test-project",
            sprint_id="TEST-S0001",
        )
        assert team["name"] == "Sprint Team"
        assert team["sprint_id"] == "TEST-S0001"

    def test_create_team_without_sprint_id(self, temp_db):
        """Backward compatibility: sprint_id defaults to None."""
        team = temp_db.create_agent_team(
            name="Global Team",
            project_id="test-project",
        )
        assert team["sprint_id"] is None

    def test_list_teams_filtered_by_sprint(self, temp_db):
        """list_agent_teams with sprint_id returns scoped + unscoped teams."""
        # Create a second sprint for the "other" team
        temp_db.create_sprint(
            sprint_id="TEST-S0002",
            project_id="test-project",
            title="Sprint 2",
            goal="Other sprint",
        )
        temp_db.create_agent_team("Sprint Team", "test-project", sprint_id="TEST-S0001")
        temp_db.create_agent_team("Global Team", "test-project")
        temp_db.create_agent_team("Other Sprint Team", "test-project", sprint_id="TEST-S0002")

        teams = temp_db.list_agent_teams("test-project", sprint_id="TEST-S0001")
        names = {t["name"] for t in teams}
        assert "Sprint Team" in names
        assert "Global Team" in names  # Unscoped teams are included
        assert "Other Sprint Team" not in names  # Different sprint (TEST-S0002) excluded

    def test_list_teams_without_sprint_filter(self, temp_db):
        """list_agent_teams without sprint_id returns all teams."""
        temp_db.create_agent_team("Team A", "test-project", sprint_id="TEST-S0001")
        temp_db.create_agent_team("Team B", "test-project")

        teams = temp_db.list_agent_teams("test-project")
        assert len(teams) == 2

    def test_get_team_composition_sprint_filter(self, temp_db):
        """get_team_composition with sprint_id respects sprint scoping."""
        team = temp_db.create_agent_team(
            "Sprint Team", "test-project", sprint_id="TEST-S0001"
        )
        # Should be found with matching sprint
        result = temp_db.get_team_composition(team["id"], sprint_id="TEST-S0001")
        assert result["name"] == "Sprint Team"

    def test_get_team_composition_wrong_sprint_raises(self, temp_db):
        """get_team_composition with wrong sprint_id raises ValueError."""
        team = temp_db.create_agent_team(
            "Sprint Team", "test-project", sprint_id="TEST-S0001"
        )
        with pytest.raises(ValueError, match="Team not found"):
            temp_db.get_team_composition(team["id"], sprint_id="WRONG-S9999")


# =============================================================================
# 3. Three-Tier Routing Tests (REM-006 / REM-007 / REM-015)
# =============================================================================


class TestThreeTierRouting:
    """Test three-tier routing in get_available_work."""

    def test_routing_without_component_map(self, temp_db):
        """Without component_map, all tasks are tier 2 (priority-sorted)."""
        tasks = temp_db.get_available_work(
            "test-project", "TEST-A001"
        )
        # Should return tasks sorted by priority: critical > high > medium
        assert len(tasks) == 3
        assert tasks[0]["priority"] == "critical"
        assert tasks[1]["priority"] == "high"
        assert tasks[2]["priority"] == "medium"
        # All tier 2 when no component map
        assert all(t["routing_tier"] == 2 for t in tasks)

    def test_routing_with_component_map_tier1(self, temp_db):
        """Backend engineer gets backend tasks in tier 1."""
        component_map = {
            "backend": ["backend_engineer"],
            "frontend": ["frontend_engineer"],
            "api": ["backend_engineer"],
        }
        tasks = temp_db.get_available_work(
            "test-project", "TEST-A001", component_map=component_map
        )
        # Backend agent should get tier 1 for backend + api tasks
        tier1 = [t for t in tasks if t["routing_tier"] == 1]
        tier3 = [t for t in tasks if t["routing_tier"] == 3]

        assert len(tier1) == 2  # backend + api tasks
        tier1_components = {t["component"] for t in tier1}
        assert "backend" in tier1_components
        assert "api" in tier1_components

        # Frontend task should be tier 3 (fallback) since tier 1 exists
        assert len(tier3) == 1
        assert tier3[0]["component"] == "frontend"

    def test_routing_frontend_agent(self, temp_db):
        """Frontend engineer gets frontend tasks in tier 1."""
        component_map = {
            "backend": ["backend_engineer"],
            "frontend": ["frontend_engineer"],
            "api": ["backend_engineer"],
        }
        tasks = temp_db.get_available_work(
            "test-project", "TEST-A002", component_map=component_map
        )
        tier1 = [t for t in tasks if t["routing_tier"] == 1]
        assert len(tier1) == 1
        assert tier1[0]["component"] == "frontend"

    def test_routing_includes_performance_score(self, temp_db):
        """Routed tasks include agent_performance_score."""
        tasks = temp_db.get_available_work("test-project", "TEST-A001")
        assert all("agent_performance_score" in t for t in tasks)
        # Default performance score is 50.0
        assert tasks[0]["agent_performance_score"] == 50.0

    def test_routing_with_sprint_filter(self, temp_db):
        """Routing respects sprint_id filter."""
        component_map = {"backend": ["backend_engineer"]}
        tasks = temp_db.get_available_work(
            "test-project",
            "TEST-A001",
            sprint_id="TEST-S0001",
            component_map=component_map,
        )
        assert len(tasks) == 3  # All tasks belong to TEST-S0001 via PRD

    def test_routing_agent_not_found(self, temp_db):
        """Raise ValueError for nonexistent agent."""
        with pytest.raises(ValueError, match="Agent not found"):
            temp_db.get_available_work("test-project", "NONEXISTENT")

    def test_routing_tier1_before_tier3(self, temp_db):
        """Tier 1 tasks appear before tier 3 tasks in results."""
        component_map = {"backend": ["backend_engineer"]}
        tasks = temp_db.get_available_work(
            "test-project", "TEST-A001", component_map=component_map
        )
        tiers = [t["routing_tier"] for t in tasks]
        # All tier 1 items should come before tier 3
        tier1_positions = [i for i, t in enumerate(tiers) if t == 1]
        tier3_positions = [i for i, t in enumerate(tiers) if t == 3]
        if tier1_positions and tier3_positions:
            assert max(tier1_positions) < min(tier3_positions)


# =============================================================================
# 4. self_assess MCP Tool Tests (REM-008)
# =============================================================================


class TestSelfAssess:
    """Test self_assess MCP tool."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("self_assess")
        mock_db.get_agent.return_value = {
            "id": "TEST-A001",
            "persona_type": "backend_engineer",
            "performance_score": 75.0,
        }
        mock_db.get_task.return_value = {
            "id": "TEST-T00001",
            "component": "backend",
        }
        mock_db.compute_agent_performance.return_value = {
            "total_completed": 8,
            "total_failed": 2,
        }

        with patch("a_sdlc.server._load_routing_config") as mock_config:
            mock_config.return_value = {
                "component_map": {"backend": ["backend_engineer"]}
            }
            result = tool("TEST-A001", "TEST-T00001")

        assert result["status"] == "ok"
        assert result["confidence"] > 0
        assert result["factors"]["component_match"] is True
        assert result["factors"]["component_score"] == 30.0

    def test_no_component_match(self, mock_db, mock_project_id):
        tool = _import_tool("self_assess")
        mock_db.get_agent.return_value = {
            "id": "TEST-A001",
            "persona_type": "backend_engineer",
            "performance_score": 50.0,
        }
        mock_db.get_task.return_value = {
            "id": "TEST-T00002",
            "component": "frontend",
        }
        mock_db.compute_agent_performance.return_value = {
            "total_completed": 0,
            "total_failed": 0,
        }

        with patch("a_sdlc.server._load_routing_config") as mock_config:
            mock_config.return_value = {
                "component_map": {"frontend": ["frontend_engineer"]}
            }
            result = tool("TEST-A001", "TEST-T00002")

        assert result["status"] == "ok"
        assert result["factors"]["component_match"] is False
        assert result["factors"]["component_score"] == 0.0

    def test_agent_not_found(self, mock_db, mock_project_id):
        tool = _import_tool("self_assess")
        mock_db.get_agent.return_value = None
        result = tool("NONEXISTENT", "TEST-T00001")
        assert result["status"] == "error"
        assert "Agent not found" in result["message"]

    def test_task_not_found(self, mock_db, mock_project_id):
        tool = _import_tool("self_assess")
        mock_db.get_agent.return_value = {"id": "TEST-A001", "persona_type": "be", "performance_score": 50}
        mock_db.get_task.return_value = None
        result = tool("TEST-A001", "NONEXISTENT")
        assert result["status"] == "error"
        assert "Task not found" in result["message"]

    def test_recommendation_levels(self, mock_db, mock_project_id):
        """Test recommendation classification thresholds."""
        tool = _import_tool("self_assess")
        mock_db.get_agent.return_value = {
            "id": "TEST-A001",
            "persona_type": "backend_engineer",
            "performance_score": 90.0,
        }
        mock_db.get_task.return_value = {"id": "T1", "component": "backend"}
        mock_db.compute_agent_performance.return_value = {
            "total_completed": 10,
            "total_failed": 0,
        }

        with patch("a_sdlc.server._load_routing_config") as mock_config:
            mock_config.return_value = {
                "component_map": {"backend": ["backend_engineer"]}
            }
            result = tool("TEST-A001", "T1")

        # 30 (component) + 40 (100% success) + 27 (90/100*30) = 97
        assert result["recommendation"] == "strong_match"


# =============================================================================
# 5. auto_compose_team MCP Tool Tests (REM-014)
# =============================================================================


class TestAutoComposeTeam:
    """Test auto_compose_team MCP tool."""

    def test_happy_path(self, mock_db, mock_project_id):
        tool = _import_tool("auto_compose_team")
        mock_db.get_sprint.return_value = {"id": "S1", "project_id": "test-project"}
        mock_db.list_tasks_by_sprint.return_value = [
            {"id": "T1", "component": "backend"},
            {"id": "T2", "component": "backend"},
            {"id": "T3", "component": "frontend"},
        ]
        mock_db.list_agents.return_value = [
            {"id": "A1", "persona_type": "backend_engineer", "display_name": "BE", "performance_score": 80.0},
            {"id": "A2", "persona_type": "frontend_engineer", "display_name": "FE", "performance_score": 70.0},
        ]

        with patch("a_sdlc.server._load_routing_config") as mock_config:
            mock_config.return_value = {
                "component_map": {
                    "backend": ["backend_engineer"],
                    "frontend": ["frontend_engineer"],
                }
            }
            result = tool("S1")

        assert result["status"] == "ok"
        assert result["total_agents_proposed"] == 2
        assert len(result["coverage_gaps"]) == 0

    def test_no_project(self, mock_db, mock_no_project):
        tool = _import_tool("auto_compose_team")
        result = tool("S1")
        assert result["status"] == "no_project"

    def test_sprint_not_found(self, mock_db, mock_project_id):
        tool = _import_tool("auto_compose_team")
        mock_db.get_sprint.return_value = None
        result = tool("NONEXISTENT")
        assert result["status"] == "error"
        assert "Sprint not found" in result["message"]

    def test_coverage_gaps(self, mock_db, mock_project_id):
        """When no agent matches a component, it appears in coverage_gaps."""
        tool = _import_tool("auto_compose_team")
        mock_db.get_sprint.return_value = {"id": "S1", "project_id": "test-project"}
        mock_db.list_tasks_by_sprint.return_value = [
            {"id": "T1", "component": "security"},
        ]
        mock_db.list_agents.return_value = [
            {"id": "A1", "persona_type": "backend_engineer", "display_name": "BE", "performance_score": 50.0},
        ]

        with patch("a_sdlc.server._load_routing_config") as mock_config:
            mock_config.return_value = {
                "component_map": {"security": ["security_engineer"]}
            }
            result = tool("S1")

        assert result["status"] == "ok"
        assert "security" in result["coverage_gaps"]
        assert result["total_agents_proposed"] == 0


# =============================================================================
# 6. enforce_team_health MCP Tool Tests (REM-016)
# =============================================================================


class TestEnforceTeamHealth:
    """Test enforce_team_health MCP tool."""

    def test_healthy_team(self, mock_db, mock_project_id):
        tool = _import_tool("enforce_team_health")
        mock_db.get_team_composition.return_value = {
            "id": 1,
            "name": "Team Alpha",
            "members": [
                {
                    "id": "A1", "display_name": "Agent 1",
                    "performance_score": 80.0, "status": "active",
                },
            ],
        }
        mock_db.compute_agent_performance.return_value = {
            "total_completed": 10,
            "total_failed": 1,
        }

        with patch("a_sdlc.server._load_governance_health_config") as mock_config:
            mock_config.return_value = {
                "quality_threshold": 40,
                "error_rate_threshold_pct": 30,
                "stalled_timeout_min": 30,
                "action": "alert",
            }
            result = tool(1)

        assert result["status"] == "ok"
        assert result["summary"]["healthy"] == 1
        assert result["summary"]["unhealthy"] == 0
        assert len(result["actions_taken"]) == 0

    def test_unhealthy_agent_alert(self, mock_db, mock_project_id):
        tool = _import_tool("enforce_team_health")
        mock_db.get_team_composition.return_value = {
            "id": 1,
            "name": "Team Alpha",
            "members": [
                {
                    "id": "A1", "display_name": "Agent 1",
                    "performance_score": 20.0, "status": "active",
                },
            ],
        }
        mock_db.compute_agent_performance.return_value = {
            "total_completed": 5,
            "total_failed": 5,
        }

        with patch("a_sdlc.server._load_governance_health_config") as mock_config:
            mock_config.return_value = {
                "quality_threshold": 40,
                "error_rate_threshold_pct": 30,
                "stalled_timeout_min": 30,
                "action": "alert",
            }
            result = tool(1)

        assert result["status"] == "ok"
        assert result["summary"]["unhealthy"] == 1
        assert len(result["actions_taken"]) == 1
        assert result["actions_taken"][0]["applied"] == "alert_generated"

    def test_unhealthy_agent_pause(self, mock_db, mock_project_id):
        """When action is 'pause', unhealthy agents are suspended."""
        tool = _import_tool("enforce_team_health")
        mock_db.get_team_composition.return_value = {
            "id": 1,
            "name": "Team Alpha",
            "members": [
                {
                    "id": "A1", "display_name": "Agent 1",
                    "performance_score": 10.0, "status": "active",
                },
            ],
        }
        mock_db.compute_agent_performance.return_value = {
            "total_completed": 2,
            "total_failed": 8,
        }

        with patch("a_sdlc.server._load_governance_health_config") as mock_config:
            mock_config.return_value = {
                "quality_threshold": 40,
                "error_rate_threshold_pct": 30,
                "stalled_timeout_min": 30,
                "action": "pause",
            }
            result = tool(1)

        assert result["actions_taken"][0]["applied"] == "suspended"
        mock_db.suspend_agent.assert_called_once_with("A1")

    def test_no_project(self, mock_db, mock_no_project):
        tool = _import_tool("enforce_team_health")
        result = tool(1)
        assert result["status"] == "no_project"

    def test_team_not_found(self, mock_db, mock_project_id):
        tool = _import_tool("enforce_team_health")
        mock_db.get_team_composition.side_effect = ValueError("Team not found: 999")

        with patch("a_sdlc.server._load_governance_health_config") as mock_config:
            mock_config.return_value = {"quality_threshold": 40, "error_rate_threshold_pct": 30, "action": "alert"}
            result = tool(999)

        assert result["status"] == "error"
        assert "Team not found" in result["message"]


# =============================================================================
# 7. Health Config from YAML Tests (REM-013)
# =============================================================================


class TestHealthConfigFromYAML:
    """Test that health thresholds come from config, not hardcoded."""

    def test_load_governance_health_defaults(self):
        """When no config file, returns sensible defaults."""

        # Call directly
        from a_sdlc.server import _load_governance_health_config

        with patch("a_sdlc.core.config_loader._load_yaml", return_value={}):
            result = _load_governance_health_config()

        assert result["quality_threshold"] == 40
        assert result["error_rate_threshold_pct"] == 30
        assert result["stalled_timeout_min"] == 30
        assert result["action"] == "alert"

    def test_load_governance_health_custom(self):
        """Config values override defaults."""
        from a_sdlc.server import _load_governance_health_config

        config = {
            "governance": {
                "health": {
                    "quality_threshold": 60,
                    "error_rate_threshold_pct": 20,
                    "action": "pause",
                }
            }
        }
        with patch("a_sdlc.core.config_loader._load_yaml", return_value=config):
            result = _load_governance_health_config()

        assert result["quality_threshold"] == 60
        assert result["error_rate_threshold_pct"] == 20
        assert result["action"] == "pause"
        # Default preserved for missing key
        assert result["stalled_timeout_min"] == 30


# =============================================================================
# 8. Routing Config Tests (REM-007)
# =============================================================================


class TestRoutingConfig:
    """Test routing config loading."""

    def test_load_routing_config_with_component_map(self):
        from a_sdlc.server import _load_routing_config

        config = {
            "routing": {
                "component_map": {
                    "backend": ["backend_engineer"],
                    "frontend": ["frontend_engineer"],
                }
            }
        }
        with patch("a_sdlc.core.config_loader._load_yaml", return_value=config):
            result = _load_routing_config()

        assert "component_map" in result
        assert "backend" in result["component_map"]

    def test_load_routing_config_empty(self):
        from a_sdlc.server import _load_routing_config

        with patch("a_sdlc.core.config_loader._load_yaml", return_value={}):
            result = _load_routing_config()

        assert result == {}


# =============================================================================
# 9. Backward Compatibility Tests
# =============================================================================


class TestBackwardCompatibility:
    """Test that everything works without governance/routing config."""

    def test_get_available_work_no_component_map(self, temp_db):
        """Original behavior preserved when no component_map."""
        tasks = temp_db.get_available_work("test-project", "TEST-A001")
        assert len(tasks) == 3
        # All tier 2 (no component map = priority-only)
        assert all(t["routing_tier"] == 2 for t in tasks)

    def test_create_team_backward_compatible(self, temp_db):
        """create_agent_team still works without sprint_id."""
        team = temp_db.create_agent_team("Legacy Team", "test-project")
        assert team["sprint_id"] is None

    def test_list_teams_backward_compatible(self, temp_db):
        """list_agent_teams still works without sprint_id filter."""
        temp_db.create_agent_team("Team A", "test-project")
        teams = temp_db.list_agent_teams("test-project")
        assert len(teams) == 1
