"""Compatibility exports for the upgraded SQLite storage."""

from avito_reminder.database import Database

DataBase = Database

__all__ = ["DataBase", "Database"]
