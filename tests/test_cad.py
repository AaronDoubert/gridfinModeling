import json

import pytest

cq = pytest.importorskip("cadquery")

from gridfin.lattice import FinSpec, solve
from gridfin.cad import export, fin_solid


@pytest.mark.parametrize("kw", [{}, {"corner": "square", "n_span": 7}, {"theta": 40, "n_span": 13}])
def test_fin_solid_valid_and_matches_2d(kw):
    lay = solve(FinSpec(**kw))
    s = fin_solid(lay)
    assert s.isValid()
    assert s.Volume() == pytest.approx(lay.metrics["metal_area_m2"] * lay.spec.c, rel=1e-6)


def test_export_writes_everything(tmp_path):
    info = export(FinSpec(name="t", n_span=6), tmp_path)
    assert info["fin_valid"] and info["fluid_valid"]
    for f in ("t_fin.step", "t_fluid.step", "t_fluid_half.step", "t_planform.dxf", "t.json"):
        assert (tmp_path / f).stat().st_size > 0
    assert json.loads((tmp_path / "t.json").read_text())["solved"]["J"] == 6
