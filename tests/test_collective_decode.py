"""Regression tests for ``scripts/collective_decode.py``.

These tests *pin the honest framing*: the saved 19-bit and 22-bit IBM
runs are statistically indistinguishable from uniform noise under the
no-side-channel collective vote. If a future change to the extractor
or candidate generator happens to make d_true rank #1 on these
datasets, that would mean *either* a real signal-extraction breakthrough
*or* (more likely) we re-introduced a verification-filter shortcut by
accident — in which case this test will scream so we look at it before
shipping anything to PR.

The 22-bit case takes ~70s; mark slow.
"""
from __future__ import annotations

import glob
import json
import math
import os

import numpy as np
import pytest

from cf_lift import cf_lift_v3
from challenges import get_challenge


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
RESULTS_DIR = os.path.join(REPO_ROOT, "results")


def _collective_votes(counts: dict[str, int],
                       bits: int, t: int, pt_w: int, window: int) -> dict:
    """Collective vote tally — the no-side-channel variant of ``extract``."""
    c = get_challenge(bits)
    n = c.n
    d_true = c.expected_d
    votes = np.zeros(n, dtype=np.int64)
    cf_cache: dict[int, list[int]] = {}

    def cf(x: int) -> list[int]:
        if x not in cf_cache:
            cf_cache[x] = cf_lift_v3(x, t, n, window=window)
        return cf_cache[x]

    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2 * t], 2) % n
        r = int(bs[2 * t:], 2) % n
        a_list = cf(j)
        b_list = cf(k)
        b_invs = []
        for b in b_list:
            if b == 0 or math.gcd(b, n) != 1:
                continue
            b_invs.append((b, pow(b, -1, n)))
        d_set: set[int] = set()
        for a in a_list:
            r_minus_a = (r - a) % n
            for _, b_inv in b_invs:
                d_set.add((r_minus_a * b_inv) % n)
        for d in d_set:
            votes[d] += cnt

    total = int(votes.sum())
    e_uniform = total / n
    std_uniform = math.sqrt(e_uniform * max(0, 1 - 1 / n))
    v_d_true = int(votes[d_true])
    rank = int((votes > v_d_true).sum() + 1)
    z = (v_d_true - e_uniform) / std_uniform if std_uniform else 0.0
    return {
        "n": n,
        "d_true": d_true,
        "total_votes": total,
        "e_uniform": e_uniform,
        "votes_d_true": v_d_true,
        "ratio": v_d_true / e_uniform if e_uniform else 0.0,
        "z_score": z,
        "rank": rank,
    }


@pytest.mark.slow
def test_19bit_t12_no_collective_signal():
    """19-bit IBM run: d_true must NOT be argmax. Documents that this
    recovery lives in the verification-filter regime — see project memory
    `project_collective_vote_findings.md`. ~3 minutes; pytest -m 'not slow'
    skips it."""
    path = os.path.join(RESULTS_DIR, "_ibm_19bit_t12_counts.json")
    if not os.path.exists(path):
        pytest.skip("19-bit counts file not available")
    blob = json.load(open(path))
    stats = _collective_votes(blob["counts"], bits=19,
                                t=blob["meta"]["t"], pt_w=20, window=16)
    # Honest framing: ratio ≈ 1.0, |z| within ~2σ of zero, rank deep in
    # the middle of [1, n].
    assert 0.8 < stats["ratio"] < 1.3, f"unexpected ratio {stats['ratio']:.3f}"
    assert abs(stats["z_score"]) < 3.0, f"unexpected z {stats['z_score']:+.2f}σ"
    assert stats["rank"] > stats["n"] // 100, (
        f"d_true ranked #{stats['rank']} of {stats['n']:,} — that would be "
        f"surprising collective signal! Re-investigate before shipping."
    )


@pytest.mark.slow
def test_22bit_t12_no_collective_signal():
    """22-bit IBM run: same expectation as 19-bit — verification-filter
    regime, d_true near uniform mean. ~70 seconds; pytest -m 'not slow'
    skips it."""
    path = os.path.join(RESULTS_DIR, "_ibm_22bit_t12_counts.json")
    if not os.path.exists(path):
        pytest.skip("22-bit counts file not available")
    blob = json.load(open(path))
    stats = _collective_votes(blob["counts"], bits=22,
                                t=blob["meta"]["t"], pt_w=23, window=16)
    assert 0.8 < stats["ratio"] < 1.3, f"unexpected ratio {stats['ratio']:.3f}"
    assert abs(stats["z_score"]) < 3.0, f"unexpected z {stats['z_score']:+.2f}σ"
    assert stats["rank"] > stats["n"] // 100, (
        f"d_true ranked #{stats['rank']} of {stats['n']:,} — that would be "
        f"surprising collective signal! Re-investigate before shipping."
    )


@pytest.mark.slow
def test_collective_decode_script_runs():
    """Smoke test the standalone driver — should not crash on the
    smallest dataset. Marked slow because subprocess + 500-shot vote
    accumulation runs ~2 minutes; the test value is in catching
    regressions in CLI argument parsing and report formatting."""
    import subprocess
    paths = glob.glob(os.path.join(RESULTS_DIR, "_ibm_19bit_t12_counts.json"))
    if not paths:
        pytest.skip("no 19-bit counts file to feed the driver")
    script = os.path.join(REPO_ROOT, "scripts", "collective_decode.py")
    result = subprocess.run(
        ["python", script, "--counts", paths[0], "--bits", "19",
         "--window", "8", "--sample", "500"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "d_true" in result.stdout
    assert "ratio to uniform" in result.stdout
