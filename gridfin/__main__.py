"""
python -m gridfin                       open the GUI
python -m gridfin preview [design.json] -o preview.png
python -m gridfin export  [design.json] --out out/ [--no-fluid] [--no-half] [--no-dxf]
python -m gridfin sweep   [design.json] --vary n_span=8,10,12 --vary t=0.010,0.020 --out out/
python -m gridfin fits    [design.json]  # table of nearby cell counts / height snap

Any FinSpec field can also be overridden on the command line:  --set t=0.012 --set corner=square
"""
import argparse
import itertools
import json
import sys
from dataclasses import fields, replace

from .lattice import FinSpec, solve, fit_table
from . import presets

_TYPES = {f.name: f.type for f in fields(FinSpec)}


def _coerce(key, val: str):
    typ = _TYPES.get(key)
    if typ is None:
        raise SystemExit(f"unknown parameter '{key}'. Valid: {', '.join(_TYPES)}")
    if typ in ("float", float):
        return float(val)
    if typ in ("int", int):
        return int(val)
    if typ in ("bool", bool):
        return val.lower() in ("1", "true", "yes", "on")
    return val


def _spec(args) -> FinSpec:
    spec = presets.load_design(args.design) if args.design else FinSpec()
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        spec = replace(spec, **{k: _coerce(k, v)})
    return spec


def main(argv=None):
    ap = argparse.ArgumentParser(prog="gridfin", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("gui")
    for name in ("preview", "export", "sweep", "fits"):
        p = sub.add_parser(name)
        p.add_argument("design", nargs="?", help="design JSON (default: built-in baseline)")
        p.add_argument("--set", action="append", metavar="KEY=VAL", help="override a parameter")
        if name == "preview":
            p.add_argument("-o", "--output", default="preview.png")
            p.add_argument("--centerlines", action="store_true")
        if name in ("export", "sweep"):
            p.add_argument("--out", default="out")
            p.add_argument("--no-fin", action="store_true")
            p.add_argument("--no-fluid", action="store_true")
            p.add_argument("--no-half", action="store_true")
            p.add_argument("--no-dxf", action="store_true")
        if name == "sweep":
            p.add_argument("--vary", action="append", required=True, metavar="KEY=V1,V2,...")
    a = ap.parse_args(argv)

    if a.cmd in (None, "gui"):
        from .gui import main as gui_main
        return gui_main()

    spec = _spec(a)
    if a.cmd == "preview":
        from .plot import save_png
        lay = solve(spec)
        save_png(lay, a.output, centerlines=a.centerlines)
        print(f"wrote {a.output}")
        print(json.dumps(lay.metrics, indent=2))
        for w in lay.warnings:
            print("WARNING:", w)
        return 0

    if a.cmd == "fits":
        print(f"{'cells':>5} {'w [mm]':>8} {'py [mm]':>8} {'h [m]':>7} {'dh [mm]':>8}")
        for r in fit_table(spec, span=6):
            print(f"{r['J']:>5} {r['w']*1e3:>8.1f} {r['py']*1e3:>8.1f} {r['h']:>7.3f} {r['dh']*1e3:>+8.0f}")
        return 0

    from .cad import export
    opts = dict(fin=not a.no_fin, fluid=not a.no_fluid, half=not a.no_half, dxf=not a.no_dxf)
    if a.cmd == "export":
        info = export(spec, a.out, progress=lambda m: print("  ", m), **opts)
        print(json.dumps({k: info[k] for k in ("solved", "files", "fin_valid", "build_s")}, indent=2))
        return 0

    # sweep: full factorial over --vary lists
    grid = {}
    for kv in a.vary:
        k, vs = kv.split("=", 1)
        grid[k] = [_coerce(k, v) for v in vs.split(",")]
    for vals in itertools.product(*grid.values()):
        tag = "_".join(f"{k}{v:g}" if isinstance(v, (int, float)) else f"{k}{v}"
                       for k, v in zip(grid, vals))
        s = replace(spec, name=f"{spec.name}_{tag}", **dict(zip(grid, vals)))
        info = export(s, a.out, **opts)
        d = info["derived"]
        print(f"{s.name:40s} J={d['cells_across_span_J']:>3} w={d['pitch_w_perp_m']*1e3:6.1f}mm "
              f"h={d['h_actual_m']:.3f}m c/w={d['c_over_w']:.3f} valid={info['fin_valid']} {info['build_s']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
