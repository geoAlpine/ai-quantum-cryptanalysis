"""Surface code baseline simulation — first FT R&D step.

Generates rotated planar surface code memory experiments at multiple
distances under uniform depolarising noise. Decodes with PyMatching
(MWPM) and reports logical error rate per round. This establishes the
threshold curve we'll need to design FT compilation for our m=15 Shor
target.

Background: the threshold theorem says that if the physical error rate
p is below ~1% for the surface code, then increasing distance d
suppresses logical error rate as ~(p/p_thresh)^(d+1)/2. Below threshold,
each +2 in distance roughly squares the suppression. The data here
should show that pattern for Helios-class p ≈ 1e-3.

Per-round logical errors at p=1e-3:
  d=3 :  ~5e-4   (factor 2 below physical)
  d=5 :  ~3e-5   (factor 30 below)
  d=7 :  ~2e-6   (factor 500 below)
  d=9 :  ~1e-7   (factor 10000 below)
(These are rough numbers; exact values depend on noise model.)

Usage:
    python scripts/stim_surface_code_baseline.py
"""
from __future__ import annotations

import numpy as np
import stim
import pymatching


def measure_logical_error_rate(
    distance: int,
    rounds: int,
    physical_error: float,
    shots: int,
    seed: int = 0,
) -> tuple[int, int]:
    """Run a memory experiment for the rotated planar surface code.

    Returns (n_errors, n_shots) so caller can aggregate across runs.
    """
    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_x",
        rounds=rounds,
        distance=distance,
        after_clifford_depolarization=physical_error,
        after_reset_flip_probability=physical_error,
        before_measure_flip_probability=physical_error,
        before_round_data_depolarization=physical_error,
    )

    # Build the matching graph from the circuit's error model
    dem = circuit.detector_error_model(decompose_errors=True)
    matching = pymatching.Matching.from_detector_error_model(dem)

    sampler = circuit.compile_detector_sampler(seed=seed)
    detection_events, observable_flips = sampler.sample(
        shots, separate_observables=True
    )
    predictions = matching.decode_batch(detection_events)
    errors = int(np.sum(predictions != observable_flips))
    return errors, shots


def main():
    print("=== Surface code memory baseline (FT R&D step 1) ===\n")
    print(f"{'distance':>8} {'rounds':>7} {'p_phys':>9} {'shots':>6} "
          f"{'errors':>7} {'p_logical':>11} {'suppression':>12}")
    print("-" * 75)

    p_phys_levels = [1e-2, 3e-3, 1e-3, 3e-4]  # IBM-ish, H2 emulator, Helios, H3 optim
    distances = [3, 5, 7]
    rounds = 5  # multiple rounds per shot to amortize timelike boundary

    for p in p_phys_levels:
        for d in distances:
            # More shots for the lower-error regimes
            shots = 5000 if p > 1e-3 else 20000
            try:
                errors, n = measure_logical_error_rate(d, rounds, p, shots)
                p_log = errors / max(1, n)
                suppression = p / max(1e-12, p_log)
                print(f"  {d:>8} {rounds:>7} {p:>9.1e} {n:>6} "
                      f"{errors:>7} {p_log:>11.3e} {suppression:>11.1f}x")
            except Exception as e:
                print(f"  d={d} p={p}: ERROR {type(e).__name__}: {str(e)[:50]}")
        print()


if __name__ == "__main__":
    main()
