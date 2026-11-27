"""Regenerate the GUI screenshots in docs/ and docs/images/.

Needs a display. On a headless box:

    xvfb-run -a --server-args="-screen 0 1600x1000x24" \
        python3 docs/make_screenshots.py

It drives the real MainWindow, so if the layout changes the shots follow.
The two 3D line drawings (images/fin-iso.png, images/fin-corner.png) are not
made here - see gui-notes.md for how those are produced.
"""
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QTimer, QEventLoop, QRect

DOCS = Path(__file__).resolve().parent
IMAGES = DOCS / "images"
IMAGES.mkdir(parents=True, exist_ok=True)

app = QApplication(sys.argv)
import gridfin.gui as gui                       # noqa: E402  (QApplication first)

win = gui.MainWindow()
win.show()


def settle(ms=400):
    """Let the debounce timer fire and Qt repaint."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    app.processEvents()


def save(pixmap, path):
    pixmap.save(str(path))
    print(f"  {path.name:22s} {pixmap.width():>5}x{pixmap.height():<5} "
          f"{path.stat().st_size // 1024:>4} kB")


def shot(path, rect=None):
    settle()
    save(win.grab(rect) if rect else win.grab(), path)


def rect_of(*widgets, pad=6, tight=False):
    """Bounding rect of widgets in window coordinates."""
    r = None
    for wd in widgets:
        size = wd.size()
        if tight:                               # labels are taller than their text
            size.setHeight(min(size.height(), wd.sizeHint().height()))
        g = QRect(wd.mapTo(win, wd.rect().topLeft()), size)
        r = g if r is None else r.united(g)
    return r.adjusted(-pad, -pad, pad, pad)


def preset(name):
    win.design_combo.setCurrentIndex(list(win.designs).index(name))
    win._on_design(0)
    settle()


canvas = lambda: rect_of(win.canvas)

preset("baseline")
shot(DOCS / "gui.png")

preset("coarse (7 cells)")
shot(IMAGES / "lattice-coarse.png", canvas())
preset("fine (14 cells)")
shot(IMAGES / "lattice-fine.png", canvas())

preset("square corners")
win.tb_mirror.setChecked(True)
shot(IMAGES / "corners-square.png", canvas())

preset("baseline")
shot(IMAGES / "readout.png", rect_of(win.readout, tight=True))
shot(IMAGES / "fits.png", rect_of(win.fit).adjusted(0, -26, 0, 28))

win.cb_cl.setChecked(True)
shot(IMAGES / "centrelines.png", canvas())
win.cb_cl.setChecked(False)

# a design with no clean lattice: web thicker than the cell pitch
preset("fine (14 cells)")
win.t.combo.setCurrentText(gui.CUSTOM)
win.t.spin.setValue(300)
shot(IMAGES / "no-fit.png")

# the export dialog, through the real worker thread
preset("baseline")
win.outdir.setText(str(DOCS.parent / "out"))
settle()
done = []


def grab_dialog(parent, title, text, *a, **kw):
    box = QMessageBox(QMessageBox.Information, title, text, QMessageBox.Ok, parent)
    box.show()
    settle(250)
    save(box.grab(), IMAGES / "export-done.png")
    box.close()
    done.append(True)
    return QMessageBox.Ok


gui.QMessageBox.information = grab_dialog
win._export()
for _ in range(120):
    settle(250)
    if done:
        break
if not done:
    sys.exit("export never finished - no export-done.png written")
print("done")
