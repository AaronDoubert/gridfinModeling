"""
gui.py - desktop GUI (PySide6 + matplotlib) for the grid-fin generator.

    python -m gridfin            # opens this window

Left: design inputs.  Right: live 2D planform preview, solved values, and a
"nearby fits" table (double-click a row to jump to that cell count).
Export runs in a background thread so the window stays responsive.
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal, QObject
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QFormLayout,
    QGroupBox, QComboBox, QDoubleSpinBox, QSpinBox, QLineEdit, QPushButton,
    QCheckBox, QLabel, QSplitter, QScrollArea, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QStackedWidget, QHeaderView, QAbstractItemView,
)
import matplotlib
matplotlib.use("QtAgg")
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from . import presets
from .lattice import FinSpec, solve, fit_table
from .plot import draw, KIND_COLOR

CUSTOM = "Custom..."


def _dspin(lo, hi, step, dec, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)
    return s


class ThicknessPicker(QWidget):
    """Stock-size dropdown + custom value (mm). value() is in metres."""
    changed = Signal()

    def __init__(self, options):
        super().__init__()
        self.options = options
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        for label, _ in options:
            self.combo.addItem(label)
        self.combo.insertSeparator(sum(1 for l, _ in options if l.endswith(" mm")))
        self.combo.addItem(CUSTOM)
        self.spin = _dspin(0.1, 500, 0.5, 2, " mm")
        self.spin.setMaximumWidth(110)
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.spin)
        self.combo.currentIndexChanged.connect(self._on_combo)
        self.spin.valueChanged.connect(lambda _: self.changed.emit())

    def _on_combo(self, _):
        text = self.combo.currentText()
        custom = text == CUSTOM
        self.spin.setEnabled(custom)
        if not custom:
            for label, m in self.options:
                if label == text:
                    self.spin.blockSignals(True)
                    self.spin.setValue(m * 1000)
                    self.spin.blockSignals(False)
        self.changed.emit()

    def value(self) -> float:
        return self.spin.value() / 1000

    def setValue(self, m: float):
        self.blockSignals(True)
        self.combo.blockSignals(True)
        idx = next((i for i, (_, v) in enumerate(self.options) if abs(v - m) < 1e-7), None)
        if idx is None:
            self.combo.setCurrentText(CUSTOM)
            self.spin.setEnabled(True)
        else:
            self.combo.setCurrentText(self.options[idx][0])
            self.spin.setEnabled(False)
        self.spin.blockSignals(True)
        self.spin.setValue(m * 1000)
        self.spin.blockSignals(False)
        self.combo.blockSignals(False)
        self.blockSignals(False)


class ExportWorker(QObject):
    progress = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, spec, outdir, opts):
        super().__init__()
        self.spec, self.outdir, self.opts = spec, outdir, opts

    def run(self):
        try:
            from .cad import export      # heavy import, only when exporting
            info = export(self.spec, self.outdir, progress=self.progress.emit, **self.opts)
            self.finished.emit(info)
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Grid fin generator")
        self.resize(1400, 900)
        p = presets.load()
        self.thick_opts = presets.thickness_options(p)
        self.materials = presets.materials(p)
        self.designs = presets.designs(p)
        self.lay = None
        self._loading = False
        self._timer = QTimer(self, singleShot=True, interval=120)
        self._timer.timeout.connect(self.refresh)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_form())
        split.addWidget(self._build_right())
        split.setStretchFactor(1, 1)
        split.setSizes([430, 970])
        self.setCentralWidget(split)
        self.statusBar().showMessage("ready")
        self.set_spec(next(iter(self.designs.values())))

    # ------------------------------------------------------------------ form
    def _build_form(self):
        w = QWidget()
        v = QVBoxLayout(w)

        g = QGroupBox("Design")
        f = QFormLayout(g)
        self.design_combo = QComboBox()
        self.design_combo.addItems(list(self.designs))
        self.design_combo.activated.connect(self._on_design)
        self.name = QLineEdit()
        row = QHBoxLayout()
        b_save, b_load = QPushButton("Save design"), QPushButton("Load...")
        b_save.clicked.connect(self._save_design)
        b_load.clicked.connect(self._load_design)
        row.addWidget(b_save)
        row.addWidget(b_load)
        f.addRow("Preset", self.design_combo)
        f.addRow("Name", self.name)
        f.addRow(row)
        v.addWidget(g)

        g = QGroupBox("Planform")
        f = QFormLayout(g)
        self.b = _dspin(0.1, 50, 0.05, 3, " m")
        self.h = _dspin(0.1, 50, 0.05, 3, " m")
        self.c = _dspin(0.01, 10, 0.01, 3, " m")
        f.addRow("Span b (exact)", self.b)
        f.addRow("Height h (target)", self.h)
        f.addRow("Chord c", self.c)
        v.addWidget(g)

        g = QGroupBox("Lattice")
        f = QFormLayout(g)
        self.sizing = QComboBox()
        self.sizing.addItems(["Cells across span", "Target pitch w"])
        self.size_stack = QStackedWidget()
        self.n_span = QSpinBox()
        self.n_span.setRange(1, 200)
        self.n_span.setKeyboardTracking(False)
        self.pitch = _dspin(0.005, 5, 0.005, 4, " m")
        self.size_stack.addWidget(self.n_span)
        self.size_stack.addWidget(self.pitch)
        self.sizing.currentIndexChanged.connect(self.size_stack.setCurrentIndex)
        self.theta = _dspin(20, 70, 1, 1, " deg")
        self.phase = QComboBox()
        self.phase.addItems(["Auto", "Webs into bottom corners", "Cells in bottom corners"])
        self.tb_mirror = QCheckBox("Mirror top/bottom (coarser height snap)")
        f.addRow("Size by", self.sizing)
        f.addRow("", self.size_stack)
        f.addRow("Web angle", self.theta)
        f.addRow("Phase", self.phase)
        f.addRow(self.tb_mirror)
        v.addWidget(g)

        g = QGroupBox("Stock thickness")
        f = QFormLayout(g)
        self.t = ThicknessPicker(self.thick_opts)
        self.tf = ThicknessPicker(self.thick_opts)
        f.addRow("Web t", self.t)
        f.addRow("Frame t_f", self.tf)
        v.addWidget(g)

        g = QGroupBox("Corners")
        f = QFormLayout(g)
        self.corner = QComboBox()
        self.corner.addItems(["Chamfer (on a web line)", "Square"])
        self.chamfer = _dspin(0, 5, 0.01, 3, " m")
        f.addRow("Style", self.corner)
        f.addRow("Chamfer leg (target)", self.chamfer)
        v.addWidget(g)

        g = QGroupBox("Material / hinge")
        f = QFormLayout(g)
        self.material = QComboBox()
        for name, rho in self.materials.items():
            self.material.addItem(f"{name}  ({rho:g} kg/m3)", name)
        self.x_h = _dspin(-10, 10, 0.01, 3, " m")
        self.z_h = _dspin(-10, 10, 0.01, 3, " m")
        f.addRow("Material", self.material)
        f.addRow("Hinge x_h", self.x_h)
        f.addRow("Hinge z_h", self.z_h)
        v.addWidget(g)

        g = QGroupBox("CFD domain  (x max(b, h))")
        f = QFormLayout(g)
        self.up = _dspin(0.5, 50, 0.5, 1, "")
        self.down = _dspin(0.5, 100, 0.5, 1, "")
        self.side = _dspin(0.5, 50, 0.5, 1, "")
        f.addRow("Upstream", self.up)
        f.addRow("Downstream", self.down)
        f.addRow("Sides", self.side)
        v.addWidget(g)

        g = QGroupBox("Export")
        f = QFormLayout(g)
        self.ex_fin = QCheckBox("Fin STEP")
        self.ex_fluid = QCheckBox("Fluid STEP (full, beta runs)")
        self.ex_half = QCheckBox("Fluid STEP (half, alpha runs)")
        self.ex_dxf = QCheckBox("Planform DXF")
        for cb in (self.ex_fin, self.ex_fluid, self.ex_half, self.ex_dxf):
            cb.setChecked(True)
            f.addRow(cb)
        out_row = QHBoxLayout()
        self.outdir = QLineEdit(str(Path.cwd() / "out"))
        b_browse = QPushButton("...")
        b_browse.setMaximumWidth(32)
        b_browse.clicked.connect(self._browse)
        out_row.addWidget(self.outdir)
        out_row.addWidget(b_browse)
        f.addRow("Folder", out_row)
        self.export_btn = QPushButton("Generate STEP")
        self.export_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.export_btn.clicked.connect(self._export)
        f.addRow(self.export_btn)
        export_group = g
        v.addStretch(1)

        # any edit -> debounced refresh
        for sp in (self.b, self.h, self.c, self.pitch, self.theta, self.chamfer,
                   self.x_h, self.z_h, self.up, self.down, self.side):
            sp.valueChanged.connect(self._changed)
        self.n_span.valueChanged.connect(self._changed)
        for cb in (self.sizing, self.phase, self.corner, self.material):
            cb.currentIndexChanged.connect(self._changed)
        self.tb_mirror.toggled.connect(self._changed)
        self.t.changed.connect(self._changed)
        self.tf.changed.connect(self._changed)
        self.name.textChanged.connect(self._changed)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(w)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(scroll, 1)
        lv.addWidget(export_group)          # always visible
        left.setMinimumWidth(410)
        return left

    def _build_right(self):
        w = QWidget()
        v = QVBoxLayout(w)
        bar = QHBoxLayout()
        self.cb_cl = QCheckBox("Web centrelines")
        self.cb_dims = QCheckBox("Dimensions")
        self.cb_dims.setChecked(True)
        self.cb_hl = QCheckBox("Colour partial cells")
        self.cb_hl.setChecked(True)
        for cb in (self.cb_cl, self.cb_dims, self.cb_hl):
            cb.toggled.connect(self._redraw)
            bar.addWidget(cb)
        legend = QLabel(" ".join(
            f'<span style="background:{KIND_COLOR[k]}">&nbsp;&nbsp;&nbsp;</span> {k}'
            for k in ("edge", "corner")))
        bar.addStretch(1)
        bar.addWidget(legend)
        v.addLayout(bar)

        self.fig = Figure(figsize=(7, 6), dpi=100)   # explicit: some rc files set 200
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasQTAgg(self.fig)
        v.addWidget(NavigationToolbar2QT(self.canvas, self))
        v.addWidget(self.canvas, 1)

        bottom = QHBoxLayout()
        self.readout = QLabel()
        self.readout.setTextFormat(Qt.RichText)
        self.readout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.readout.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bottom.addWidget(self.readout, 3)

        fits = QVBoxLayout()
        fits.addWidget(QLabel("<b>Nearby fits</b> (double-click to use)"))
        self.fit = QTableWidget(0, 4)
        self.fit.setHorizontalHeaderLabels(["cells", "w [mm]", "h [m]", "dh [mm]"])
        self.fit.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.fit.verticalHeader().setVisible(False)
        self.fit.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.fit.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fit.cellDoubleClicked.connect(self._use_fit)
        self.fit.setMinimumWidth(300)
        fits.addWidget(self.fit)
        bottom.addLayout(fits, 2)
        v.addLayout(bottom)
        return w

    # ------------------------------------------------------------------ spec <-> widgets
    def spec(self) -> FinSpec:
        mat = self.material.currentData()
        return FinSpec(
            name=self.name.text().strip() or "gridfin",
            b=self.b.value(), h=self.h.value(), c=self.c.value(),
            t=self.t.value(), tf=self.tf.value(),
            theta=self.theta.value(),
            sizing="cells" if self.sizing.currentIndex() == 0 else "pitch",
            n_span=self.n_span.value(), pitch=self.pitch.value(),
            phase=("auto", "node", "cell")[self.phase.currentIndex()],
            tb_mirror=self.tb_mirror.isChecked(),
            corner="chamfer" if self.corner.currentIndex() == 0 else "square",
            chamfer=self.chamfer.value(),
            material=mat, density=self.materials.get(mat, 7850.0),
            x_h=self.x_h.value(), z_h=self.z_h.value(),
            up=self.up.value(), down=self.down.value(), side=self.side.value())

    def set_spec(self, s: FinSpec):
        self._loading = True
        self.name.setText(s.name)
        self.b.setValue(s.b); self.h.setValue(s.h); self.c.setValue(s.c)
        self.t.setValue(s.t); self.tf.setValue(s.tf)
        self.theta.setValue(s.theta)
        self.sizing.setCurrentIndex(0 if s.sizing == "cells" else 1)
        self.n_span.setValue(s.n_span); self.pitch.setValue(s.pitch)
        self.phase.setCurrentIndex(("auto", "node", "cell").index(s.phase))
        self.tb_mirror.setChecked(s.tb_mirror)
        self.corner.setCurrentIndex(0 if s.corner == "chamfer" else 1)
        self.chamfer.setValue(s.chamfer)
        i = self.material.findData(s.material)
        self.material.setCurrentIndex(max(i, 0))
        self.x_h.setValue(s.x_h); self.z_h.setValue(s.z_h)
        self.up.setValue(s.up); self.down.setValue(s.down); self.side.setValue(s.side)
        self._loading = False
        self.refresh()

    # ------------------------------------------------------------------ updates
    def _changed(self, *_):
        if not self._loading:
            self._timer.start()

    def refresh(self):
        s = self.spec()
        chamfer = s.corner == "chamfer"
        self.chamfer.setEnabled(chamfer)
        self.tb_mirror.setEnabled(not chamfer)
        if chamfer:
            self.tb_mirror.setToolTip("Always on with chamfers so all four corners match")
        try:
            self.lay = solve(s)
        except ValueError as e:
            self.lay = None
            self.readout.setText(f'<span style="color:#c0392b"><b>Invalid:</b> {e}</span>')
            self.ax.clear()
            self.canvas.draw_idle()
            self.export_btn.setEnabled(False)
            return
        self.export_btn.setEnabled(True)
        self._redraw()
        self._update_readout()
        self._update_fits(s)

    def _redraw(self, *_):
        if self.lay is None:
            return
        draw(self.ax, self.lay, centerlines=self.cb_cl.isChecked(),
             dims=self.cb_dims.isChecked(), highlight=self.cb_hl.isChecked())
        self.fig.tight_layout()
        self.canvas.draw_idle()

    def _update_readout(self):
        L, m, s = self.lay, self.lay.metrics, self.lay.spec
        k = m["cell_counts"]
        ch = ""
        if s.corner == "chamfer":
            ch = f"chamfer leg (outer): {m['chamfer_outer_leg_bottom_m']*1000:.0f} mm  (target {s.chamfer*1000:.0f})<br>"
        warn = "".join(f'<br><span style="color:#c0392b">&#9888; {x}</span>' for x in L.warnings)
        ok = ('<span style="color:#1e8449">clean: 0 irregular cells, mirror-symmetric about y=0</span>'
              if k["other"] == 0 and m["symmetry_error"] < 1e-9 else
              '<span style="color:#c0392b">NOT clean</span>')
        self.readout.setText(
            f"<b>{L.J}</b> cells across span, {L.M} half-rows &nbsp;|&nbsp; "
            f"pitch w = <b>{L.w*1000:.1f} mm</b> (perp.), {L.py*1000:.1f} mm along span<br>"
            f"height: <b>{L.h:.3f} m</b> (target {s.h:.3f}, snapped {L.dh*1000:+.0f} mm)<br>"
            f"{ch}"
            f"cells: {m['n_cells']} = {k['full']} full + {k['edge']} edge + {k['corner']} corner &nbsp;|&nbsp; "
            f"min angle {m['min_cell_angle_deg']:.1f} deg<br>"
            f"c/w = {m['c_over_w']:.3f} &nbsp; t/c = {m['t_over_c']:.4f} &nbsp; "
            f"2t/w = {m['solidity_approx_2t_over_w']:.4f} &nbsp; open area = {m['open_area_ratio']:.1%}<br>"
            f"S_ref = {m['S_ref_m2']:.3f} m2 &nbsp; mass = {m['mass_kg']:.0f} kg ({s.material})<br>"
            f"{ok}{warn}")

    def _update_fits(self, s):
        rows = fit_table(s, around=self.lay.J)
        self.fit.setRowCount(len(rows))
        best = min(rows, key=lambda r: abs(r["dh"]))["J"] if rows else None
        for i, r in enumerate(rows):
            vals = [str(r["J"]), f"{r['w']*1000:.1f}", f"{r['h']:.3f}", f"{r['dh']*1000:+.0f}"]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(val)
                it.setTextAlignment(Qt.AlignCenter)
                if r["J"] == self.lay.J:
                    f = it.font(); f.setBold(True); it.setFont(f)
                if r["J"] == best:
                    it.setForeground(Qt.darkGreen)
                self.fit.setItem(i, j, it)

    def _use_fit(self, row, _col):
        J = int(self.fit.item(row, 0).text())
        self.sizing.setCurrentIndex(0)
        self.n_span.setValue(J)

    # ------------------------------------------------------------------ actions
    def _on_design(self, _):
        self.set_spec(self.designs[self.design_combo.currentText()])

    def _save_design(self):
        s = self.spec()
        path, _ = QFileDialog.getSaveFileName(self, "Save design",
                                              str(presets.DESIGNS_DIR / f"{s.name}.json"), "JSON (*.json)")
        if path:
            presets.save_design(s, path)
            self.statusBar().showMessage(f"saved {path}")
            self.designs = presets.designs()
            self.design_combo.clear()
            self.design_combo.addItems(list(self.designs))

    def _load_design(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load design", str(presets.DESIGNS_DIR), "JSON (*.json)")
        if path:
            try:
                self.set_spec(presets.load_design(path))
            except Exception as e:
                QMessageBox.warning(self, "Load failed", str(e))

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.outdir.text())
        if d:
            self.outdir.setText(d)

    def _export(self):
        if self.lay is None:
            return
        opts = dict(fin=self.ex_fin.isChecked(), fluid=self.ex_fluid.isChecked(),
                    half=self.ex_half.isChecked(), dxf=self.ex_dxf.isChecked())
        self.export_btn.setEnabled(False)
        self._thread = QThread(self)
        self._worker = ExportWorker(self.spec(), self.outdir.text(), opts)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(lambda m: self.statusBar().showMessage(f"export: {m}"))
        self._worker.finished.connect(self._export_done)
        self._worker.failed.connect(self._export_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _export_done(self, info):
        self.export_btn.setEnabled(True)
        valid = info.get("fin_valid") and info.get("fluid_valid", True)
        msg = (f"Wrote {len(info['files'])} files to {self.outdir.text()} in {info['build_s']} s\n\n"
               + "\n".join(info["files"]) + f"\n\nsolids valid: {valid}")
        self.statusBar().showMessage(f"export done ({info['build_s']} s)")
        QMessageBox.information(self, "Export complete", msg)

    def _export_failed(self, tb):
        self.export_btn.setEnabled(True)
        self.statusBar().showMessage("export failed")
        QMessageBox.critical(self, "Export failed", tb[-2000:])


def main(argv=None):
    app = QApplication.instance() or QApplication(sys.argv if argv is None else argv)
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
