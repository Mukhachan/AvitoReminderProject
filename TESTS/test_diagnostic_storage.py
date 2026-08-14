import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from avito_reminder.avito import AvitoClient
from avito_reminder.browser_sessions import collect_browser_snapshot, save_browser_snapshot
from avito_reminder.diagnostics import (
    AVITO_DIAGNOSTIC_BUNDLE_LIMIT,
    BROWSER_SNAPSHOT_LIMIT,
    BROWSER_STORAGE_STATE_LIMIT,
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    maintain_browser_storage_directory,
    prune_avito_diagnostic_bundles,
    prune_browser_session_snapshots,
)

from .helpers import settings


class DiagnosticPageStub:
    url = "https://www.avito.ru/moskva?q=test"

    async def content(self) -> str:
        return "<html><body>diagnostic</body></html>"

    async def screenshot(self, *, path: str, **_kwargs) -> None:
        Path(path).write_bytes(b"test-png")


class ContentOnlyPageStub:
    url = "https://www.avito.ru/moskva?q=test"

    async def content(self) -> str:
        return "<html><body>diagnostic</body></html>"


class StorageContextStub:
    async def storage_state(self, *, path: str, indexed_db: bool = False) -> None:
        Path(path).write_text(
            json.dumps({"cookies": [], "origins": [], "indexedDB": indexed_db}),
            encoding="utf-8",
        )


class SnapshotPageStub:
    def __init__(self) -> None:
        self.script = ""

    async def evaluate(self, script: str) -> dict[str, object]:
        self.script = script
        return {"userAgent": "Chromium test", "webdriver": True}


def test_snapshot_writer_applies_private_modes_best_effort(tmp_path, monkeypatch) -> None:
    chmod_calls: list[tuple[Path, int]] = []

    def record_chmod(path: Path, mode: int) -> None:
        chmod_calls.append((path, mode))

    monkeypatch.setattr(Path, "chmod", record_chmod)
    target = tmp_path / "browser-sessions" / f"{uuid4()}.json"

    save_browser_snapshot({"sessionId": target.stem}, target)

    assert json.loads(target.read_text(encoding="utf-8"))["sessionId"] == target.stem
    assert (target.parent, PRIVATE_DIRECTORY_MODE) in chmod_calls
    assert (target, PRIVATE_FILE_MODE) in chmod_calls


def test_browser_snapshot_records_user_agent_and_webdriver_signal() -> None:
    page = SnapshotPageStub()

    snapshot = asyncio.run(collect_browser_snapshot(page))  # type: ignore[arg-type]

    assert snapshot == {"userAgent": "Chromium test", "webdriver": True}
    assert "userAgent: navigator.userAgent" in page.script
    assert "webdriver: navigator.webdriver" in page.script


def test_snapshot_writer_ignores_unsupported_permission_changes(tmp_path, monkeypatch) -> None:
    def reject_chmod(_path: Path, _mode: int) -> None:
        raise OSError("chmod is unavailable")

    monkeypatch.setattr(Path, "chmod", reject_chmod)
    target = tmp_path / "browser-sessions" / f"{uuid4()}.json"

    save_browser_snapshot({"ok": True}, target)

    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True}


def test_snapshot_retention_removes_only_owned_uuid_json_files(tmp_path) -> None:
    directory = tmp_path / "browser-sessions"
    unrelated = directory / "operator-notes.json"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")
    owned: list[Path] = []
    for index in range(BROWSER_SNAPSHOT_LIMIT + 2):
        target = directory / f"{uuid4()}.json"
        save_browser_snapshot({"index": index}, target)
        owned.append(target)

    remaining = [path for path in owned if path.exists()]

    assert len(remaining) == BROWSER_SNAPSHOT_LIMIT
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_snapshot_pruner_leaves_uuid_named_directories_untouched(tmp_path) -> None:
    directory = tmp_path / "browser-sessions"
    snapshot_directory = directory / f"{uuid4()}.json"
    snapshot_directory.mkdir(parents=True)

    removed = prune_browser_session_snapshots(directory, limit=0)

    assert removed == []
    assert snapshot_directory.is_dir()


def test_avito_bundle_pruner_removes_whole_old_bundle_and_nothing_else(tmp_path) -> None:
    directory = tmp_path / "diagnostics"
    directory.mkdir()
    stems = [
        "avito-429-20260814-120000-000001",
        "avito-429-20260814-120001-000001",
        "avito-429-20260814-120002-000001",
    ]
    for index, stem in enumerate(stems, start=1):
        for suffix in ("html", "json", "png"):
            target = directory / f"{stem}.{suffix}"
            target.write_text(stem, encoding="utf-8")
            os.utime(target, ns=(index, index))
    unrelated = directory / "avito-429-manual-note.json"
    unrelated.write_text("keep", encoding="utf-8")

    removed = prune_avito_diagnostic_bundles(directory, limit=2)

    assert {path.name for path in removed} == {
        f"{stems[0]}.html",
        f"{stems[0]}.json",
        f"{stems[0]}.png",
    }
    assert all(
        not (directory / f"{stems[0]}.{suffix}").exists()
        for suffix in ("html", "json", "png")
    )
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_avito_diagnostic_collection_enforces_bundle_limit(tmp_path) -> None:
    client = AvitoClient(settings(tmp_path / "data" / "test.db"))
    page = DiagnosticPageStub()
    diagnostic_dir = tmp_path / "data" / "diagnostics"
    unrelated = diagnostic_dir / "README.txt"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("keep", encoding="utf-8")

    async def collect() -> None:
        for _ in range(AVITO_DIAGNOSTIC_BUNDLE_LIMIT + 2):
            assert await client._save_browser_diagnostic(page, 429) is not None

    asyncio.run(collect())

    assert len(list(diagnostic_dir.glob("avito-*.html"))) == AVITO_DIAGNOSTIC_BUNDLE_LIMIT
    assert len(list(diagnostic_dir.glob("avito-*.json"))) == AVITO_DIAGNOSTIC_BUNDLE_LIMIT
    assert len(list(diagnostic_dir.glob("avito-*.png"))) == AVITO_DIAGNOSTIC_BUNDLE_LIMIT
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_avito_diagnostic_hardens_directory_and_each_bundle_file(
    tmp_path,
    monkeypatch,
) -> None:
    client = AvitoClient(settings(tmp_path / "data" / "test.db"))
    client._ensure_browser_identity()
    chmod_calls: list[tuple[Path, int]] = []

    def record_chmod(path: Path, mode: int) -> None:
        chmod_calls.append((path, mode))

    monkeypatch.setattr(Path, "chmod", record_chmod)

    screenshot = asyncio.run(client._save_browser_diagnostic(DiagnosticPageStub(), 429))

    assert screenshot is not None
    diagnostic_dir = screenshot.parent
    assert (diagnostic_dir, PRIVATE_DIRECTORY_MODE) in chmod_calls
    for suffix in ("html", "json", "png"):
        assert (screenshot.with_suffix(f".{suffix}"), PRIVATE_FILE_MODE) in chmod_calls


def test_missing_screenshot_api_does_not_make_diagnostics_fail(tmp_path) -> None:
    client = AvitoClient(settings(tmp_path / "data" / "test.db"))

    result = asyncio.run(client._save_browser_diagnostic(ContentOnlyPageStub(), 200))

    assert result is None
    diagnostic_dir = tmp_path / "data" / "diagnostics"
    assert len(list(diagnostic_dir.glob("avito-*.html"))) == 1
    assert len(list(diagnostic_dir.glob("avito-*.json"))) == 1


def test_browser_storage_maintenance_bounds_states_and_removes_only_stale_own_temp(
    tmp_path,
) -> None:
    directory = tmp_path / "storage"
    directory.mkdir()
    now_ns = 2_000_000_000_000_000_000
    states: list[Path] = []
    for index in range(BROWSER_STORAGE_STATE_LIMIT + 2):
        identity_id = f"{index:012x}"
        target = directory / f"direct-{identity_id}.json"
        target.write_text("{}", encoding="utf-8")
        os.utime(target, ns=(now_ns - index * 1_000_000_000,) * 2)
        states.append(target)
    preserved = states[-1]
    stale_temp = directory / "direct-aaaaaaaaaaaa.tmp"
    fresh_temp = directory / "direct-bbbbbbbbbbbb.tmp"
    unrelated_temp = directory / "operator-notes.tmp"
    unrelated_json = directory / "direct-manual-backup.json"
    for path in (stale_temp, fresh_temp, unrelated_temp):
        path.write_text("keep", encoding="utf-8")
    unrelated_json.write_text("keep", encoding="utf-8")
    os.utime(stale_temp, ns=(now_ns - 100_000_000_000,) * 2)
    os.utime(fresh_temp, ns=(now_ns - 1_000_000_000,) * 2)

    maintain_browser_storage_directory(
        directory,
        preserve=(preserved,),
        stale_temp_age_seconds=10,
        now_ns=now_ns,
    )

    assert len([path for path in states if path.exists()]) == BROWSER_STORAGE_STATE_LIMIT
    assert preserved.exists()
    assert not stale_temp.exists()
    assert fresh_temp.exists()
    assert unrelated_temp.read_text(encoding="utf-8") == "keep"
    assert unrelated_json.read_text(encoding="utf-8") == "keep"


def test_browser_storage_save_hardens_directory_temporary_and_final_file(
    tmp_path,
    monkeypatch,
) -> None:
    client = AvitoClient(
        settings(
            tmp_path / "data" / "test.db",
            avito_new_user_per_session=False,
        )
    )
    client._ensure_browser_identity()
    client._browser_context = StorageContextStub()  # type: ignore[assignment]
    target = client._browser_storage_state_path()
    temporary = target.with_suffix(".tmp")
    chmod_calls: list[tuple[Path, int]] = []

    def record_chmod(path: Path, mode: int) -> None:
        chmod_calls.append((path, mode))

    monkeypatch.setattr(Path, "chmod", record_chmod)

    asyncio.run(client._save_browser_storage_state())

    assert target.is_file()
    assert not temporary.exists()
    assert (target.parent, PRIVATE_DIRECTORY_MODE) in chmod_calls
    assert (temporary, PRIVATE_FILE_MODE) in chmod_calls
    assert (target, PRIVATE_FILE_MODE) in chmod_calls
