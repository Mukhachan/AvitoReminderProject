from pathlib import Path


def test_systemd_service_keeps_retrying_after_a_long_startup_outage() -> None:
    script = (Path(__file__).parents[1] / "service.sh").read_text(encoding="utf-8")

    assert 'echo "Restart=on-failure"' in script
    assert 'echo "RestartSec=60"' in script
    assert 'echo "StartLimitIntervalSec=0"' in script
    assert "StartLimitBurst" not in script
