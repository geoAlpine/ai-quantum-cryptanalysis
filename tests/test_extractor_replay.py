"""Regression test for the d-extractor against every saved IBM-hardware
counts file. Costs zero QPU — pure post-processing over previously-
collected shots.

This is the pytest sibling of ``scripts/replay_benchmark.py``. Run after
touching anything in the extractor / oracle / indexer paths to make sure
the headline results still recover.

The 22-bit case takes ~30 seconds on a laptop; mark it ``slow`` so fast
iterations (``pytest -m 'not slow'``) skip it."""
from __future__ import annotations

import glob
import json
import os

import pytest

from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)


REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
RESULTS_DIR = os.path.join(REPO_ROOT, "results")


def _detect_oracle(bs_len: int, bits: int) -> str:
    """Pick oracle kind such that ``2t + pt_w`` equals the bitstring length."""
    n = get_challenge(bits).n
    m = max(1, (n - 1).bit_length())
    for kind, pt_w in (("ripple", m + 1), ("dense", m)):
        rem = bs_len - pt_w
        if rem > 0 and rem % 2 == 0:
            return kind
    raise ValueError(f"no oracle matches bs_len={bs_len} for bits={bits}")


def _infer_t(bs_len: int, bits: int, oracle_kind: str) -> int:
    n = get_challenge(bits).n
    m = max(1, (n - 1).bit_length())
    pt_w = m if oracle_kind == "dense" else m + 1
    return (bs_len - pt_w) // 2


def _discover_counts_files() -> list[str]:
    return sorted(glob.glob(os.path.join(RESULTS_DIR, "_ibm_*_counts.json")))


def _id_for(path: str) -> str:
    return os.path.basename(path).replace("_ibm_", "").replace("_counts.json", "")


_FILES = _discover_counts_files()


def _is_slow(path: str) -> bool:
    """22-bit extract takes ~30s; mark it slow so fast runs can skip it."""
    return "_22bit_" in path


def _pytest_param(path: str):
    marks = [pytest.mark.slow] if _is_slow(path) else []
    return pytest.param(path, id=_id_for(path), marks=marks)


@pytest.mark.skipif(not _FILES, reason="no saved IBM counts files found")
@pytest.mark.parametrize("counts_path", [_pytest_param(p) for p in _FILES])
def test_replay_recovers_expected_d(counts_path):
    """Every saved IBM run must still recover its expected ``d`` via the
    current ``ShorECDLPSolver.extract`` implementation."""
    blob = json.load(open(counts_path))
    counts = blob["counts"]
    meta = blob["meta"]
    bits = meta["bits"]
    expected_d = meta["expected_d"]

    bs_len = len(next(iter(counts)))
    oracle_kind = _detect_oracle(bs_len, bits)
    t = meta.get("t") or _infer_t(bs_len, bits, oracle_kind)

    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)
    lazy = c.n >= 5_000_000
    ind = SubgroupIndexer(curve, G, c.n, lazy=lazy)
    oracle = (
        DenseUnitaryOracle(ind) if oracle_kind == "dense" else RippleCarryOracle(ind)
    )
    solver = ShorECDLPSolver(
        curve, G, Q, c.n, oracle=oracle, num_counting=t, lazy=lazy
    )

    recovered = solver.extract(counts, cf_window=16, cf_version="v3")
    assert recovered == expected_d, (
        f"regression: {os.path.basename(counts_path)} expected d={expected_d}, "
        f"got {recovered}"
    )
