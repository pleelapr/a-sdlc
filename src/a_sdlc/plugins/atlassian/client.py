"""
Atlassian Cloud REST API client.

Provides a unified HTTP client for Jira and Confluence REST APIs
with error handling, rate limiting, and retries.
"""

import time
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

from a_sdlc.plugins.atlassian.auth import APITokenAuth


class AtlassianAPIError(Exception):
    """Exception raised for Atlassian API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: dict | None = None,
    ) -> None:
        """Initialize API error.

        Args:
            message: Error message.
            status_code: HTTP status code if available.
            response_body: Parsed response body if available.
        """
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}

    def __str__(self) -> str:
        """Format error message with status code."""
        if self.status_code:
            return f"[{self.status_code}] {super().__str__()}"
        return super().__str__()


class RateLimitError(AtlassianAPIError):
    """Exception raised when rate limited by Atlassian API."""

    def __init__(self, retry_after: int = 60) -> None:
        """Initialize rate limit error.

        Args:
            retry_after: Seconds to wait before retrying.
        """
        super().__init__(f"Rate limited. Retry after {retry_after} seconds.", 429)
        self.retry_after = retry_after


class AtlassianClient:
    """HTTP client for Atlassian Cloud REST APIs.

    Handles authentication, error handling, rate limiting, and retries
    for both Jira and Confluence APIs.

    Configuration:
        - base_url: Atlassian site URL (e.g., https://company.atlassian.net)
        - auth: APITokenAuth instance for authentication
        - timeout: Request timeout in seconds (default: 30)
        - max_retries: Maximum retry attempts (default: 3)
    """

    DEFAULT_TIMEOUT = 30
    DEFAULT_MAX_RETRIES = 3
    RETRY_BACKOFF_FACTOR = 2

    def __init__(
        self,
        base_url: str,
        auth: APITokenAuth,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """Initialize Atlassian client.

        Args:
            base_url: Atlassian site URL (e.g., https://company.atlassian.net)
            auth: APITokenAuth instance for authentication.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retry attempts.

        Raises:
            ImportError: If httpx is not installed.
        """
        if httpx is None:
            raise ImportError(
                "httpx is required for Atlassian integration. "
                "Install with: pip install a-sdlc[atlassian]"
            )

        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.timeout = timeout
        self.max_retries = max_retries

        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                **auth.get_auth_header(),
            },
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "AtlassianClient":
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    def _handle_response(self, response: "httpx.Response") -> dict | list | None:
        """Handle API response and extract JSON.

        Args:
            response: HTTP response object.

        Returns:
            Parsed JSON response or None for empty responses.

        Raises:
            RateLimitError: If rate limited (429).
            AtlassianAPIError: For other API errors.
        """
        # Handle rate limiting
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 60))
            raise RateLimitError(retry_after)

        # Handle successful responses
        if response.status_code in (200, 201, 204):
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

        # Handle errors
        try:
            error_body = response.json()
            # Jira error format
            if "errorMessages" in error_body:
                message = "; ".join(error_body.get("errorMessages", []))
                if not message and "errors" in error_body:
                    message = str(error_body["errors"])
            # Confluence error format
            elif "message" in error_body:
                message = error_body["message"]
            else:
                message = str(error_body)
        except Exception:
            message = response.text or f"HTTP {response.status_code}"

        raise AtlassianAPIError(message, response.status_code)

    def _request_with_retry(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict | list | None:
        """Make request with retry logic.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE).
            path: API path (appended to base_url).
            **kwargs: Additional arguments for httpx request.

        Returns:
            Parsed JSON response or None.

        Raises:
            AtlassianAPIError: After all retries exhausted.
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                response = self._client.request(method, path, **kwargs)
                return self._handle_response(response)

            except RateLimitError as e:
                # Wait for rate limit to reset
                if attempt < self.max_retries - 1:
                    time.sleep(e.retry_after)
                else:
                    raise

            except httpx.TimeoutException as e:
                last_error = AtlassianAPIError(f"Request timed out: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.RETRY_BACKOFF_FACTOR ** attempt)

            except httpx.RequestError as e:
                last_error = AtlassianAPIError(f"Request failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.RETRY_BACKOFF_FACTOR ** attempt)

        if last_error:
            raise last_error
        raise AtlassianAPIError("Request failed after all retries")

    def get(self, path: str, params: dict | None = None) -> dict | list | None:
        """Make GET request.

        Args:
            path: API path.
            params: Query parameters.

        Returns:
            Parsed JSON response.
        """
        return self._request_with_retry("GET", path, params=params)

    def post(self, path: str, data: dict | None = None) -> dict | list | None:
        """Make POST request.

        Args:
            path: API path.
            data: Request body as dict.

        Returns:
            Parsed JSON response.
        """
        return self._request_with_retry("POST", path, json=data)

    def put(self, path: str, data: dict | None = None) -> dict | list | None:
        """Make PUT request.

        Args:
            path: API path.
            data: Request body as dict.

        Returns:
            Parsed JSON response.
        """
        return self._request_with_retry("PUT", path, json=data)

    def delete(self, path: str) -> dict | list | None:
        """Make DELETE request.

        Args:
            path: API path.

        Returns:
            Parsed JSON response (usually None for DELETE).
        """
        return self._request_with_retry("DELETE", path)
