"""
Statistical analysis to verify genuine quantum advantage.

Core idea: if quantum circuit output is indistinguishable from /dev/urandom,
the attack has no quantum advantage. We must statistically falsify this null hypothesis.
"""

import os
import numpy as np
from scipy import stats
from typing import Optional
import time


def random_baseline_counts(n_bits: int, shots: int) -> dict[str, int]:
    """/dev/urandom baseline: what pure classical noise looks like."""
    counts: dict[str, int] = {}
    rng = np.random.default_rng(int.from_bytes(os.urandom(8), "big"))
    samples = rng.integers(0, 2**n_bits, size=shots)
    for s in samples:
        key = format(s, f"0{n_bits}b")
        counts[key] = counts.get(key, 0) + 1
    return counts


def counts_to_distribution(counts: dict[str, int], n_bits: int) -> np.ndarray:
    """Convert counts dict to probability array of length 2^n_bits."""
    total = sum(counts.values())
    dist = np.zeros(2**n_bits)
    for bitstring, cnt in counts.items():
        idx = int(bitstring, 2)
        dist[idx] = cnt / total
    return dist


def chi_squared_vs_uniform(counts: dict[str, int], n_bits: int) -> tuple[float, float]:
    """
    Chi-squared test: H0 = output is uniform (indistinguishable from noise).
    Returns (chi2_stat, p_value). Low p_value => reject H0 => quantum signal present.
    """
    n_states = 2**n_bits
    total = sum(counts.values())
    expected = total / n_states

    observed = np.zeros(n_states)
    for bitstring, cnt in counts.items():
        observed[int(bitstring, 2)] = cnt

    chi2, p = stats.chisquare(observed, f_exp=np.full(n_states, expected))
    return float(chi2), float(p)


def kl_divergence(p: np.ndarray, q: np.ndarray, epsilon: float = 1e-10) -> float:
    """KL divergence D(p || q). High value = p differs from q (uniform noise)."""
    p = np.clip(p, epsilon, 1.0)
    q = np.clip(q, epsilon, 1.0)
    p = p / p.sum()
    q = q / q.sum()
    return float(np.sum(p * np.log(p / q)))


def tvd(p: np.ndarray, q: np.ndarray) -> float:
    """Total Variation Distance. 0 = identical, 1 = completely different."""
    return float(0.5 * np.sum(np.abs(p - q)))


def success_probability(counts: dict[str, int], true_k: int) -> float:
    """Fraction of shots that recovered the correct key."""
    total = sum(counts.values())
    key_str = None
    for bitstring, cnt in counts.items():
        if int(bitstring, 2) == true_k:
            key_str = cnt
            break
    return (key_str or 0) / total


def quantum_advantage_report(
    quantum_counts: dict[str, int],
    true_k: int,
    n_bits: int,
    shots: int,
) -> dict:
    """
    Full analysis report comparing quantum output vs /dev/urandom baseline.
    This is the key metric that the 15-bit prize submission lacked.
    """
    uniform = counts_to_distribution(random_baseline_counts(n_bits, shots), n_bits)
    quantum_dist = counts_to_distribution(quantum_counts, n_bits)

    chi2, p_val = chi_squared_vs_uniform(quantum_counts, n_bits)
    kl = kl_divergence(quantum_dist, uniform)
    tv = tvd(quantum_dist, uniform)
    p_success = success_probability(quantum_counts, true_k)
    random_expected = 1.0 / (2**n_bits)

    return {
        "n_bits": n_bits,
        "true_k": true_k,
        "shots": shots,
        "success_probability": p_success,
        "random_expected_success": random_expected,
        "success_ratio_vs_random": p_success / random_expected if random_expected > 0 else 0,
        "chi2_statistic": chi2,
        "chi2_p_value": p_val,
        "kl_divergence_from_uniform": kl,
        "total_variation_distance": tv,
        "has_quantum_advantage": p_val < 0.01 and p_success / random_expected > 3.0,
    }


def classical_brute_force_timing(brute_force_fn, *args) -> tuple[any, float]:
    """Time a classical brute-force solver. Used to compare against quantum."""
    start = time.perf_counter()
    result = brute_force_fn(*args)
    elapsed = time.perf_counter() - start
    return result, elapsed


def print_report(report: dict):
    print("=" * 60)
    print(f"  Quantum Advantage Analysis  ({report['n_bits']}-bit ECDLP)")
    print("=" * 60)
    print(f"  True k:               {report['true_k']}")
    print(f"  Shots:                {report['shots']}")
    print(f"  Success prob:         {report['success_probability']:.6f}")
    print(f"  Random baseline:      {report['random_expected_success']:.6f}")
    print(f"  Ratio vs random:      {report['success_ratio_vs_random']:.1f}x")
    print(f"  Chi2 p-value:         {report['chi2_p_value']:.4e}")
    print(f"  KL divergence:        {report['kl_divergence_from_uniform']:.6f}")
    print(f"  TVD vs uniform:       {report['total_variation_distance']:.6f}")
    print("-" * 60)
    verdict = "QUANTUM ADVANTAGE DETECTED" if report["has_quantum_advantage"] else "NO QUANTUM ADVANTAGE (indistinguishable from noise)"
    print(f"  Verdict: {verdict}")
    print("=" * 60)
