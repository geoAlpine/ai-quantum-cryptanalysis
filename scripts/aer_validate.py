"""
Aer end-to-end validation of the ShorECDLPSolver pipeline.

For small bit-counts where statevector / MPS simulation is tractable, this
runs the *exact production circuit* (built by ShorECDLPSolver) on the Aer
simulator. Then it runs the v3 extractor on the counts and checks whether
d is recovered.

Three uses:
  1. **Pipeline regression test** — confirms the solver-to-extractor flow
     is bug-free at each oracle/t combination
  2. **Ideal hit-rate baseline** — measures how often verified d appears in
     the *noiseless* QFT distribution. Establishes the upper bound on what
     hardware noise leaves on the table.
  3. **Threshold validation** — empirically explores the 4^t/n boundary by
     scanning t and showing where signal collapses into noise.
  4. **Noisy preview** (--noise-from): predict hardware behavior at modest
     bit-sizes by running with a real backend's noise model. Backend
     properties are metadata — fetching them costs zero QPU. Practical
     ceiling: ~22-24 logical qubits (4-bit ripple = 12 qubits; 6-bit
     dense = 13 qubits; 6-bit ripple = 16 qubits + ancilla → tight).

Usage:
    python scripts/aer_validate.py --bits 6 --oracle ripple --t 4 --shots 4096
    python scripts/aer_validate.py --bits 6 --oracle dense --t 6 --shots 4096
    python scripts/aer_validate.py --bits 4 --scan-t  # sweep t=1..m
    python scripts/aer_validate.py --bits 4 --oracle ripple --t 3 --shots 1024 \\
        --noise-from ibm_fez   # noisy preview at 11 qubits
"""

import argparse
import math
import os
import sys
import time

from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import (
    ShorECDLPSolver,
    SubgroupIndexer,
    DenseUnitaryOracle,
    RippleCarryOracle,
)
from qiskit_aer import AerSimulator
from qiskit import transpile
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager


_BACKEND_CACHE: dict[str, tuple] = {}


def _get_noisy_backend(name: str):
    """Fetch IBM backend (sim, pass_manager) once per process. Free metadata
    fetch — no QPU consumed. Cached because the auth + properties round-trip
    is ~1-2s and we may want repeated calls in a t-scan."""
    if name in _BACKEND_CACHE:
        return _BACKEND_CACHE[name]
    from qiskit_ibm_runtime import QiskitRuntimeService
    from quantum_ecc import load_token
    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    backend = svc.backend(name)
    sim = AerSimulator.from_backend(backend)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    _BACKEND_CACHE[name] = (sim, pm, backend)
    return _BACKEND_CACHE[name]


def run_one(bits: int, oracle_kind: str, t: int, shots: int,
            sim_method: str = "automatic", verbose: bool = True,
            noise_from: str | None = None):
    c = get_challenge(bits)
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)

    ind = SubgroupIndexer(curve, G, c.n)
    if oracle_kind == "dense":
        if bits > 6:
            return {"skipped": "dense oracle requires bits<=6"}
        oracle = DenseUnitaryOracle(ind)
    else:
        oracle = RippleCarryOracle(ind)

    solver = ShorECDLPSolver(curve, G, Q, c.n, oracle=oracle, num_counting=t)
    plan = solver.plan()
    qc = solver.build_circuit()

    if verbose:
        suffix = f" noise={noise_from}" if noise_from else ""
        print(f"[bits={bits} oracle={oracle_kind} t={t}] "
              f"qubits={plan.total_qubits}, 4^t/n={4**t/c.n:.2f}{suffix}")

    if plan.total_qubits > 28 and sim_method == "statevector":
        return {"skipped": f"too many qubits ({plan.total_qubits}) for statevector"}

    transpiled_2q = None
    if noise_from:
        # Real-noise mode: simulate with backend's calibration. Density-matrix
        # simulation is 4^N memory, so cap at ~14 qubits; otherwise Aer falls
        # back to stochastic per-shot statevector (slower but 2^N memory).
        if plan.total_qubits > 24:
            return {"skipped": f"noise sim impractical at {plan.total_qubits} qubits"}
        sim, pm, backend = _get_noisy_backend(noise_from)
        if verbose:
            print(f"  backend snapshot: {backend.name}, n_qubits={backend.num_qubits}")
        qc_t = pm.run(qc)
        transpiled_2q = sum(v for k, v in qc_t.count_ops().items()
                             if k in ("cx", "ecr", "cz"))
        if verbose:
            print(f"  transpiled: depth={qc_t.depth()}, 2Q={transpiled_2q}")
    else:
        sim = AerSimulator(method=sim_method)
        qc_t = transpile(qc, sim, optimization_level=1)

    t0 = time.time()
    result = sim.run(qc_t, shots=shots).result()
    counts = result.get_counts()
    sim_time = time.time() - t0

    # Run v3 extractor (defaults match what fetch_result.py / submit_25bit.py use)
    d_recovered = solver.extract(counts, cf_window=16, cf_version="v3")

    # Count "verified hits" the same way IBM analysis does: shots whose v3
    # candidate set contains d_true. This is the ideal hit rate at this t.
    n = c.n
    pt_w = oracle.point_register_width()
    hits = 0
    triples = 0
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        triples += 1
        k = int(bs[:t], 2) % n
        j = int(bs[t:2*t], 2) % n
        r = int(bs[2*t:], 2) % n
        a_list = solver._cf_lift_v3(j, t, n, window=16)
        b_list = solver._cf_lift_v3(k, t, n, window=16)
        for b in b_list:
            if b == 0 or math.gcd(b, n) != 1:
                continue
            b_inv = pow(b, -1, n)
            for a in a_list:
                d_cand = ((r - a) * b_inv) % n
                if d_cand == c.expected_d:
                    hits += cnt
                    break
            else:
                continue
            break

    # Direct extraction hit count (no CF-lift, just (r-j)*k^-1)
    direct_hits = 0
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        k = int(bs[:t], 2) % n
        j = int(bs[t:2*t], 2) % n
        r = int(bs[2*t:], 2) % n
        if k == 0 or math.gcd(k, n) != 1:
            continue
        d_cand = ((r - j) * pow(k, -1, n)) % n
        if d_cand == c.expected_d:
            direct_hits += cnt

    return {
        "bits": bits,
        "oracle": oracle_kind,
        "t": t,
        "qubits": plan.total_qubits,
        "shots": shots,
        "unique_outcomes": len(counts),
        "expected_d": c.expected_d,
        "recovered_d": d_recovered,
        "success": d_recovered == c.expected_d,
        "direct_hits": direct_hits,
        "v3_hits": hits,
        "ideal_signal_ratio": hits / shots if shots else 0,
        "ratio_4t_over_n": 4**t / c.n,
        "sim_time": sim_time,
        "sim_method": sim_method,
        "noise_from": noise_from,
        "transpiled_2q": transpiled_2q,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bits", type=int, default=4)
    p.add_argument("--oracle", choices=["dense", "ripple"], default="dense")
    p.add_argument("--t", type=int, default=None)
    p.add_argument("--shots", type=int, default=4096)
    p.add_argument("--sim-method", default="automatic")
    p.add_argument("--scan-t", action="store_true",
                   help="Sweep t=1..m (else use --t or t=m)")
    p.add_argument("--noise-from", type=str, default=None,
                   help="IBM backend name (e.g. ibm_fez) to load noise model "
                        "from. Free metadata fetch — costs 0 QPU. Practical "
                        "ceiling ~24 qubits.")
    args = p.parse_args()

    c = get_challenge(args.bits)
    m = max(1, (c.n - 1).bit_length())

    if args.scan_t:
        ts = list(range(1, m + 1))
    else:
        ts = [args.t if args.t is not None else m]

    label = f"noisy ({args.noise_from})" if args.noise_from else "noiseless"
    print(f"=== Aer {label} pipeline validation ===")
    print(f"bits={args.bits} n={c.n} m={m} d={c.expected_d} oracle={args.oracle}")
    print()
    print(f"{'t':<4} {'qubits':<8} {'4^t/n':<10} {'success':<10} "
          f"{'direct_hits':<14} {'v3_hits':<10} {'sim_t':<8}")
    print("-" * 70)

    for t in ts:
        r = run_one(args.bits, args.oracle, t, args.shots,
                    sim_method=args.sim_method, verbose=False,
                    noise_from=args.noise_from)
        if "skipped" in r:
            print(f"t={t}  SKIPPED ({r['skipped']})")
            continue
        ok = "OK" if r["success"] else "FAIL"
        print(f"{t:<4} {r['qubits']:<8} {r['ratio_4t_over_n']:<10.2f} "
              f"d={r['recovered_d']} {ok:<6} "
              f"{r['direct_hits']:<14} {r['v3_hits']:<10} "
              f"{r['sim_time']:<8.1f}")


if __name__ == "__main__":
    main()
