"""The window builds, solves, and says so when it cannot.

Nothing else covers gui.py, and the two things checked here - that every preset
lands on a clean lattice, and that an unsolvable design is reported rather than
left as stale state - are the ones most likely to break when the form is edited.
Runs on the offscreen Qt platform, so it needs no display, only Qt's system
libraries (libegl1, libgl1, libxkbcommon0 on Debian/Ubuntu).
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets",
                                reason="PySide6 missing or Qt's system libraries are not installed")


@pytest.fixture(scope="session")
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(qapp):
    from gridfin.gui import MainWindow
    w = MainWindow()
    w.show()
    qapp.processEvents()
    yield w
    w.close()


def test_opens_on_a_clean_lattice(win):
    assert win.lay is not None
    assert win.lay.metrics["cell_counts"]["other"] == 0
    assert win.lay.metrics["symmetry_error"] < 1e-9
    assert win.export_btn.isEnabled()
    assert win.fit.rowCount() > 0


def test_every_preset_solves_cleanly(win):
    names = list(win.designs)
    assert names, "no presets loaded"
    for i, name in enumerate(names):
        win.design_combo.setCurrentIndex(i)
        win._on_design(i)
        assert win.lay is not None, f"{name} did not solve"
        assert win.lay.metrics["cell_counts"]["other"] == 0, f"{name} has irregular cells"


def test_sizing_by_pitch_still_fills_the_table(win):
    win.sizing.setCurrentIndex(1)              # "Target pitch w"
    win.pitch.setValue(0.20)
    win.refresh()
    assert win.lay is not None
    assert win.fit.rowCount() > 0
    assert win.size_label.text() == "Target pitch w"


def test_unsolvable_design_is_reported_not_left_stale(win):
    assert win.fit.rowCount() > 0              # a table to go stale in the first place
    win.t.combo.setCurrentText("Custom...")
    win.t.spin.setValue(300)                   # web far thicker than the cell pitch
    win.refresh()
    assert win.lay is None
    assert not win.export_btn.isEnabled()
    assert win.fit.rowCount() == 0, "stale fits rows survive an unsolvable design"
    assert "no clean lattice" in win.statusBar().currentMessage()
