"""The guarantee: whatever the user picks, the lattice meets the frame cleanly."""
import itertools
import math

import pytest

from gridfin.lattice import FinSpec, solve, fit_table, inner_to_outer_leg

SWEEP = list(itertools.product(
    [3, 4, 5, 7, 8, 10, 11, 13, 16, 20],      # cells across span
    [0.006, 0.020, 0.040],                     # web t
    [0.020, 0.050, 0.100],                     # frame tf
    ["square", "chamfer"],
    [30.0, 45.0, 52.5],                        # lattice angle
))


@pytest.mark.parametrize("J,t,tf,corner,theta", SWEEP)
def test_always_clean(J, t, tf, corner, theta):
    spec = FinSpec(n_span=J, t=t, tf=tf, corner=corner, theta=theta, chamfer=0.35)
    lay = solve(spec)
    m = lay.metrics
    # 1. no irregular / sliver cells: every cell is a full rhombus or a clean triangle
    assert m["cell_counts"]["other"] == 0
    # 2. no angle smaller than the lattice geometry itself allows
    assert m["min_cell_angle_deg"] >= min(theta, 90 - theta) - 1e-6
    # 3. exact mirror symmetry about the mid-span plane (half model valid)
    assert m["symmetry_error"] < 1e-9
    # 4. span exact, height within half a snap step of the target
    assert math.isclose(max(y for y, _ in lay.outer) * 2, spec.b, rel_tol=1e-9)
    step = lay.pz if (corner == "chamfer" or spec.tb_mirror) else lay.pz / 2
    assert abs(lay.dh) <= step / 2 + 1e-9
    # 5. chamfered: all four corners identical
    if corner == "chamfer":
        assert lay.q_top == lay.q_bot


def test_edge_cells_are_exact_halves():
    lay = solve(FinSpec(corner="square"))
    k = lay.metrics["cell_counts"]
    assert k["edge"] > 0 and k["other"] == 0 and k["chamfer"] == 0


def test_chamfer_lies_on_web_line():
    """Inner chamfer face must coincide with a lattice web centreline."""
    lay = solve(FinSpec(corner="chamfer"))
    th = math.radians(lay.spec.theta)
    s, c = math.sin(th), math.cos(th)
    # top-right chamfer: the inner edge from (yb-L, zb) to (yb, zb-H) is a v-line
    yb, zb = lay.b_i / 2, lay.h_i / 2
    v = s * (yb - lay.q_top * lay.py / 2) + c * zb
    assert abs(((v - lay.phi) / lay.w) - round((v - lay.phi) / lay.w)) < 1e-9


def test_pitch_mode_snaps_to_nearest_cell_count():
    lay = solve(FinSpec(sizing="pitch", pitch=0.38))
    assert lay.J == round(lay.b_i * math.sin(math.radians(45)) / 0.38)


def test_chamfer_target_tracks():
    small = solve(FinSpec(chamfer=0.2)).metrics["chamfer_outer_leg_top_m"]
    big = solve(FinSpec(chamfer=0.9)).metrics["chamfer_outer_leg_top_m"]
    assert big > small > 0


def test_fit_table_contains_current():
    rows = fit_table(FinSpec(n_span=10))
    assert any(r["J"] == 10 for r in rows)


def test_rejects_impossible():
    with pytest.raises(ValueError):
        solve(FinSpec(t=0.5, n_span=10))
    with pytest.raises(ValueError):
        solve(FinSpec(tf=3.0))


def test_outer_leg_formula_matches_geometry():
    lay = solve(FinSpec(corner="chamfer", tf=0.08))
    hb = lay.spec.b / 2
    top = max(z for _, z in lay.outer)
    y_top_right = max(y for y, z in lay.outer if abs(z - top) < 1e-9)
    assert math.isclose(hb - y_top_right,
                        inner_to_outer_leg(lay.q_top * lay.py / 2, lay.spec.tf, lay.spec.theta),
                        rel_tol=1e-9)
