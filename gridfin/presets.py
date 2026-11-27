"""Stock thickness lists, materials and saved designs."""
from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from .lattice import FinSpec

PKG_DIR = Path(__file__).resolve().parent
PRESETS_FILE = PKG_DIR / "presets.json"
DESIGNS_DIR = PKG_DIR.parent / "designs"
INCH = 0.0254


def _parse_inch(s: str) -> float:
    """'1-1/2' -> 1.5, '3/16' -> 0.1875, '2' -> 2."""
    s = s.strip()
    if "-" in s:
        whole, frac = s.split("-", 1)
        return float(whole) + float(Fraction(frac))
    return float(Fraction(s))


def load() -> dict:
    with open(PRESETS_FILE) as f:
        return json.load(f)


def thickness_options(p: dict | None = None):
    """[(label, metres)] - metric first, then imperial."""
    p = p or load()
    out = [(f"{mm:g} mm", mm / 1000) for mm in p.get("thickness_metric_mm", [])]
    for s in p.get("thickness_imperial_in", []):
        m = _parse_inch(s) * INCH
        out.append((f'{s}" ({m*1000:.2f} mm)', m))
    return out


def materials(p: dict | None = None) -> dict:
    p = p or load()
    return dict(p.get("materials", {"Steel": 7850}))


def designs(p: dict | None = None) -> dict:
    """{name: FinSpec} built-in presets followed by saved designs."""
    p = p or load()
    out = {}
    for name, d in p.get("designs", {}).items():
        out[name] = FinSpec.from_dict({**d, "name": name.split(" (")[0].replace(" ", "_")})
    if DESIGNS_DIR.is_dir():
        for f in sorted(DESIGNS_DIR.glob("*.json")):
            try:
                out[f"saved: {f.stem}"] = load_design(f)
            except (ValueError, KeyError, json.JSONDecodeError):
                continue
    return out


def load_design(path) -> FinSpec:
    with open(path) as f:
        d = json.load(f)
    return FinSpec.from_dict(d.get("params", d))   # accepts export JSON too


def save_design(spec: FinSpec, path=None) -> Path:
    path = Path(path) if path else DESIGNS_DIR / f"{spec.name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(spec.to_dict(), f, indent=2)
    return path
