"""Tests for ``hnp_recover_lattice`` — the q-ary Boneh-Venkatesan / Ekerå
lattice replacement for the exhaustive ``hnp_score_search`` ceiling.

Designed against ``docs/lattice_hnp_design.md``. The validation ladder is:

  Step 1 (this file)     noiseless 4-bit ideal shots, n=7 → d=6
  Step 2 (this file)     noiseless 6-bit ideal shots, n=31 → d=18
  Step 3 (separate run)  ibm_kingston noise sim on small n
  Step 4 (separate run)  Phase 1 + reps real-hardware data
  Step 5 (separate run)  19-bit IBM data (the make-or-break)

Step 1 + 2 here pin the algorithm; the harder steps run as scripts.
"""
from __future__ import annotations

import pytest

from lattice_postprocess import HNPResult, hnp_recover_lattice


def _synthesise_ideal_shots(
    n: int, t: int, d_true: int, num_shots: int
) -> list[tuple[int, int, int]]:
    """Generate `num_shots` noiseless Shor peaks for given (n, t, d).

    For each k, pick a Shor peak index ``s`` and set
    ``j = (round(s·M/n) - d·k) mod M`` so the relation
    ``n·(j + d·k) ≡ s·M (mod n·M)`` holds exactly.
    """
    M = 1 << t
    peaks = [(s * M + n // 2) // n % M for s in range(n)]
    shots = []
    for k_idx in range(num_shots):
        k = (k_idx + 1) % M  # avoid k=0 (trivial / degenerate)
        s = k_idx % n
        j = (peaks[s] - d_true * k) % M
        shots.append((j, k, 0))
    return shots


def test_lattice_recovers_d_4bit_noiseless():
    """Step 1: noiseless 4-bit ideal shots, n=7, d_true=6.

    With 25 perfect shots the lattice should land on the d-class
    ``{6, 1}`` (d_true or its modular negation -d mod n).
    """
    n = 7
    t = 6
    d_true = 6
    shots = _synthesise_ideal_shots(n, t, d_true, num_shots=25)
    result = hnp_recover_lattice(shots, n, t, max_shots=25, block_size=10)
    d_class = {d_true, (n - d_true) % n}
    assert result.d_candidate in d_class, (
        f"expected d_candidate in d-class {d_class}, got {result.d_candidate} "
        f"(short ||v||={result.short_vector_norm:.3e}, "
        f"confidence={result.confidence:.3f})"
    )


def test_lattice_recovers_d_6bit_noiseless():
    """Step 2: noiseless 6-bit ideal shots, n=31, d_true=18.

    Scale-up test — confirms the construction works at larger n. Uses
    40 shots since the design doc estimates N ≈ 2m to 4m suffices.
    """
    n = 31
    t = 8
    d_true = 18
    shots = _synthesise_ideal_shots(n, t, d_true, num_shots=40)
    result = hnp_recover_lattice(shots, n, t, max_shots=40, block_size=10)
    d_class = {d_true, (n - d_true) % n}
    assert result.d_candidate in d_class, (
        f"expected d_candidate in d-class {d_class}, got {result.d_candidate} "
        f"(short ||v||={result.short_vector_norm:.3e})"
    )


def test_lattice_returns_HNPResult_shape():
    """Smoke test: return type and fields are correct."""
    shots = _synthesise_ideal_shots(7, 6, 6, num_shots=15)
    result = hnp_recover_lattice(shots, 7, 6, max_shots=15, block_size=2)
    assert isinstance(result, HNPResult)
    assert 0 <= result.d_candidate < 7
    assert result.used_shots == 15
    assert result.short_vector_norm >= 0


def test_lattice_handles_empty_shots():
    """Edge case: empty shot list returns zero result, doesn't crash."""
    result = hnp_recover_lattice([], 7, 6, max_shots=10)
    assert result.used_shots == 0
    assert result.d_candidate == 0
