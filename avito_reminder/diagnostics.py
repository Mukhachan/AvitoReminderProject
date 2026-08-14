from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
BROWSER_SNAPSHOT_LIMIT = 50
AVITO_DIAGNOSTIC_BUNDLE_LIMIT = 20
BROWSER_STORAGE_STATE_LIMIT = 50
BROWSER_STORAGE_TEMP_MAX_AGE_SECONDS = 24 * 60 * 60

_BROWSER_SNAPSHOT_NAME = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json"
)
_AVITO_DIAGNOSTIC_NAME = re.compile(
    r"(?P<stem>avito-(?:[0-9]{3}|unknown)-[0-9]{8}-[0-9]{6}-[0-9]{6})"
    r"\.(?:html|json|png)"
)
_BROWSER_STORAGE_STATE_NAME = re.compile(
    r"(?:direct|[0-9a-f]{16})-[0-9a-f]{12}\.json"
)
_BROWSER_STORAGE_TEMP_NAME = re.compile(
    r"(?:direct|[0-9a-f]{16})-[0-9a-f]{12}\.tmp"
)


def ensure_private_directory(path: Path) -> None:
    """Create a diagnostics directory and restrict it when the OS supports modes."""
    path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    if path.is_symlink():
        logger.debug("Refusing to chmod a symlinked private directory: %s", path)
        return
    _chmod_best_effort(path, PRIVATE_DIRECTORY_MODE)


def harden_file_permissions(path: Path) -> None:
    """Restrict a diagnostics file without making collection fail on unsupported FSes."""
    if path.is_symlink():
        logger.debug("Refusing to chmod a symlinked private file: %s", path)
        return
    _chmod_best_effort(path, PRIVATE_FILE_MODE)


def write_private_text(path: Path, text: str) -> None:
    """Atomically write UTF-8 text through a private temporary file."""
    ensure_private_directory(path.parent)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="") as handle:
            file_descriptor = -1
            handle.write(text)
        harden_file_permissions(temporary)
        temporary.replace(path)
        harden_file_permissions(path)
    except BaseException:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        with suppress(OSError):
            temporary.unlink()
        raise


def write_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    write_private_text(
        path,
        json.dumps(dict(payload), ensure_ascii=False, indent=2),
    )


def prune_browser_session_snapshots(
    directory: Path,
    *,
    limit: int = BROWSER_SNAPSHOT_LIMIT,
) -> list[Path]:
    """Remove only old UUID-named snapshot JSON files created by this project."""
    candidates = _owned_files(directory, _BROWSER_SNAPSHOT_NAME)
    for path in candidates:
        harden_file_permissions(path)
    return _prune_oldest_files(candidates, limit=limit)


def prune_avito_diagnostic_bundles(
    directory: Path,
    *,
    limit: int = AVITO_DIAGNOSTIC_BUNDLE_LIMIT,
) -> list[Path]:
    """Retain the newest Avito bundles and leave unrelated diagnostics untouched."""
    if limit < 0:
        raise ValueError("diagnostic retention limit cannot be negative")

    bundles: dict[str, list[Path]] = {}
    entries = _safe_directory_entries(directory)
    for entry in entries:
        match = _AVITO_DIAGNOSTIC_NAME.fullmatch(entry.name)
        if match is None or not _is_file_or_symlink(entry):
            continue
        harden_file_permissions(entry)
        bundles.setdefault(match.group("stem"), []).append(entry)

    ranked: list[tuple[int, str, list[Path]]] = []
    for stem, files in bundles.items():
        modified_times = [_mtime_ns(path) for path in files]
        known_times = [value for value in modified_times if value is not None]
        if not known_times:
            continue
        ranked.append((max(known_times), stem, files))
    ranked.sort(reverse=True)

    removed: list[Path] = []
    for _, _, files in ranked[limit:]:
        for path in files:
            if _unlink_best_effort(path):
                removed.append(path)
    return removed


def maintain_browser_storage_directory(
    directory: Path,
    *,
    preserve: tuple[Path, ...] = (),
    state_limit: int = BROWSER_STORAGE_STATE_LIMIT,
    stale_temp_age_seconds: int = BROWSER_STORAGE_TEMP_MAX_AGE_SECONDS,
    now_ns: int | None = None,
) -> list[Path]:
    """Harden and bound route+identity storage without touching unrelated files."""
    if state_limit < 0:
        raise ValueError("browser storage retention limit cannot be negative")
    if stale_temp_age_seconds < 0:
        raise ValueError("browser storage temporary age cannot be negative")
    ensure_private_directory(directory)
    entries = _safe_directory_entries(directory)
    if not entries:
        return []

    states = [
        path
        for path in entries
        if _BROWSER_STORAGE_STATE_NAME.fullmatch(path.name)
        and _is_file_or_symlink(path)
    ]
    temporaries = [
        path
        for path in entries
        if _BROWSER_STORAGE_TEMP_NAME.fullmatch(path.name)
        and _is_file_or_symlink(path)
    ]
    for path in (*states, *temporaries):
        harden_file_permissions(path)

    preserved_names = {
        path.name
        for path in preserve
        if path.parent == directory
        and _BROWSER_STORAGE_STATE_NAME.fullmatch(path.name)
        and path.exists()
    }
    preserved = [path for path in states if path.name in preserved_names]
    unprotected = [path for path in states if path.name not in preserved_names]
    state_capacity = max(0, state_limit - len(preserved))
    removed = _prune_oldest_files(unprotected, limit=state_capacity)

    current_ns = time.time_ns() if now_ns is None else now_ns
    stale_before = current_ns - stale_temp_age_seconds * 1_000_000_000
    for path in temporaries:
        modified_at = _mtime_ns(path)
        if (
            modified_at is not None
            and modified_at <= stale_before
            and _unlink_best_effort(path)
        ):
            removed.append(path)
    return removed


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError as exc:
        logger.debug("Could not restrict diagnostics path %s: %s", path, exc)


def _owned_files(directory: Path, name_pattern: re.Pattern[str]) -> list[Path]:
    entries = _safe_directory_entries(directory)
    return [
        entry
        for entry in entries
        if name_pattern.fullmatch(entry.name) and _is_file_or_symlink(entry)
    ]


def _safe_directory_entries(directory: Path) -> list[Path]:
    try:
        if directory.is_symlink() or not directory.is_dir():
            return []
        return list(directory.iterdir())
    except OSError:
        return []


def _is_file_or_symlink(path: Path) -> bool:
    try:
        return path.is_file() or path.is_symlink()
    except OSError:
        return False


def _mtime_ns(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


def _prune_oldest_files(files: list[Path], *, limit: int) -> list[Path]:
    if limit < 0:
        raise ValueError("diagnostic retention limit cannot be negative")
    ranked = [
        (modified_at, path.name, path)
        for path in files
        if (modified_at := _mtime_ns(path)) is not None
    ]
    ranked.sort(reverse=True)
    removed: list[Path] = []
    for _, _, path in ranked[limit:]:
        if _unlink_best_effort(path):
            removed.append(path)
    return removed


def _unlink_best_effort(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.debug("Could not remove expired diagnostics file %s: %s", path, exc)
        return False
