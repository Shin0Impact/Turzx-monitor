from __future__ import annotations

import json

from turingscreen import config


def test_defaults_when_nothing_exists(tmp_path):
    cfg = config.load(tmp_path / "none.toml", tmp_path / "none.json")
    assert cfg == config.DEFAULTS
    assert cfg is not config.DEFAULTS


def test_config_file_overrides_defaults(tmp_path):
    (tmp_path / "c.toml").write_text("[screen]\nbrightness = 70\n[bigstats]\nnet = true\n")
    cfg = config.load(tmp_path / "c.toml", tmp_path / "none.json")
    assert cfg["screen"]["brightness"] == 70
    assert cfg["screen"]["orientation"] == "portrait"
    assert cfg["bigstats"]["net"] is True


def test_saved_state_overrides_config_file(tmp_path):
    (tmp_path / "c.toml").write_text("[screen]\nbrightness = 70\n")
    (tmp_path / "s.json").write_text(json.dumps({"screen.brightness": 30, "display.mode": "clock"}))
    cfg = config.load(tmp_path / "c.toml", tmp_path / "s.json")
    assert cfg["screen"]["brightness"] == 30
    assert cfg["display"]["mode"] == "clock"


def test_unknown_or_unsafe_keys_in_state_are_ignored(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps({"screen.port": "COM9", "nonsense": 1, "app.tray": False}))
    cfg = config.load(tmp_path / "none.toml", tmp_path / "s.json")
    assert cfg["screen"]["port"] == "AUTO"
    assert cfg["app"]["tray"] is True


def test_corrupt_state_file_is_ignored(tmp_path):
    (tmp_path / "s.json").write_text("{ not json")
    assert config.load(tmp_path / "none.toml", tmp_path / "s.json") == config.DEFAULTS


def test_save_round_trip(tmp_path):
    cfg = config.load(tmp_path / "none.toml", tmp_path / "s.json")
    cfg["display"]["clock_color"] = "#ff0000"
    cfg["bigstats"]["net"] = True
    config.save(cfg, tmp_path / "s.json")
    again = config.load(tmp_path / "none.toml", tmp_path / "s.json")
    assert again["display"]["clock_color"] == "#ff0000"
    assert again["bigstats"]["net"] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_gif_folder_resolves_relative_to_the_project(tmp_path):
    assert config.gif_folder({"gif": {"folder": "gifs"}}) == config.ROOT / "gifs"
    assert config.gif_folder({"gif": {"folder": str(tmp_path)}}) == tmp_path
