"""Property tests for ``src/cf_lift.py``.

The v3 extractor is a candidate generator (see module docstring + README →
"Honest framing"). These tests pin its structural invariants so future
refactors can't silently break the calibrated production scripts."""
from __future__ import annotations

import pytest

from cf_lift import CF_C_TABLE, cf_lift_v3, estimate_c_per_shot


# Representative ``n`` values: 22-bit headline, 25-bit attempt, plus a small
# tractable case. ``t`` matches what production scripts run with.
N_22BIT = 2_098_699
N_25BIT = 16_773_667
N_SMALL = 79  # 6-bit challenge


def test_output_invariants():
    """Sorted, deduplicated, all in [0, n)."""
    out = cf_lift_v3(12345, t=12, n=N_22BIT)
    assert out == sorted(out)
    assert len(out) == len(set(out))
    assert all(0 <= a < N_22BIT for a in out)


def test_determinism():
    """Same args → same output, byte-for-byte."""
    args = dict(x_meas=8675309, t=12, n=N_22BIT, window=16)
    assert cf_lift_v3(**args) == cf_lift_v3(**args)


def test_direct_rounding_is_included():
    """The ``x_meas * n / 2^t`` rounding is the most likely true peak in an
    ideal run — it must always survive."""
    N = 1 << 12
    x = 123
    a_direct = (x * N_22BIT + N // 2) // N
    out = cf_lift_v3(x, t=12, n=N_22BIT, window=4)
    assert a_direct in out


def test_mirror_symmetry():
    """x and ``N - x`` must produce identical candidate sets when mirror is on.

    QFT peaks come in symmetric pairs, so this is the property the mirror
    branch is supposed to enforce."""
    N = 1 << 10
    x = 137
    a = cf_lift_v3(x, t=10, n=N_SMALL, include_mirror=True)
    b = cf_lift_v3((N - x) % N, t=10, n=N_SMALL, include_mirror=True)
    assert a == b


def test_window_monotonic_in_size():
    """Widening the perturbation window can only add candidates, not remove."""
    base = set(cf_lift_v3(456, t=12, n=N_22BIT, window=4))
    wide = set(cf_lift_v3(456, t=12, n=N_22BIT, window=32))
    assert base.issubset(wide)


def test_bitflips_add_candidates():
    """Disabling bitflips never produces more candidates than enabling them."""
    off = set(cf_lift_v3(789, t=12, n=N_22BIT, include_bitflips=False))
    on = set(cf_lift_v3(789, t=12, n=N_22BIT, include_bitflips=True))
    assert off.issubset(on)


def test_mirror_off_minimal_x_zero():
    """``x_meas=0`` + no mirror is an early-exit special case — returns just [0]."""
    assert cf_lift_v3(0, t=12, n=N_22BIT, include_mirror=False) == [0]


def test_max_candidates_cap():
    """``max_candidates`` caps the size and prefers candidates near direct rounding."""
    N = 1 << 12
    x = 5000
    a_direct = (x * N_22BIT + N // 2) // N
    capped = cf_lift_v3(x, t=12, n=N_22BIT, window=64, max_candidates=20)
    assert len(capped) <= 20
    # The closest-to-direct candidate should survive the trimming.
    assert min(capped, key=lambda a: abs(a - a_direct)) == min(
        cf_lift_v3(x, t=12, n=N_22BIT, window=64),
        key=lambda a: abs(a - a_direct),
    )


def test_small_n_still_works():
    """Sanity at challenge sizes we actually verify on simulator."""
    out = cf_lift_v3(7, t=4, n=N_SMALL)
    assert all(0 <= a < N_SMALL for a in out)
    assert len(out) > 0


@pytest.mark.parametrize("window", sorted(CF_C_TABLE.keys()))
def test_calibrated_windows_run(window):
    """Every entry in the calibration table must execute without crashing —
    if someone adds a new ``window`` to ``CF_C_TABLE`` they're also asserting
    it's runnable."""
    out = cf_lift_v3(42424, t=12, n=N_22BIT, window=window)
    assert len(out) > 0


def test_estimate_c_per_shot_uses_table_when_calibrated():
    for w, c in CF_C_TABLE.items():
        assert estimate_c_per_shot(w) == c


def test_estimate_c_per_shot_falls_back_for_uncalibrated():
    """Uncalibrated windows still return *something* finite — preflight should
    not crash on a fresh window value."""
    assert estimate_c_per_shot(99) > 0


def test_extract_rejects_unknown_cf_version():
    """Typo'd ``cf_version`` should fail loudly rather than fall through to v2."""
    from challenges import get_challenge
    from ecc import EllipticCurve
    from shor_ecdlp import RippleCarryOracle, ShorECDLPSolver, SubgroupIndexer

    c = get_challenge(4)
    curve = EllipticCurve(0, 7, c.p)
    G, Q = curve.point(*c.G), curve.point(*c.Q)
    solver = ShorECDLPSolver(
        curve, G, Q, c.n,
        oracle=RippleCarryOracle(SubgroupIndexer(curve, G, c.n)),
        num_counting=3,
    )
    with pytest.raises(ValueError, match="cf_version"):
        solver.extract({}, cf_version="v4")
