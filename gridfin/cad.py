"""
cad.py - 3D solids + STEP/DXF/JSON export (CadQuery / OpenCascade).

The fin is built as ONE planar face (outer frame wire + every cell as an inner
wire) extruded along the chord.  No 3D booleans are needed for the fin itself,
so it is fast and always produces a valid solid.  Only the fluid domain uses
booleans (box minus fin).

Outputs per design:
  <name>_fin.step         solid fin
  <name>_fluid.step       box minus fin, full model (beta runs)
  <name>_fluid_half.step  same, cut at the y = 0 mid-span plane (alpha runs only)
  <name>_planform.dxf     2D section in the y-z plane (metres), for Onshape comparison
  <name>.json             parameters + solved lattice + dimensionless groups
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import cadquery as cq

from .lattice import FinSpec, Layout, solve


def _wire(ring, x0):
    return cq.Wire.makePolygon([cq.Vector(x0, y, z) for y, z in ring], close=True)


def fin_solid(lay: Layout) -> cq.Solid:
    c = lay.spec.c
    x0 = -c / 2
    face = cq.Face.makeFromWires(_wire(lay.outer, x0), [_wire(v, x0) for v in lay.voids])
    return cq.Solid.extrudeLinear(face, cq.Vector(c, 0, 0))


def fluid_domain(lay: Layout, fin: cq.Solid):
    sp = lay.spec
    Lr = max(sp.b, lay.h)
    x0, x1 = -sp.c / 2 - sp.up * Lr, sp.c / 2 + sp.down * Lr
    Wy = sp.b + 2 * sp.side * Lr
    Hz = lay.h + 2 * sp.side * Lr
    box = cq.Solid.makeBox(x1 - x0, Wy, Hz, pnt=cq.Vector(x0, -Wy / 2, -Hz / 2))
    full = box.cut(fin)
    half_box = cq.Solid.makeBox(x1 - x0, Wy / 2, Hz, pnt=cq.Vector(x0, 0, -Hz / 2))
    half = half_box.cut(fin)
    return full, half


def write_dxf(lay: Layout, path):
    import ezdxf
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6           # metres
    msp = doc.modelspace()
    doc.layers.add("FRAME_OUTER", color=7)
    doc.layers.add("FRAME_INNER", color=8)
    doc.layers.add("CELLS", color=5)
    msp.add_lwpolyline(lay.outer, close=True, dxfattribs={"layer": "FRAME_OUTER"})
    msp.add_lwpolyline(lay.inner, close=True, dxfattribs={"layer": "FRAME_INNER"})
    for v in lay.voids:
        msp.add_lwpolyline(v, close=True, dxfattribs={"layer": "CELLS"})
    doc.saveas(path)


def summary(lay: Layout) -> dict:
    return {"params": lay.spec.to_dict(),
            "solved": {"J": lay.J, "M": lay.M, "w": lay.w, "py": lay.py, "pz": lay.pz,
                       "h": lay.h, "b_inner": lay.b_i, "h_inner": lay.h_i,
                       "phase_bottom_row": lay.i1, "q_bottom": lay.q_bot, "q_top": lay.q_top},
            "derived": lay.metrics,
            "warnings": lay.warnings}


def export(spec: FinSpec, outdir=".", fin=True, fluid=True, half=True, dxf=True,
           progress=lambda msg: None) -> dict:
    t0 = time.time()
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    progress("solving lattice")
    lay = solve(spec)
    info = summary(lay)
    files = []
    progress("building fin solid")
    solid = fin_solid(lay)
    info["fin_valid"] = solid.isValid()
    info["fin_volume_m3"] = solid.Volume()
    info["n_faces"] = len(solid.Faces())
    stem = spec.name or "gridfin"
    if fin:
        p = out / f"{stem}_fin.step"
        solid.exportStep(str(p))
        files.append(p.name)
    if fluid or half:
        progress("building fluid domain (boolean)")
        full_d, half_d = fluid_domain(lay, solid)
        info["fluid_valid"] = full_d.isValid() and half_d.isValid()
        if fluid:
            p = out / f"{stem}_fluid.step"
            full_d.exportStep(str(p))
            files.append(p.name)
        if half:
            p = out / f"{stem}_fluid_half.step"
            half_d.exportStep(str(p))
            files.append(p.name)
    if dxf:
        p = out / f"{stem}_planform.dxf"
        write_dxf(lay, p)
        files.append(p.name)
    info["files"] = files
    info["build_s"] = round(time.time() - t0, 2)
    with open(out / f"{stem}.json", "w") as f:
        json.dump(info, f, indent=2)
    progress(f"done in {info['build_s']} s")
    return info
