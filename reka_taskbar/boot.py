"""
Point d'entrée de REKA-Taskbar.exe.

« --update-watchdog » : le gardien des mises à jour (core/update_guard.py),
sans aucun import de Qt ni du reste de l'application ; il tourne dans l'ancien
exe et doit marcher même si la nouvelle version est cassée.
Sinon : la barre (main.py).
"""

import sys


def run() -> int:
    if "--update-watchdog" in sys.argv[1:]:
        from core import update_guard

        return update_guard.watchdog_main()
    import main

    return main.main()


if __name__ == "__main__":
    sys.exit(run())
