"""
Core storage and database functionality for a-sdlc.

This module provides the foundational storage layer:
- Database: SQLite metadata and file path references
- ContentManager: Markdown content file operations
"""

from a_sdlc.core.database import Database, get_data_dir, get_db, get_db_path
from a_sdlc.core.content import ContentManager, get_content_manager

__all__ = [
    "Database",
    "ContentManager",
    "get_data_dir",
    "get_db_path",
    "get_db",
    "get_content_manager",
]
