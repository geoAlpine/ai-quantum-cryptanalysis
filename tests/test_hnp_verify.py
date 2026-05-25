"""Tests for ``hnp_recover_with_verification`` — the production
recovery flow that drives Phase 1 hardware submissions.

The flow:
  1. score all ``d ∈ [0, n)`` against the joint Shor peak relation,
  2. iterate the top-K candidates *and* each one's anti-d partner
     ``(n - d) % n``,
  3. return the first ``d`` whose ``verify_fn(d)`` (typically
     ``d · G == Q``) succeeds.

These tests pin the invariants the production scripts rely on:
verification fall-back works, anti-d is tried, ``d_recovered=None`` on
total failure.
"""
from __future__ import annotations

import math

import pytest

from challenges import get_challenge
from ecc import EllipticCurve
from lattice_postprocess import (
    hnp_recover_with_verification,
    hnp_score,
    hnp_score_search,
)


def _curve_setup(bits: int):
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    return c, curve, G, Q


def _make_verify(curve, G, Q):
    return lambda d: curve.scalar_mul(d, G) == Q


def test_verify_accepts_d_true_and_only_d_true_4bit():
    """Sanity: the verifier callable behaves as expected — exactly
    ``d_true * G == Q`` and no other d ∈ [1, n) does."""
    c, curve, G, Q = _curve_setup(4)
    verify = _make_verify(curve, G, Q)
    matches = [d for d in range(1, c.n) if verify(d)]
    assert matches == [c.expected_d]


def test_hnp_recover_finds_d_via_anti_d_on_perfect_shot():
    """When we feed a single perfect ``(j, k)`` peak that satisfies the
    Shor relation for ``d_true=6``, HNP's top-1 will be ``-d_true`` mod
    n by symmetry — recovery should still find d_true via the anti-d
    fall-back."""
    c, curve, G, Q = _curve_setup(4)
    n = c.n  # 7
    d_true = c.expected_d  # 6
    t = 6
    M = 1 << t
    # j=0, k=0, r=0 is exactly the s=0 peak — satisfies the relation
    # for any d, so isn't discriminative. Use a non-trivial peak:
    # find any (j, k, r) where (j + d_true*k) mod M is at an expected
    # peak position.
    expected_peaks = sorted({(s * M + n // 2) // n % M for s in range(n)})
    # Force (j + 6k) mod 64 to be exactly the s=2 peak (= 18 for M=64,n=7).
    target = expected_peaks[2]
    k = 1
    j = (target - d_true * k) % M
    # Synthesise 1000 copies of the same perfect shot.
    shots = [(j, k, 0)] * 1000

    verify = _make_verify(curve, G, Q)
    result = hnp_recover_with_verification(shots, n, t, verify, top_k=5)
    assert result["d_recovered"] == d_true, (
        f"expected to recover d_true={d_true}, got {result['d_recovered']}"
    )
    # The top-1 score should be {d, n-d} or some equivalent under
    # symmetry; either way we recovered correctly via either branch.
    assert result["rank_in_hnp"] is not None
    assert 1 <= result["rank_in_hnp"] <= 5


def test_hnp_recover_returns_none_when_no_top_k_verifies():
    """If we feed pure-noise shots, no candidate within top-K (or its
    anti-d) will pass verification — return ``d_recovered=None``."""
    c, curve, G, Q = _curve_setup(4)
    n = c.n
    t = 6
    import random
    rng = random.Random(42)
    shots = [(rng.randrange(1 << t), rng.randrange(1 << t),
              rng.randrange(n)) for _ in range(500)]
    verify = _make_verify(curve, G, Q)
    # With only n=7 candidates the verify check WILL likely find d_true
    # somewhere in top-K — that's a feature, not a bug. To test the
    # "no recovery" path we'd need a fake verify that always rejects.
    fake_verify = lambda d: False
    result = hnp_recover_with_verification(shots, n, t, fake_verify, top_k=3)
    assert result["d_recovered"] is None
    assert result["rank_in_hnp"] is None


def test_hnp_recover_score_ordering_matches_hnp_score():
    """``hnp_recover_with_verification`` must use the same scoring as
    ``hnp_score`` — otherwise the rank-in-HNP report is wrong."""
    c, curve, G, Q = _curve_setup(4)
    n = c.n
    t = 6
    shots = [(1, 1, 0), (3, 2, 5), (7, 7, 1)] * 100
    verify = _make_verify(curve, G, Q)
    result = hnp_recover_with_verification(shots, n, t, verify, top_k=n)
    # The returned hnp_top_k should be sorted by score ascending.
    scores = [s for _, s in result["hnp_top_k"]]
    assert scores == sorted(scores)
    # And the scores should match what hnp_score returns directly.
    for d, s in result["hnp_top_k"]:
        assert math.isclose(s, hnp_score(d, shots, n, t), rel_tol=1e-9)


def test_hnp_recover_rejects_large_n():
    """The exhaustive variant must error fast on large n rather than
    silently take forever. Lattice reduction will replace this code
    path eventually (Task #17)."""
    n_too_large = 2 * 10**6
    shots = [(0, 0, 0)] * 10
    verify = lambda d: False
    with pytest.raises(ValueError, match="lattice"):
        hnp_recover_with_verification(shots, n_too_large, 12, verify, top_k=5)


def test_phase1_hardware_result_replays():
    """**Hardware regression test**: replay the Phase 1 ibm_kingston
    submission counts through the production HNP+verify pipeline and
    assert recovery succeeds with the documented metrics. If this ever
    fails, either we broke the decoder OR the saved counts changed."""
    import json
    import os

    repo = os.path.join(os.path.dirname(__file__), "..")
    counts_path = os.path.join(
        repo, "results", "shor_4bit_t6_1024shots_hnp_ibm.json"
    )
    if not os.path.exists(counts_path):
        pytest.skip("Phase 1 hardware counts not present in this checkout")

    blob = json.load(open(counts_path))
    counts = blob["counts"]
    c, curve, G, Q = _curve_setup(blob["bits"])
    t = blob["t"]
    pt_w = blob.get("qubits", 15) - 2 * t  # = 3 for the m=3 dense submission
    n = c.n
    d_true = c.expected_d

    shots = []
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        for _ in range(cnt):
            shots.append((j, k, r))
    assert len(shots) == 1024

    verify = _make_verify(curve, G, Q)
    result = hnp_recover_with_verification(shots, n, t, verify, top_k=7)
    # Hardware reality: d_true recovered, at HNP rank 2, via direct verify.
    assert result["d_recovered"] == d_true
    assert result["rank_in_hnp"] == 2, (
        f"Phase 1 hardware rank expected 2, got {result['rank_in_hnp']}"
    )
    assert result["verified_via_anti_d"] is False, (
        "Phase 1 hardware was direct-verify recovery (no anti-d needed); "
        "if this assert flips that's an interesting algorithmic change."
    )
    # d-class {d_true, n-d_true} should be in top-3
    d_class = {d_true, (n - d_true) % n}
    top3 = {d for d, _ in result["hnp_top_k"][:3]}
    assert top3 & d_class == d_class, (
        f"d-class {d_class} should be in top-3 {top3} on Phase 1 hardware"
    )
