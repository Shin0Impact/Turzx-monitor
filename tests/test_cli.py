from __future__ import annotations

import logging

import pytest

from turingscreen import cli, config
from turingscreen.lcd import SerialLcd
from turingscreen.simulator import SimulatedLcd


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Keep logs, previews and settings out of the project folder, and undo the logging set-up."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "load", lambda *a, **k: __import__("copy").deepcopy(config.DEFAULTS))
    root = logging.getLogger()
    handlers = list(root.handlers)
    yield tmp_path
    for handler in list(root.handlers):
        if handler not in handlers:
            handler.close()
            root.removeHandler(handler)


def test_defaults():
    args = cli.parse_args([])
    assert args.command == "run"
    assert not args.background and not args.simulate


def test_flags():
    args = cli.parse_args(["--background", "--simulate", "--seconds", "3", "--no-ui"])
    assert args.background and args.simulate and args.no_ui and args.seconds == 3


def test_unknown_command_is_rejected():
    with pytest.raises(SystemExit):
        cli.parse_args(["explode"])


def test_install_and_uninstall_are_dispatched(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "install", lambda: calls.append("install") or 0)
    monkeypatch.setattr(cli, "uninstall", lambda: calls.append("uninstall") or 0)
    assert cli.main(["install"]) == 0
    assert cli.main(["uninstall"]) == 0
    assert calls == ["install", "uninstall"]


def test_lcd_choice():
    cfg = config.DEFAULTS
    assert isinstance(cli.build_lcd(cfg, simulate=True), SimulatedLcd)
    assert isinstance(cli.build_lcd(cfg, simulate=False), SerialLcd)


def test_simulated_run_draws_a_preview_and_stops_by_itself(isolated):
    assert cli.main(["--simulate", "--no-ui", "--background", "--seconds", "2"]) == 0
    assert (isolated / "previews" / "preview.png").stat().st_size > 1000
    assert "stopped" in (isolated / "logs" / "turing.log").read_text()


def test_a_second_copy_asks_the_first_to_show_its_panel(isolated, monkeypatch):
    monkeypatch.setattr(cli, "is_first_instance", lambda: False)
    monkeypatch.setattr(config, "OPEN_PANEL_FLAG", isolated / "open_panel.flag")
    assert cli.main(["--no-ui", "--background"]) == 0
    assert (isolated / "open_panel.flag").exists()
