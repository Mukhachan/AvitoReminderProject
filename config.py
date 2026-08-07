"""Compatibility import for the upgraded configuration module.

Secrets are loaded from environment variables. See .env.example.
"""

from avito_reminder.config import Settings, load_settings

__all__ = ["Settings", "load_settings"]
