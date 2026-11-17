import json

from core import config


def test_load_creates_user_config_from_defaults(appdata):
    cfg = config.load_config()
    assert cfg["bar"]["edge"] == "top"
    assert (appdata / "REKA Taskbar" / "config.json").is_file()


def test_user_values_are_kept_and_new_keys_appear(appdata):
    path = config.user_config_path()
    path.write_text(json.dumps({"bar": {"edge": "bottom"}, "layout": {"left": ["clock"]}}),
                    encoding="utf-8")
    cfg = config.load_config()
    assert cfg["bar"]["edge"] == "bottom"
    assert cfg["bar"]["height"] == 44                  # clé absente : valeur par défaut
    assert cfg["layout"]["left"] == ["clock"]          # une liste est remplacée, pas fusionnée
    assert cfg["layout"]["right"]


def test_corrupted_user_config_is_set_aside(appdata):
    path = config.user_config_path()
    path.write_text("{ pas du json", encoding="utf-8")
    cfg = config.load_config()
    assert cfg["bar"]["edge"] == "top"
    assert path.with_name("config.invalide.json").is_file()


def test_save_is_atomic_and_readable(cfg):
    cfg["bar"]["height"] = 50
    config.save_config(cfg)
    assert config.read_json(config.user_config_path())["bar"]["height"] == 50
    assert not config.user_config_path().with_suffix(".tmp").exists()


def test_media_player_moves_to_the_middle_once(appdata):
    path = config.user_config_path()
    path.write_text(json.dumps({"layout": {"left": ["start", "media", "tasks"], "center": [],
                                           "right": ["clock"]}}), encoding="utf-8")
    cfg = config.load_config()
    assert cfg["layout"] == {"left": ["start", "tasks"], "center": ["media"], "right": ["clock"]}
    assert config.read_json(path)["layout_version"] == config.LAYOUT_VERSION
    cfg["layout"]["center"] = []                         # retiré ensuite : c'est respecté
    config.save_config(cfg)
    assert config.load_config()["layout"]["center"] == []


def test_new_config_has_the_player_in_the_middle(appdata):
    cfg = config.load_config()
    assert cfg["layout"]["center"] == ["media"] and cfg["layout_version"] == config.LAYOUT_VERSION
    assert cfg["bar"]["show_hotkey"] == "Ctrl+Alt+B" and cfg["widgets"]["media"]["show_idle"]
