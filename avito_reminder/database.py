from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .models import AvitoItem, Search


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def as_iso(value: datetime) -> str:
    return value.isoformat()


class Database:
    def __init__(
        self,
        path: Path,
        *,
        schedule_spread_seconds: int = 0,
        minimum_interval_seconds: int = 0,
    ):
        self.path = path
        self.schedule_spread_seconds = max(0, schedule_spread_seconds)
        self.minimum_interval_seconds = max(0, minimum_interval_seconds)

    def _spread_delay(self, search_id: int) -> int:
        if self.schedule_spread_seconds <= 0:
            return 0
        return (search_id * 97) % (self.schedule_spread_seconds + 1)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS searches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    city TEXT NOT NULL,
                    price_min INTEGER,
                    price_max INTEGER,
                    interval_seconds INTEGER NOT NULL DEFAULT 900,
                    url TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    initialized INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    next_check_at TEXT NOT NULL,
                    last_error TEXT,
                    failure_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_searches_due
                    ON searches(active, next_check_at);
                CREATE INDEX IF NOT EXISTS idx_searches_chat
                    ON searches(chat_id, id);

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

                CREATE INDEX IF NOT EXISTS idx_seen_pending
                    ON seen_items(search_id, notified, first_seen_at);

                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS notification_retries (
                    search_id INTEGER PRIMARY KEY,
                    retry_at TEXT NOT NULL,
                    FOREIGN KEY (search_id) REFERENCES searches(id) ON DELETE CASCADE
                );
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(searches)").fetchall()
            }
            if "interval_seconds" not in columns:
                connection.execute("ALTER TABLE searches ADD COLUMN interval_seconds INTEGER")
            connection.execute(
                "UPDATE searches SET interval_seconds = 900 WHERE interval_seconds IS NULL"
            )
            if self.minimum_interval_seconds:
                connection.execute(
                    "UPDATE searches SET interval_seconds = ? WHERE interval_seconds < ?",
                    (self.minimum_interval_seconds, self.minimum_interval_seconds),
                )

    @staticmethod
    def _search(row: sqlite3.Row | None) -> Search | None:
        if row is None:
            return None
        return Search(
            id=row["id"],
            chat_id=row["chat_id"],
            user_id=row["user_id"],
            query=row["query"],
            city=row["city"],
            price_min=row["price_min"],
            price_max=row["price_max"],
            interval_seconds=row["interval_seconds"],
            url=row["url"],
            active=bool(row["active"]),
            initialized=bool(row["initialized"]),
            created_at=row["created_at"],
            last_checked_at=row["last_checked_at"],
            next_check_at=row["next_check_at"],
            last_error=row["last_error"],
            failure_count=row["failure_count"],
        )

    async def add_search(
        self,
        *,
        chat_id: int,
        user_id: int,
        query: str,
        city: str,
        price_min: int | None,
        price_max: int | None,
        url: str,
        interval_seconds: int = 900,
    ) -> Search:
        return await asyncio.to_thread(
            self._add_search,
            chat_id,
            user_id,
            query,
            city,
            price_min,
            price_max,
            url,
            interval_seconds,
        )

    def _add_search(
        self,
        chat_id: int,
        user_id: int,
        query: str,
        city: str,
        price_min: int | None,
        price_max: int | None,
        url: str,
        interval_seconds: int,
    ) -> Search:
        interval_seconds = max(interval_seconds, self.minimum_interval_seconds)
        now_value = utc_now()
        now = as_iso(now_value)
        with self._connect() as connection:
            not_before = self._avito_not_before_from_connection(connection)
            next_check = max(now_value, not_before or now_value)
            cursor = connection.execute(
                """
                INSERT INTO searches (
                    chat_id, user_id, query, city, price_min, price_max, interval_seconds, url,
                    created_at, next_check_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    user_id,
                    query,
                    city,
                    price_min,
                    price_max,
                    interval_seconds,
                    url,
                    now,
                    as_iso(next_check),
                ),
            )
            row = connection.execute(
                "SELECT * FROM searches WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            if row is not None:
                next_check = max(
                    utc_now(),
                    not_before or utc_now(),
                ) + timedelta(seconds=self._spread_delay(row["id"]))
                connection.execute(
                    "UPDATE searches SET next_check_at = ? WHERE id = ?",
                    (as_iso(next_check), row["id"]),
                )
                row = connection.execute(
                    "SELECT * FROM searches WHERE id = ?", (row["id"],)
                ).fetchone()
        search = self._search(row)
        assert search is not None
        return search

    async def get_search(self, search_id: int, chat_id: int | None = None) -> Search | None:
        return await asyncio.to_thread(self._get_search, search_id, chat_id)

    def _get_search(self, search_id: int, chat_id: int | None) -> Search | None:
        sql = "SELECT * FROM searches WHERE id = ?"
        params: tuple[int, ...] = (search_id,)
        if chat_id is not None:
            sql += " AND chat_id = ?"
            params = (search_id, chat_id)
        with self._connect() as connection:
            return self._search(connection.execute(sql, params).fetchone())

    async def list_searches(self, chat_id: int) -> list[Search]:
        return await asyncio.to_thread(self._list_searches, chat_id)

    def _list_searches(self, chat_id: int) -> list[Search]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM searches WHERE chat_id = ? ORDER BY id", (chat_id,)
            ).fetchall()
        return [search for row in rows if (search := self._search(row)) is not None]

    async def due_searches(self, limit: int = 50) -> list[Search]:
        return await asyncio.to_thread(self._due_searches, limit)

    def _due_searches(self, limit: int) -> list[Search]:
        with self._connect() as connection:
            now = utc_now()
            not_before = self._avito_not_before_from_connection(connection)
            if not_before is not None and not_before > now:
                return []
            rows = connection.execute(
                """
                SELECT * FROM searches
                WHERE active = 1 AND next_check_at <= ?
                ORDER BY next_check_at
                LIMIT ?
                """,
                (as_iso(now), limit),
            ).fetchall()
        return [search for row in rows if (search := self._search(row)) is not None]

    async def set_active(self, search_id: int, chat_id: int, active: bool) -> bool:
        return await asyncio.to_thread(self._set_active, search_id, chat_id, active)

    def _set_active(self, search_id: int, chat_id: int, active: bool) -> bool:
        next_check = utc_now()
        with self._connect() as connection:
            if active:
                not_before = self._avito_not_before_from_connection(connection)
                next_check = max(next_check, not_before or next_check)
                next_check += timedelta(seconds=self._spread_delay(search_id))
            cursor = connection.execute(
                "UPDATE searches SET active = ?, next_check_at = ? WHERE id = ? AND chat_id = ?",
                (int(active), as_iso(next_check), search_id, chat_id),
            )
            return cursor.rowcount > 0

    async def postpone_active_searches(self, delay_seconds: int) -> int:
        return await asyncio.to_thread(self._postpone_active_searches, delay_seconds)

    def _postpone_active_searches(self, delay_seconds: int) -> int:
        resume_at = utc_now() + timedelta(seconds=delay_seconds)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_state (key, value) VALUES ('avito_not_before', ?)
                ON CONFLICT(key) DO UPDATE SET value = CASE
                    WHEN runtime_state.value > excluded.value
                    THEN runtime_state.value ELSE excluded.value
                END
                """,
                (as_iso(resume_at),),
            )
            not_before = self._avito_not_before_from_connection(connection)
            assert not_before is not None
            rows = connection.execute(
                "SELECT id, next_check_at FROM searches WHERE active = 1"
            ).fetchall()
            updated = 0
            for row in rows:
                target = not_before + timedelta(seconds=self._spread_delay(row["id"]))
                current = datetime.fromisoformat(row["next_check_at"])
                if current >= target:
                    continue
                cursor = connection.execute(
                    "UPDATE searches SET next_check_at = ? WHERE id = ?",
                    (as_iso(target), row["id"]),
                )
                updated += cursor.rowcount
            return updated

    @staticmethod
    def _avito_not_before_from_connection(
        connection: sqlite3.Connection,
    ) -> datetime | None:
        row = connection.execute(
            "SELECT value FROM runtime_state WHERE key = 'avito_not_before'"
        ).fetchone()
        return datetime.fromisoformat(row["value"]) if row is not None else None

    async def avito_retry_after_seconds(self) -> int:
        return await asyncio.to_thread(self._avito_retry_after_seconds)

    def _avito_retry_after_seconds(self) -> int:
        with self._connect() as connection:
            not_before = self._avito_not_before_from_connection(connection)
        if not_before is None:
            return 0
        remaining = (not_before - utc_now()).total_seconds()
        return max(0, int(remaining + 0.999))

    async def delete_search(self, search_id: int, chat_id: int) -> bool:
        return await asyncio.to_thread(self._delete_search, search_id, chat_id)

    def _delete_search(self, search_id: int, chat_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM searches WHERE id = ? AND chat_id = ?", (search_id, chat_id)
            )
            return cursor.rowcount > 0

    async def record_items(
        self, search_id: int, items: Iterable[AvitoItem], *, notify: bool
    ) -> int:
        return await asyncio.to_thread(self._record_items, search_id, list(items), notify)

    def _record_items(self, search_id: int, items: list[AvitoItem], notify: bool) -> int:
        inserted = 0
        now = as_iso(utc_now())
        with self._connect() as connection:
            for item in items:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO seen_items (
                        search_id, item_id, title, price, url, location, image_url,
                        first_seen_at, notified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        search_id,
                        item.id,
                        item.title,
                        item.price,
                        item.url,
                        item.location,
                        item.image_url,
                        now,
                        0 if notify else 1,
                    ),
                )
                inserted += cursor.rowcount
                if cursor.rowcount == 0 and item.image_url:
                    # A pending item may have been recorded from a shell/older
                    # parser before its lazy image became available.  Enrich only
                    # unsent notifications without treating it as a new listing.
                    connection.execute(
                        """
                        UPDATE seen_items
                        SET image_url = COALESCE(image_url, ?)
                        WHERE search_id = ? AND item_id = ? AND notified = 0
                        """,
                        (item.image_url, search_id, item.id),
                    )
        return inserted

    async def pending_items(self, search_id: int, limit: int) -> list[AvitoItem]:
        return await asyncio.to_thread(self._pending_items, search_id, limit)

    def _pending_items(self, search_id: int, limit: int) -> list[AvitoItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT item_id, title, price, url, location, image_url
                FROM seen_items
                WHERE search_id = ? AND notified = 0
                ORDER BY first_seen_at, item_id
                LIMIT ?
                """,
                (search_id, limit),
            ).fetchall()
        return [
            AvitoItem(
                id=row["item_id"],
                title=row["title"],
                price=row["price"],
                url=row["url"],
                location=row["location"],
                image_url=row["image_url"],
            )
            for row in rows
        ]

    async def searches_with_pending_items(self, limit: int = 50) -> list[Search]:
        return await asyncio.to_thread(self._searches_with_pending_items, limit)

    def _searches_with_pending_items(self, limit: int) -> list[Search]:
        with self._connect() as connection:
            now = as_iso(utc_now())
            rows = connection.execute(
                """
                SELECT searches.*
                FROM searches
                WHERE searches.active = 1
                  AND NOT EXISTS (
                    SELECT 1 FROM notification_retries
                    WHERE notification_retries.search_id = searches.id
                      AND notification_retries.retry_at > ?
                  )
                  AND EXISTS (
                    SELECT 1 FROM seen_items
                    WHERE seen_items.search_id = searches.id
                      AND seen_items.notified = 0
                )
                ORDER BY searches.id
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
        return [search for row in rows if (search := self._search(row)) is not None]

    async def postpone_pending_delivery(self, search_id: int, delay_seconds: int) -> None:
        await asyncio.to_thread(self._postpone_pending_delivery, search_id, delay_seconds)

    def _postpone_pending_delivery(self, search_id: int, delay_seconds: int) -> None:
        retry_at = utc_now() + timedelta(seconds=delay_seconds)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notification_retries (search_id, retry_at) VALUES (?, ?)
                ON CONFLICT(search_id) DO UPDATE SET retry_at = excluded.retry_at
                """,
                (search_id, as_iso(retry_at)),
            )

    async def clear_pending_delivery_retry(self, search_id: int) -> None:
        await asyncio.to_thread(self._clear_pending_delivery_retry, search_id)

    def _clear_pending_delivery_retry(self, search_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM notification_retries WHERE search_id = ?", (search_id,)
            )

    async def mark_notified(self, search_id: int, item_id: str) -> None:
        await asyncio.to_thread(self._mark_notified, search_id, item_id)

    def _mark_notified(self, search_id: int, item_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE seen_items SET notified = 1 WHERE search_id = ? AND item_id = ?",
                (search_id, item_id),
            )

    async def mark_success(self, search_id: int, interval_seconds: int) -> None:
        await asyncio.to_thread(self._mark_success, search_id, interval_seconds)

    def _mark_success(self, search_id: int, interval_seconds: int) -> None:
        now = utc_now()
        spread_seconds = self._spread_delay(search_id)
        next_check = now + timedelta(seconds=interval_seconds + spread_seconds)
        with self._connect() as connection:
            # Serialize the runtime cooldown read with the row update.  A global
            # postpone that wins the lock first is preserved; one that runs after
            # this transaction updates the row afterwards.  Per-search failure
            # backoff is intentionally reset by a successful manual/automatic run.
            connection.execute("BEGIN IMMEDIATE")
            not_before = self._avito_not_before_from_connection(connection)
            if not_before is not None and not_before > now:
                next_check = max(
                    next_check,
                    not_before + timedelta(seconds=spread_seconds),
                )
            connection.execute(
                """
                UPDATE searches
                SET initialized = 1, last_checked_at = ?,
                    next_check_at = ?,
                    last_error = NULL, failure_count = 0
                WHERE id = ?
                """,
                (as_iso(now), as_iso(next_check), search_id),
            )

    async def mark_failure(self, search_id: int, message: str, retry_seconds: int) -> None:
        await asyncio.to_thread(self._mark_failure, search_id, message, retry_seconds)

    def _mark_failure(self, search_id: int, message: str, retry_seconds: int) -> None:
        now = utc_now()
        next_check = now + timedelta(
            seconds=retry_seconds + self._spread_delay(search_id)
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE searches
                SET last_checked_at = ?,
                    next_check_at = CASE
                        WHEN next_check_at > ? THEN next_check_at ELSE ?
                    END,
                    last_error = ?,
                    failure_count = failure_count + 1
                WHERE id = ?
                """,
                (
                    as_iso(now),
                    as_iso(next_check),
                    as_iso(next_check),
                    message[:500],
                    search_id,
                ),
            )
