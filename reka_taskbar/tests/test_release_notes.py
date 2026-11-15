"""Nouveautés : lecture de NOUVEAUTES.md et fenêtre."""

from core import config
from core.release_notes import load_notes, notes_between, sections

TEXT = """# Nouveautés

## 1.10.0

- dix

## 1.2.0 (patch)

- deux

## 1.1.0

- un

## 1.0.0

Première version.
"""


def test_sections_and_ranges():
    assert [v for v, _ in sections(TEXT)] == ["1.10.0", "1.2.0", "1.1.0", "1.0.0"]
    assert [v for v, _ in notes_between(TEXT, "1.1.0", "1.10.0")] == ["1.10.0", "1.2.0"]
    assert [v for v, _ in notes_between(TEXT, None, "1.2.0")] == ["1.2.0", "1.1.0", "1.0.0"]
    assert notes_between(TEXT, "1.10.0", "1.10.0") == []
    assert dict(notes_between(TEXT, "1.0.0", "1.1.0"))["1.1.0"] == "- un"


def test_shipped_notes_cover_the_current_version():
    text = load_notes()
    assert any(version == config.APP_VERSION for version, _ in sections(text)), \
        "ajoute une section « ## " + config.APP_VERSION + " » dans NOUVEAUTES.md"


def test_notes_dialog(qapp):
    from ui.notes_dialog import NotesDialog

    dialog = NotesDialog(since="1.0.0", text=TEXT.replace("1.10.0", config.APP_VERSION))
    assert dialog.versions[0] == config.APP_VERSION
    assert "1.0.0" not in dialog.versions
    assert not dialog.grab().isNull()
