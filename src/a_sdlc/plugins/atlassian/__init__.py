"""
Atlassian Cloud integration utilities.

Provides a shared client and authentication for Jira and Confluence
REST API integrations.
"""

from a_sdlc.plugins.atlassian.auth import APITokenAuth
from a_sdlc.plugins.atlassian.client import AtlassianClient

__all__ = ["AtlassianClient", "APITokenAuth"]
