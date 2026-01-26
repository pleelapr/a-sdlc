"""
Atlassian Cloud API authentication.

Implements API token authentication for Atlassian Cloud services.
Uses Basic Auth with email + API token as per Atlassian Cloud requirements.
"""

import base64
import os


class APITokenAuth:
    """Atlassian Cloud API token authentication.

    Atlassian Cloud REST APIs require Basic Authentication with:
    - Username: Your Atlassian account email
    - Password: API token (generated at https://id.atlassian.com/manage-profile/security/api-tokens)

    The credentials can be provided directly or via environment variables.
    """

    def __init__(
        self,
        email: str | None = None,
        api_token: str | None = None,
        email_env: str = "ATLASSIAN_EMAIL",
        token_env: str = "ATLASSIAN_API_TOKEN",
    ) -> None:
        """Initialize authentication.

        Args:
            email: Atlassian account email. If None, uses email_env.
            api_token: API token. If None, uses token_env.
            email_env: Environment variable name for email fallback.
            token_env: Environment variable name for token fallback.
        """
        self.email = email or os.environ.get(email_env, "")
        self.api_token = api_token or os.environ.get(token_env, "")

    @property
    def is_configured(self) -> bool:
        """Check if authentication is properly configured."""
        return bool(self.email and self.api_token)

    def get_auth_header(self) -> dict[str, str]:
        """Generate Authorization header for requests.

        Returns:
            Dict with Authorization header for HTTP requests.

        Raises:
            RuntimeError: If authentication is not configured.
        """
        if not self.is_configured:
            raise RuntimeError(
                "Atlassian authentication not configured. "
                "Set ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN environment variables, "
                "or run: a-sdlc plugins configure jira"
            )

        credentials = f"{self.email}:{self.api_token}"
        encoded = base64.b64encode(credentials.encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    def __repr__(self) -> str:
        """String representation (hides sensitive data)."""
        email_display = self.email if self.email else "<not set>"
        token_display = "****" if self.api_token else "<not set>"
        return f"APITokenAuth(email={email_display!r}, api_token={token_display!r})"
