import pytest

from avito_reminder.runtime_lock import AlreadyRunningError, RuntimeLock


def test_runtime_lock_prevents_second_process_owner(tmp_path) -> None:
    database_path = tmp_path / "monitor.db"
    first = RuntimeLock(database_path)
    second = RuntimeLock(database_path)

    first.acquire()
    try:
        with pytest.raises(AlreadyRunningError):
            second.acquire()
    finally:
        first.release()

    second.acquire()
    second.release()


def test_runtime_lock_context_releases_after_exception(tmp_path) -> None:
    database_path = tmp_path / "monitor.db"

    with pytest.raises(RuntimeError, match="startup failed"), RuntimeLock(database_path):
        raise RuntimeError("startup failed")

    with RuntimeLock(database_path):
        pass
