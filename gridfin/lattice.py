"""
lattice.py - the "smart" grid-fin lattice solver (pure 2D, no CAD kernel).

Frame (same as the project variable list):
    x = chord / flow direction (extrusion direction, not used here)
    y = span  = HINGE AXIS
    z = height (tangential)
Origin: planform centre.

The idea
--------
The webs are two families of straight lines at +theta and -theta to the hinge
axis, perpendicular spacing w.  Where a web of one family crosses a web of the
other we have a *node*.  For a symmetric lattice (mirror about y = 0, needed for
the half-model) the nodes always sit on a rhombic grid

        y_j = j * py/2          py = w / sin(theta)   (pitch along the span)
        z_i = z0 + i * pz/2     pz = w / cos(theta)   (pitch along the height)
        with  i = j  (mod 2)

A frame edge is "clean" (every web hits it at a node, every edge cell is a whole
half-cell triangle, zero slivers) exactly when the edge lies on a node column /
node row.  So, measured on the INNER face of the frame:

        inner span    b_i = J * py          J = cells across the span (integer)
        inner height  h_i = M * pz/2        M = half-cell rows       (integer)

The span b is kept exact, so the pitch w is solved from J, and the height h is
snapped to the nearest clean value.  A chamfer is clean when its inner face lies
exactly ON a web line, which means its legs are q*py/2 by q*pz/2 for an integer q
with the right parity.  The parity (and hence which q values are allowed) is set
by the lattice "phase", which the solver picks automatically to hit the
requested chamfer size as closely as possible.

Everything here is analytic; shapely is only used to clip cells against the
frame and to measure areas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict, fields, replace

from shapely.geometry import Polygon, LineString
from shapely.geometry.polygon import orient

CORNERS = ("square", "chamfer")
PHASES = ("auto", "node", "cell")      # what sits in the bottom corners
SIZING = ("cells", "pitch")


@dataclass
class FinSpec:
    """Everything the user chooses.  All lengths in metres, angles in degrees."""
    name: str = "baseline"
    # planform
    b: float = 4.0              # outer span along hinge axis (kept exact)
    h: float = 3.5              # TARGET outer height (snapped to a clean value)
    c: float = 0.5              # chord / lattice depth (extrusion along x)
    # stock thicknesses
    t: float = 0.020            # web thickness
    tf: float = 0.050           # frame thickness
    # lattice
    theta: float = 45.0         # web angle to hinge axis
    sizing: str = "cells"       # "cells": n_span drives; "pitch": target w drives
    n_span: int = 10            # cells across the span
    pitch: float = 0.276        # target perpendicular cell pitch w (sizing="pitch")
    phase: str = "auto"         # "auto" | "node" (webs run into bottom corners) | "cell"
    tb_mirror: bool = False     # force top/bottom mirror symmetry (coarser height snap);
                                # always on for chamfered corners so all 4 corners match
    # corners
    corner: str = "chamfer"     # "square" | "chamfer"
    chamfer: float = 0.30       # target OUTER chamfer leg measured along the span
    # material (for mass readout)
    material: str = "Steel"
    density: float = 7850.0
    # hinge axis location (recorded for the C_h reference)
    x_h: float = 0.0
    z_h: float = 0.0
    # CFD fluid domain extents, multiples of max(b, h)
    up: float = 3.0
    down: float = 6.0
    side: float = 3.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FinSpec":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})


@dataclass
class Layout:
    """The solved, clean geometry."""
    spec: FinSpec
    J: int                      # cells across span
    M: int                      # half-cell rows across height
    w: float                    # perpendicular cell pitch (web centreline spacing)
    py: float                   # pitch along span
    pz: float                   # pitch along height
    b_i: float
    h_i: float
    h: float                    # actual outer height after snapping
    i1: int                     # row index of bottom edge (sets the phase)
    q_bot: int                  # chamfer size in half-cell steps, bottom corners
    q_top: int                  # chamfer size in half-cell steps, top corners
    phi: float                  # lattice offset: web lines are u,v = phi + k*w
    inner: list = field(default_factory=list)   # inner frame face polygon [(y,z)...]
    outer: list = field(default_factory=list)   # outer planform polygon
    voids: list = field(default_factory=list)   # list of void polygons
    void_kind: list = field(default_factory=list)  # "full" | "edge" | "corner" | "chamfer" | "other"
    centerlines: list = field(default_factory=list)  # web centreline segments for preview
    metrics: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    @property
    def dh(self) -> float:
        return self.h - self.spec.h


# ----------------------------------------------------------------------------- helpers

def _clean_ring(coords, tol=1e-9):
    """Drop the closing point, near-duplicate points and collinear points."""
    pts = [tuple(p) for p in coords]
    if len(pts) > 1 and math.dist(pts[0], pts[-1]) < tol:
        pts = pts[:-1]
    out = []
    for p in pts:
        if not out or math.dist(p, out[-1]) > tol:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) <= tol:
        out.pop()
    changed = True
    while changed and len(out) > 3:
        changed = False
        for i in range(len(out)):
            a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if abs(cross) < tol * max(math.dist(a, b), math.dist(b, c), tol):
                out.pop(i)
                changed = True
                break
    return out


def _angles(ring):
    """Interior angles (deg) of a convex polygon."""
    n = len(ring)
    res = []
    for i in range(n):
        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
        v1 = (a[0] - b[0], a[1] - b[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        d = math.hypot(*v1) * math.hypot(*v2)
        if d == 0:
            continue
        cosang = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / d))
        res.append(math.degrees(math.acos(cosang)))
    return res


def outer_to_inner_leg(outer_leg, tf, theta_deg):
    """Chamfer leg along the span: outer face -> inner face (mitred offset)."""
    th = math.radians(theta_deg)
    s, c = math.sin(th), math.cos(th)
    return outer_leg - tf * (1.0 - (1.0 - c) / s)


def inner_to_outer_leg(inner_leg, tf, theta_deg):
    th = math.radians(theta_deg)
    s, c = math.sin(th), math.cos(th)
    return inner_leg + tf * (1.0 - (1.0 - c) / s) if inner_leg > 0 else 0.0


# ----------------------------------------------------------------------------- solver

def _snap(spec: FinSpec):
    """Integer cell counts + pitches.  Returns (J, M, w, py, pz, b_i, h_i)."""
    if not (5.0 <= spec.theta <= 85.0):
        raise ValueError("lattice angle must be between 5 and 85 deg")
    th = math.radians(spec.theta)
    s, c = math.sin(th), math.cos(th)
    b_i = spec.b - 2 * spec.tf
    h_i_target = spec.h - 2 * spec.tf
    if b_i <= 0 or h_i_target <= 0:
        raise ValueError("frame thickness is too large for the planform")
    if spec.sizing == "pitch":
        if spec.pitch <= 0:
            raise ValueError("target pitch must be positive")
        J = max(1, round(b_i * s / spec.pitch))
    else:
        J = max(1, int(spec.n_span))
    w = b_i * s / J
    py, pz = w / s, w / c
    # An even row count makes top and bottom identical.  Chamfered corners always
    # use it, otherwise top and bottom chamfers would differ by half a cell.
    if spec.tb_mirror or spec.corner == "chamfer":
        M = max(2, 2 * round(h_i_target / pz))
    else:
        M = max(2, round(h_i_target / (pz / 2)))
    return J, M, w, py, pz, b_i, M * pz / 2


def _pick_q(parity, target_q, q_max, corner):
    """Nearest allowed chamfer step count with the required parity."""
    if corner == "square":
        return 0
    q_min = 1 if parity else 2
    if q_max < q_min:
        return 0
    best = None
    for q in range(q_min, q_max + 1, 2):
        if best is None or abs(q - target_q) < abs(best - target_q):
            best = q
    return best


def _choose_phase(spec, J, M, py, pz, b_i, h_i):
    """Pick bottom-row index i1 (0/1) and chamfer step counts (q_bot, q_top)."""
    if spec.phase == "node":
        cands = [J % 2]
    elif spec.phase == "cell":
        cands = [(J + 1) % 2]
    else:
        cands = [J % 2, (J + 1) % 2]      # 'node' first so it wins ties
    inner_target = max(outer_to_inner_leg(spec.chamfer, spec.tf, spec.theta), 0.0)
    target_q = inner_target / (py / 2)
    best = None
    for i1 in cands:
        i2 = i1 + M
        par_b, par_t = (J - i1) % 2, (J - i2) % 2
        q_max_y = J - 1                     # leave some straight edge on top/bottom
        q_b = _pick_q(par_b, target_q, q_max_y, spec.corner)
        q_t = _pick_q(par_t, target_q, q_max_y, spec.corner)
        # chamfers must leave a straight piece on the side edges too
        while q_b + q_t >= M and (q_b > 0 or q_t > 0):
            if q_t >= q_b and q_t > 0:
                q_t = q_t - 2 if q_t - 2 >= (1 if par_t else 2) else 0
            else:
                q_b = q_b - 2 if q_b - 2 >= (1 if par_b else 2) else 0
        if spec.corner == "chamfer":
            leg = lambda q: q * py / 2
            score = abs(leg(q_b) - inner_target) + abs(leg(q_t) - inner_target)
        else:
            score = 0.0
        score += 1e-6 * cands.index(i1)     # deterministic tie-break
        if best is None or score < best[0]:
            best = (score, i1, q_b, q_t)
    return best[1], best[2], best[3]


def solve(spec: FinSpec, geometry: bool = True) -> Layout:
    J, M, w, py, pz, b_i, h_i = _snap(spec)
    th = math.radians(spec.theta)
    s, c = math.sin(th), math.cos(th)
    i1, q_b, q_t = _choose_phase(spec, J, M, py, pz, b_i, h_i)
    z0 = -h_i / 2 - i1 * pz / 2            # row i sits at z0 + i*pz/2
    phi = c * z0
    lay = Layout(spec=spec, J=J, M=M, w=w, py=py, pz=pz, b_i=b_i, h_i=h_i,
                 h=h_i + 2 * spec.tf, i1=i1, q_bot=q_b, q_top=q_t, phi=phi)

    warn = lay.warnings
    if spec.t >= 0.6 * w:
        warn.append(f"web t={spec.t*1e3:.1f} mm is {spec.t/w:.0%} of the pitch: cells nearly closed")
    if spec.corner == "chamfer" and (q_b == 0 or q_t == 0):
        warn.append("chamfer too large for this grid - some corners left square")
    if abs(lay.dh) > 0.05 * spec.h:
        warn.append(f"height snapped by {lay.dh*1e3:+.0f} mm (>5%) - try another cell count")
    if spec.t >= w:
        raise ValueError("web thickness exceeds the cell pitch")

    if not geometry:
        return lay

    # -- inner frame face (CCW) ------------------------------------------------
    yb, zb = b_i / 2, h_i / 2
    Lb, Hb = q_b * py / 2, q_b * pz / 2
    Lt, Ht = q_t * py / 2, q_t * pz / 2
    pts = [(-yb + Lb, -zb), (yb - Lb, -zb), (yb, -zb + Hb), (yb, zb - Ht),
           (yb - Lt, zb), (-yb + Lt, zb), (-yb, zb - Ht), (-yb, -zb + Hb)]
    lay.inner = _clean_ring(pts)
    inner = Polygon(lay.inner)
    outer = inner.buffer(spec.tf, join_style="mitre", mitre_limit=20.0)
    lay.outer = _clean_ring(orient(outer, 1.0).exterior.coords)

    # -- cells: shrink each lattice rhombus by t/2 and clip to the inner face ---
    def yz(u, v):
        return ((v - u) / (2 * s), (u + v) / (2 * c))

    us = [-s * y + c * z for y, z in lay.inner]
    vs = [s * y + c * z for y, z in lay.inner]
    k0 = math.floor((min(us) - phi) / w) - 1
    k1 = math.ceil((max(us) - phi) / w) + 1
    l0 = math.floor((min(vs) - phi) / w) - 1
    l1 = math.ceil((max(vs) - phi) / w) + 1
    a = w - spec.t
    full_area = a * a / math.sin(2 * th)
    ht = spec.t / 2
    for k in range(k0, k1):
        u0, u1 = phi + k * w + ht, phi + (k + 1) * w - ht
        for l in range(l0, l1):
            v0, v1 = phi + l * w + ht, phi + (l + 1) * w - ht
            cell = Polygon([yz(u0, v0), yz(u1, v0), yz(u1, v1), yz(u0, v1)])
            if not cell.intersects(inner):
                continue
            piece = cell.intersection(inner)
            if piece.is_empty or piece.area < 1e-9 * full_area:
                continue
            geoms = getattr(piece, "geoms", [piece])
            for g in geoms:
                if g.geom_type != "Polygon" or g.area < 1e-9 * full_area:
                    continue
                ring = _clean_ring(orient(g, -1.0).exterior.coords)  # CW = hole
                lay.voids.append(ring)
                ratio = g.area / full_area
                n = len(ring)
                if n == 4 and ratio > 0.999:
                    kind = "full"
                elif n == 3 and abs(ratio - 0.5) < 1e-3:
                    kind = "edge"
                elif n == 3 and abs(ratio - 0.25) < 1e-3:
                    kind = "corner"
                elif n == 3:
                    kind = "chamfer"
                else:
                    kind = "other"
                lay.void_kind.append(kind)

    # -- centrelines for the preview ------------------------------------------
    R = math.hypot(b_i, h_i)
    for fam in (-1, 1):                  # u-lines (fam=-1) and v-lines (fam=+1)
        for k in range(min(k0, l0), max(k1, l1) + 1):
            val = phi + k * w
            # line: fam*s*y + c*z = val ; direction (c, -fam*s)
            p0 = ((fam * s) * val, c * val)       # foot point (normal * val)
            d = (c, -fam * s)
            seg = LineString([(p0[0] - R * d[0], p0[1] - R * d[1]),
                              (p0[0] + R * d[0], p0[1] + R * d[1])]).intersection(inner)
            for g in getattr(seg, "geoms", [seg]):
                if g.geom_type == "LineString" and g.length > 1e-9:
                    lay.centerlines.append(list(g.coords))

    _metrics(lay)
    return lay


def _metrics(lay: Layout):
    sp = lay.spec
    outer_area = Polygon(lay.outer).area
    void_areas = [Polygon(v).area for v in lay.voids]
    void_area = sum(void_areas)
    angles = [a for v in lay.voids for a in _angles(v)]
    inradii = [2 * Polygon(v).area / Polygon(v).length for v in lay.voids]
    metal = outer_area - void_area
    kinds = {k: lay.void_kind.count(k) for k in ("full", "edge", "corner", "chamfer", "other")}
    if kinds["other"]:
        lay.warnings.append(f"{kinds['other']} irregular cells (should be 0)")
    # symmetry of the planform about y = 0 (half-model validity)
    from shapely.ops import unary_union
    from shapely.affinity import scale
    fin = Polygon(lay.outer, holes=[v[::-1] for v in lay.voids])
    sym_err = fin.symmetric_difference(scale(fin, -1, 1, origin=(0, 0))).area / max(fin.area, 1e-12)
    out_leg = lambda q: inner_to_outer_leg(q * lay.py / 2, sp.tf, sp.theta)
    lay.metrics = {
        "cells_across_span_J": lay.J,
        "half_rows_M": lay.M,
        "pitch_w_perp_m": lay.w,
        "pitch_along_span_m": lay.py,
        "pitch_along_height_m": lay.pz,
        "h_target_m": sp.h,
        "h_actual_m": lay.h,
        "dh_m": lay.dh,
        "chamfer_outer_leg_bottom_m": out_leg(lay.q_bot),
        "chamfer_outer_leg_top_m": out_leg(lay.q_top),
        "n_cells": len(lay.voids),
        "cell_counts": kinds,
        "min_cell_area_m2": min(void_areas) if void_areas else 0.0,
        "min_cell_angle_deg": min(angles) if angles else 0.0,
        "min_cell_inradius_m": min(inradii) if inradii else 0.0,
        "S_ref_m2": outer_area,
        "open_area_ratio": void_area / outer_area if outer_area else 0.0,
        "metal_area_m2": metal,
        "mass_kg": metal * sp.c * sp.density,
        "c_over_w": sp.c / lay.w,
        "t_over_c": sp.t / sp.c,
        "t_over_w": sp.t / lay.w,
        "solidity_approx_2t_over_w": 2 * sp.t / lay.w,
        "symmetry_error": sym_err,
    }


def fit_table(spec: FinSpec, around: int | None = None, span: int = 4):
    """Nearby cell counts and how far the height has to move for each."""
    J0 = around if around is not None else solve(spec, geometry=False).J
    rows = []
    for J in range(max(1, J0 - span), J0 + span + 1):
        try:
            lay = solve(replace(spec, sizing="cells", n_span=J), geometry=False)
        except ValueError:
            continue
        rows.append({"J": J, "w": lay.w, "py": lay.py, "h": lay.h, "dh": lay.dh, "M": lay.M})
    return rows
