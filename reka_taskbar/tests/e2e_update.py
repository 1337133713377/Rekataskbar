"""
Test de bout en bout des mises à jour, sous Windows, avec le vrai exe
(lancé par le build GitHub après PyInstaller ; pas collecté par pytest).

    python tests/e2e_update.py success    # mise à jour réussie
    python tests/e2e_update.py rollback   # nouvelle version qui ne démarre pas

Un petit serveur local joue le rôle de GitHub : il annonce une version plus
récente (999.0.0) et sert l'exe à télécharger.
- success : il sert le même exe. La barre doit le télécharger, l'installer,
  passer par le gardien, redémarrer, confirmer son bon fonctionnement et
  supprimer l'ancien exe, sans boucler.
- rollback : il sert whoami.exe de Windows, qui s'arrête aussitôt. Le gardien
  doit remettre l'ancien exe, le relancer, et ignorer la version fautive.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST_EXE = ROOT / "dist" / "REKA-Taskbar.exe"
NEWER = "999.0.0"
TIMEOUT_S = 180


def start_server(payload: bytes, switch_to: str | None):
    """version.json annonce NEWER ; après le premier téléchargement, `switch_to`
    si donné (sinon NEWER reste annoncée)."""
    state = {"downloads": 0, "checks": 0}
    sha = hashlib.sha256(payload).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (API http.server)
            if self.path == "/version.json":
                state["checks"] += 1
                version = switch_to if (switch_to and state["downloads"]) else NEWER
                port = self.server.server_port
                body = json.dumps({"version": version,
                                   "url": f"http://127.0.0.1:{port}/REKA-Taskbar.exe",
                                   "sha256": sha, "size": len(payload),
                                   "notes": "test"}).encode()
            elif self.path == "/REKA-Taskbar.exe":
                state["downloads"] += 1
                body = payload
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def wait_for(condition, what: str, timeout: float = TIMEOUT_S) -> None:
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return
        time.sleep(1)
    raise AssertionError(f"{what} (après {timeout:.0f} s)")


def stop_all() -> None:
    for image in ("REKA-Taskbar.exe", "REKA-Taskbar.old.exe", "REKA-Taskbar.broken.exe"):
        subprocess.run(["taskkill", "/IM", image, "/T", "/F"], capture_output=True)


def run(mode: str) -> int:
    version = json.loads((ROOT / "build_info.json").read_text(encoding="utf-8"))["version"]
    original = DIST_EXE.read_bytes()
    work = Path(tempfile.mkdtemp(prefix=f"reka-maj-{mode}-"))
    exe = work / "REKA-Taskbar.exe"
    shutil.copy(DIST_EXE, exe)
    data = work / "appdata" / "REKA Taskbar"
    data.mkdir(parents=True)
    if mode == "success":
        payload, switch_to = original, version
    else:
        system = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "whoami.exe"
        payload, switch_to = system.read_bytes(), None
    server, state = start_server(payload, switch_to)
    (data / "config.json").write_text(json.dumps({
        "update": {"url": f"http://127.0.0.1:{server.server_port}/version.json",
                   "first_check_s": 3, "auto_install": True},
        "bar": {"reserve_space": False}}), encoding="utf-8")
    env = dict(os.environ, APPDATA=str(work / "appdata"))
    env.pop("QT_QPA_PLATFORM", None)
    subprocess.Popen([str(exe)], env=env, cwd=str(work))
    log, marker = data / "app.log", data / "update_pending.json"
    try:
        if mode == "success":
            wait_for(lambda: f"Mise \u00e0 jour : {version} \u2192 {version}" in read(log),
                     "la nouvelle version n'a pas été démarrée par le gardien")
            print("Nouvelle version démarrée par le gardien : OK")
            wait_for(lambda: not marker.exists(), "pas de confirmation au gardien")
            print("Bon fonctionnement confirmé au gardien : OK")
            wait_for(lambda: not (work / "REKA-Taskbar.old.exe").exists(),
                     "ancien exe non supprimé")
            print("Ancien exe supprimé : OK")
            assert exe.read_bytes() == original, "exe inattendu en place"
            time.sleep(10)                      # vérification suivante de la nouvelle version
            assert state["downloads"] == 1, f"{state['downloads']} téléchargements (boucle ?)"
            print("Un seul téléchargement, pas de boucle : OK")
        else:
            wait_for(lambda: f"La version {NEWER} n'a pas d\u00e9marr\u00e9" in read(log),
                     "pas de retour à l'ancienne version")
            print("Retour automatique à l'ancienne version : OK")
            assert exe.read_bytes() == original, "l'exe remis en place n'est pas l'ancien"
            saved = json.loads((data / "config.json").read_text(encoding="utf-8"))
            assert saved["update"]["skipped_version"] == NEWER, saved.get("update")
            print("Version fautive ignorée : OK")
            time.sleep(15)                      # vérification suivante de l'ancienne version
            assert state["downloads"] == 1, f"{state['downloads']} téléchargements (boucle ?)"
            print("Pas de nouvelle tentative : OK")
            wait_for(lambda: not (work / "REKA-Taskbar.broken.exe").exists(),
                     "exe fautif non supprimé", timeout=90)
            print("Exe fautif supprimé : OK")
    except AssertionError as exc:
        print(f"ÉCHEC : {exc}")
        return 1
    finally:
        print("--- app.log (fin) ---")
        print(read(log)[-5000:])
        print("--- update.log ---")
        print(read(data / "update.log"))
        stop_all()
        server.shutdown()
    print("RÉSULTAT : OK")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "success"))
