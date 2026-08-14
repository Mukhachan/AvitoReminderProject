import asyncio

from avito_reminder import app
from TESTS.helpers import settings


def test_app_checks_telegram_before_starting_monitor_and_releases_lock(
    monkeypatch,
    tmp_path,
) -> None:
    events: list[str] = []
    cfg = settings(tmp_path / "app.db")

    class FakeRuntimeLock:
        def __init__(self, _path) -> None:
            pass

        def acquire(self) -> None:
            events.append("lock:acquire")

        def release(self) -> None:
            events.append("lock:release")

    class FakeDatabase:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def initialize(self) -> None:
            events.append("database")

    class FakeSession:
        async def close(self) -> None:
            events.append("telegram:close")

    class FakeBot:
        def __init__(self, *_args, **_kwargs) -> None:
            self.session = FakeSession()

        async def get_me(self) -> object:
            events.append("telegram:get_me")
            return object()

        async def set_my_commands(self, _commands) -> None:
            events.append("telegram:commands")

    class FakeDispatcher:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def include_router(self, _router) -> None:
            pass

        def resolve_used_update_types(self) -> list[str]:
            return []

        async def start_polling(self, *_args, **_kwargs) -> None:
            events.append("telegram:polling")
            await asyncio.sleep(0)

    class FakeClient:
        def __init__(self, _settings) -> None:
            pass

        async def close(self) -> None:
            events.append("avito:close")

    class FakeService:
        def __init__(self, **_kwargs) -> None:
            pass

        async def run(self) -> None:
            events.append("avito:monitor")

        def stop(self) -> None:
            events.append("avito:stop")

    monkeypatch.setattr(app, "load_settings", lambda: cfg)
    monkeypatch.setattr(app, "RuntimeLock", FakeRuntimeLock)
    monkeypatch.setattr(app, "Database", FakeDatabase)
    monkeypatch.setattr(app, "Bot", FakeBot)
    monkeypatch.setattr(app, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(app, "AvitoClient", FakeClient)
    monkeypatch.setattr(app, "MonitorService", FakeService)
    monkeypatch.setattr(app, "create_telegram_session", lambda _settings: FakeSession())

    asyncio.run(app.run())

    assert events.index("telegram:get_me") < events.index("avito:monitor")
    assert events.index("telegram:commands") < events.index("avito:monitor")
    assert events[-1] == "lock:release"


def test_app_releases_lock_when_telegram_startup_fails(monkeypatch, tmp_path) -> None:
    events: list[str] = []
    cfg = settings(tmp_path / "startup-failure.db")

    class FakeRuntimeLock:
        def __init__(self, _path) -> None:
            pass

        def acquire(self) -> None:
            events.append("lock:acquire")

        def release(self) -> None:
            events.append("lock:release")

    class FakeDatabase:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def initialize(self) -> None:
            pass

    class FakeSession:
        async def close(self) -> None:
            events.append("telegram:close")

    class FakeBot:
        def __init__(self, *_args, **_kwargs) -> None:
            self.session = FakeSession()

        async def get_me(self) -> object:
            events.append("telegram:get_me")
            raise RuntimeError("telegram unavailable")

    class FakeDispatcher:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def include_router(self, _router) -> None:
            pass

    class FakeClient:
        def __init__(self, _settings) -> None:
            pass

        async def close(self) -> None:
            events.append("avito:close")

    class FakeService:
        def __init__(self, **_kwargs) -> None:
            pass

        def stop(self) -> None:
            events.append("avito:stop")

    monkeypatch.setattr(app, "load_settings", lambda: cfg)
    monkeypatch.setattr(app, "RuntimeLock", FakeRuntimeLock)
    monkeypatch.setattr(app, "Database", FakeDatabase)
    monkeypatch.setattr(app, "Bot", FakeBot)
    monkeypatch.setattr(app, "Dispatcher", FakeDispatcher)
    monkeypatch.setattr(app, "AvitoClient", FakeClient)
    monkeypatch.setattr(app, "MonitorService", FakeService)
    monkeypatch.setattr(app, "create_telegram_session", lambda _settings: FakeSession())

    try:
        asyncio.run(app.run())
    except RuntimeError as exc:
        assert str(exc) == "telegram unavailable"
    else:
        raise AssertionError("Telegram startup failure was not propagated")

    assert "avito:monitor" not in events
    assert events[-1] == "lock:release"
