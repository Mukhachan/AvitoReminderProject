from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType


class AlreadyRunningError(RuntimeError):
    """Another process already owns the monitor for this database."""


class RuntimeLock:
    """Small cross-platform advisory lock held for the process lifetime."""

    def __init__(self, database_path: Path):
        self.path = database_path.with_suffix(database_path.suffix + ".lock")
        self._file = None

    def acquire(self) -> None:
        if self._file is not None:
            raise RuntimeError("RuntimeLock уже захвачен этим экземпляром")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise AlreadyRunningError(
                "другой экземпляр Avito Reminder уже работает с этой базой"
            ) from exc
        self._file = handle

    def release(self) -> None:
        handle = self._file
        self._file = None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def __enter__(self) -> RuntimeLock:
        self.acquire()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()
