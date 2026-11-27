"""2D planform preview, shared by the GUI and `python -m gridfin preview`."""
from __future__ import annotations

from matplotlib.patches import Polygon as MplPolygon
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch

from .lattice import Layout

METAL = "#8a96a3"
EDGE = "#2b3440"
VOID = "#ffffff"
BAD = "#d62728"           # irregular cell - should never appear
KIND_COLOR = {"edge": "#f2c88a", "corner": "#e08a3c", "chamfer": "#b5d99c", "other": BAD}
AXIS = "#c0392b"
CL = "#3d7bd9"


def _ring_path(rings):
    verts, codes = [], []
    for r in rings:
        verts += list(r) + [r[0]]
        codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(r) - 1) + [MplPath.CLOSEPOLY]
    return MplPath(verts, codes)


def draw(ax, lay: Layout, centerlines=False, dims=True, highlight=True, dark=False):
    ax.clear()
    bg = "#1e2227" if dark else "#ffffff"
    fg = "#d8dee6" if dark else "#222"
    ax.set_facecolor(bg)
    ax.figure.set_facecolor(bg)
    # fin = outer ring (CCW) with voids (CW) as holes - nonzero winding fill
    path = _ring_path([lay.outer] + [v for v in lay.voids])
    ax.add_patch(PathPatch(path, facecolor=METAL, edgecolor=EDGE, lw=0.6))
    if highlight:
        for v, kind in zip(lay.voids, lay.void_kind):
            if kind != "full":
                ax.add_patch(MplPolygon(v, closed=True, facecolor=KIND_COLOR.get(kind, BAD),
                                        alpha=0.6, lw=0))
    ax.add_patch(MplPolygon(lay.inner, closed=True, fill=False, edgecolor=EDGE, lw=0.5, ls="--"))
    if centerlines:
        for seg in lay.centerlines:
            xs, ys = zip(*seg)
            ax.plot(xs, ys, color=CL, lw=0.5, alpha=0.7)
    sp = lay.spec
    hb, hh = sp.b / 2, lay.h / 2
    # hinge axis (y) and mid-span symmetry plane
    ax.plot([-hb * 1.12, hb * 1.12], [sp.z_h, sp.z_h], color=AXIS, lw=0.9, ls="-.")
    ax.text(hb * 1.13, sp.z_h, "hinge (y)", color=AXIS, fontsize=8, va="center")
    ax.plot([0, 0], [-hh * 1.08, hh * 1.08], color=fg, lw=0.6, ls=":", alpha=0.6)
    if dims:
        off = 0.10 * max(sp.b, lay.h)
        ax.annotate("", (-hb, -hh - off), (hb, -hh - off),
                    arrowprops=dict(arrowstyle="<->", color=fg, lw=0.8))
        ax.text(0, -hh - off * 1.35, f"b = {sp.b:.3f} m   ({lay.J} cells, py = {lay.py*1000:.1f} mm)",
                ha="center", va="top", fontsize=8, color=fg)
        ax.annotate("", (-hb - off, -hh), (-hb - off, hh),
                    arrowprops=dict(arrowstyle="<->", color=fg, lw=0.8))
        ax.text(-hb - off * 1.3, 0, f"h = {lay.h:.3f} m  (target {sp.h:.3f}, {lay.dh*1000:+.0f} mm)",
                ha="center", va="center", fontsize=8, color=fg, rotation=90)
    m = (0.18 if dims else 0.06) * max(sp.b, lay.h)   # room for the dimension arrows
    ax.set_xlim(-hb - m, hb + m)
    ax.set_ylim(-hh - m, hh + m)
    ax.set_aspect("equal")
    ax.set_xlabel("y  (span / hinge axis)  [m]", color=fg, fontsize=8)
    ax.set_ylabel("z  [m]", color=fg, fontsize=8)
    ax.tick_params(colors=fg, labelsize=7)
    for s in ax.spines.values():
        s.set_color(fg)
        s.set_alpha(0.3)
    ax.set_title(f"{sp.name}  -  flow along +x (into page)", color=fg, fontsize=9)


def save_png(lay: Layout, path, **kw):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(8, 7), dpi=130)
    draw(ax, lay, **kw)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
