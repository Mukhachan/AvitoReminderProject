from avito_reminder.browser_identity import (
    load_browser_identity,
    resolve_http_impersonate,
    rotate_browser_identity,
    stealth_init_script,
)


def test_browser_identity_is_persistent_and_rotates_as_one_bundle(tmp_path) -> None:
    profile = tmp_path / "profile"
    kwargs = {
        "profile_path": profile,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        "impersonate": "chrome",
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
    }

    first = load_browser_identity(**kwargs)
    restored = load_browser_identity(**kwargs)
    rotated = rotate_browser_identity(profile_path=profile, current=first)
    restored_after_rotation = load_browser_identity(**kwargs)

    assert restored == first
    assert rotated.identity_id != first.identity_id
    assert (rotated.viewport_width, rotated.viewport_height) != (
        first.viewport_width,
        first.viewport_height,
    )
    assert restored_after_rotation == rotated
    assert rotated.http_headers["user-agent"] == rotated.user_agent
    assert rotated.http_headers["sec-ch-ua-platform"] == '"Windows"'
    assert '"136"' in rotated.http_headers["sec-ch-ua"]


def test_stealth_script_uses_the_saved_identity(tmp_path) -> None:
    identity = load_browser_identity(
        profile_path=tmp_path / "profile",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
        ),
        impersonate="chrome",
        locale="ru-RU",
        timezone_id="Europe/Moscow",
    )

    script = stealth_init_script(identity)

    assert "Navigator.prototype, 'webdriver'" in script
    assert '"platform": "Win32"' in script
    assert "Navigator.prototype, 'userAgentData'" in script
    assert '"ru-RU"' in script


def test_generic_chrome_impersonation_is_pinned_to_user_agent_version() -> None:
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    )

    assert resolve_http_impersonate(user_agent, "chrome") == "chrome136"
