-- Актуальная схема Avito Reminder 2.0 (SQLite).
-- Обычно создаётся автоматически командой: python -m avito_reminder.cli

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    query TEXT NOT NULL,
    city TEXT NOT NULL,
    price_min INTEGER,
    price_max INTEGER,
    url TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    initialized INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_checked_at TEXT,
    next_check_at TEXT NOT NULL,
    last_error TEXT,
    failure_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS seen_items (
    search_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    title TEXT NOT NULL,
    price INTEGER,
    url TEXT NOT NULL,
    location TEXT,
    image_url TEXT,
    first_seen_at TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (search_id, item_id),
    FOREIGN KEY (search_id) REFERENCES searches(id) ON DELETE CASCADE
);
