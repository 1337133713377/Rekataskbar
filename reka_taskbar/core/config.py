"""
Configuration de REKA Taskbar : emplacements des fichiers et lecture/écriture
de config.json (même principe que REKA).

- Le config.json livré avec l'application contient les valeurs par défaut ;
  dans l'exe PyInstaller il est en lecture seule, on ne le modifie jamais.
- La config de l'utilisateur vit dans %APPDATA%/REKA Taskbar/config.json.
  Elle est fusionnée avec les défauts à chaque démarrage : les clés ajoutées
  par une mise à jour apparaissent toutes seules.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

APP_NAME = "REKA Taskbar"
APP_VERSION = "1.3.0"
APP_AUTHORS = "Regrettable et Zerka"
CONFIG_FILENAME = "config.json"
LAYOUT_VERSION = 2            # 2 : le lecteur de musique au milieu de la barre

log = logging.getLogger(__name__)

_save_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Emplacements
# --------------------------------------------------------------------------- #
def resource_dir() -> Path:
    """Dossier des ressources livrées (assets/, config.json par défaut) :
    dossier d'extraction de PyInstaller dans l'exe, racine du projet sinon."""
    bundle = getattr(sys, "_MEIPASS", None)
    return Path(bundle) if bundle else Path(__file__).resolve().parent.parent


def resource_path(relative: str | Path) -> Path:
    return resource_dir() / relative


def roaming_dir() -> Path:
    """%APPDATA% (hors Windows, en développement : ~/.config)."""
    base = os.environ.get("APPDATA")
    return Path(base) if base else Path.home() / ".config"


def app_data_dir() -> Path:
    """Dossier de données de la barre : %APPDATA%/REKA Taskbar (créé si besoin)."""
    path = roaming_dir() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_config_path() -> Path:
    return app_data_dir() / CONFIG_FILENAME


# --------------------------------------------------------------------------- #
# Lecture / écriture
# --------------------------------------------------------------------------- #
def default_config() -> dict[str, Any]:
    return read_json(resource_path(CONFIG_FILENAME))


def load_config() -> dict[str, Any]:
    """Défauts livrés + surcharge utilisateur. Une config utilisateur corrompue
    est mise de côté et remplacée par les défauts, sans bloquer le démarrage."""
    defaults = default_config()
    user_path = user_config_path()
    user: dict[str, Any] = {}
    if user_path.is_file():
        try:
            user = read_json(user_path)
        except (OSError, ValueError) as exc:
            broken = user_path.with_name("config.invalide.json")
            log.error("Config utilisateur illisible (%s) : renommée en %s.", exc, broken.name)
            try:
                os.replace(user_path, broken)
            except OSError as move_error:
                log.error("Config illisible non renommée (%s).", move_error)
                return deep_merge(defaults, {})
    cfg = deep_merge(defaults, user)
    if user and migrate_layout(cfg, user):
        save_quietly(cfg)
    if not user_path.is_file():
        save_config(cfg)
    return cfg


def migrate_layout(cfg: dict[str, Any], user: dict[str, Any]) -> bool:
    """Une fois, pour une config d'avant la 1.2 : le lecteur de musique va au
    milieu de la barre (en tête de la zone du centre), où qu'il soit. True si
    la config a changé. Ensuite, la disposition choisie est respectée."""
    try:
        version = int(user.get("layout_version", 1))
    except (TypeError, ValueError):
        version = 1
    if version >= LAYOUT_VERSION:
        return False
    cfg["layout_version"] = LAYOUT_VERSION
    layout = cfg.get("layout")
    if not isinstance(layout, dict):
        return True
    for zone, keys in list(layout.items()):
        if isinstance(keys, list):
            layout[zone] = [key for key in keys if key != "media"]
    center = layout.get("center") if isinstance(layout.get("center"), list) else []
    layout["center"] = ["media", *center]
    log.info("Disposition mise à jour : lecteur de musique au milieu de la barre.")
    return True


def save_config(cfg: dict[str, Any]) -> None:
    """Écriture atomique (fichier temporaire puis remplacement)."""
    path = user_config_path()
    tmp = path.with_suffix(".tmp")
    data = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    with _save_lock:
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)


def save_quietly(cfg: dict[str, Any]) -> bool:
    try:
        save_config(cfg)
        return True
    except OSError as exc:
        log.error("Config non sauvegardée : %s", exc)
        return False


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} doit contenir un objet JSON")
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Fusion récursive : les dicts sont fusionnés clé par clé, tout le reste
    (listes, nombres, textes) est remplacé par la valeur de `override`."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
