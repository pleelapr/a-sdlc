"""Quality system helper functions.

Extracted from server/__init__.py to reduce module size.
Contains AC verification constants and safe config loading.
"""

from __future__ import annotations

from typing import Any

# Valid evidence types for AC verification
VALID_EVIDENCE_TYPES = {"test", "manual", "demo"}


def load_quality_config_safe() -> Any:
    """Attempt to load quality config; return None if unavailable.

    The quality config module (SDLC-T00171) may not be present yet.
    When absent, behavioral strictness is disabled (backward compatible).
    """
    try:
        from a_sdlc.core.quality_config import load_quality_config

        return load_quality_config()
    except (ImportError, ModuleNotFoundError):
        return None
    except Exception:
        return None
