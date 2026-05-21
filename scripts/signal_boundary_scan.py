"""
Signal-extraction boundary scan.

Sweeps ``m`` over a range, runs the full Shor-ECDLP circuit on Aer
(noiseless and/or with an IBM backend noise model), then evaluates the
**collective vote test**: without telling the extractor the answer, does
the true ``d`` emerge as the argmax of the candidate vote distribution?

This is the test the headline 22-bit run failed (d_true was at the 48th
percentile of votes — i.e. indistinguishable from any random ``d``).
Finding the largest ``m`` where the test PASSES on a noise model of
real hardware tells us where to aim the next real-QPU submission.

Usage:
    # Noiseless: confirm methodology — every m should pass.
    python scripts/signal_boundary_scan.py --m 6 7 8 9 10

    # Noisy: where does signal actually die?
    python scripts/signal_boundary_scan.py --m 6 7 8 9 10 --noise-from ibm_fez

    # Single m with extra shots to fight noise:
    python scripts/signal_boundary_scan.py --m 8 --shots 8192 --noise-from ibm_fez
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import numpy as np

from cf_lift import cf_lift_v3
from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import (
    DenseUnitaryOracle,
    RippleCarryOracle,
    ShorECDLPSolver,
    SubgroupIndexer,
)
from qiskit_aer import AerSimulator
from qiskit import transpile


_BACKEND_CACHE: dict[str, tuple] = {}


def _get_noisy_backend(name: str):
    if name in _BACKEND_CACHE:
        return _BACKEND_CACHE[name]
    from qiskit_ibm_runtime import QiskitRuntimeService
    from quantum_ecc import load_token
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    svc = QiskitRuntimeService(channel="ibm_quantum_platform", token=load_token())
    backend = svc.backend(name)
    sim = AerSimulator.from_backend(backend)
    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    _BACKEND_CACHE[name] = (sim, pm, backend)
    return _BACKEND_CACHE[name]


def _stats(votes: np.ndarray, n: int, d_true: int) -> dict:
    total = int(votes.sum())
    e_uniform = total / n if n else 0.0
    std_uniform = math.sqrt(e_uniform * max(0, 1 - 1 / n)) if n else 0.0
    v_d_true = int(votes[d_true])
    rank_d_true = int(np.sum(votes > v_d_true) + 1)
    return {
        "total_votes": total,
        "e_uniform": e_uniform,
        "std_uniform": std_uniform,
        "votes_d_true": v_d_true,
        "ratio_to_uniform": v_d_true / e_uniform if e_uniform else 0.0,
        "z_score": ((v_d_true - e_uniform) / std_uniform) if std_uniform else 0.0,
        "rank_d_true": rank_d_true,
        "argmax_is_d_true": rank_d_true == 1,
    }


def collective_vote_argmax(counts: dict[str, int],
                            n: int, t: int, pt_w: int,
                            window: int,
                            d_true: int) -> dict:
    """Two complementary no-side-channel vote tests:
      * **direct**: 1 candidate per shot via ``d = (r - a_direct) * b_direct⁻¹``.
        Cleanest interpretation, lowest sensitivity.
      * **v3-cf**: expanded candidate set per shot via ``cf_lift_v3``. Higher
        sensitivity at the cost of candidate-density saturation when n is small.
    """
    votes_direct = np.zeros(n, dtype=np.int64)
    votes_v3 = np.zeros(n, dtype=np.int64)
    cf_cache: dict[int, list[int]] = {}

    def cf(x: int) -> list[int]:
        if x in cf_cache:
            return cf_cache[x]
        v = cf_lift_v3(x, t, n, window=window)
        cf_cache[x] = v
        return v

    N = 1 << t
    parsed = 0
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + pt_w:
            continue
        parsed += 1
        # Qiskit measurement strings need reversing for the per-register MSB
        # convention these classical registers use — verified empirically on
        # noiseless 4-bit ripple, which gives d_true rank=1 only with this
        # parse and falls to noise floor without it.
        bs_r = bs[::-1]
        k = int(bs_r[:t], 2) % n
        j = int(bs_r[t:2 * t], 2) % n
        r = int(bs_r[2 * t:], 2) % n

        # Direct extraction: try BOTH signs and BOTH floor/ceiling rounding
        # of a, b — the statevector inspection showed different peaks need
        # different (a, b, sign) combinations to hit d_true.
        for a_d in {(j * n) // N, (j * n + N - 1) // N, (j * n + N // 2) // N}:
            for b_d in {(k * n) // N, (k * n + N - 1) // N, (k * n + N // 2) // N}:
                if b_d == 0 or math.gcd(b_d, n) != 1:
                    continue
                binv = pow(b_d, -1, n)
                votes_direct[((r - a_d) * binv) % n] += cnt
                votes_direct[((a_d - r) * binv) % n] += cnt

        # v3 candidate set: many candidates per shot, BOTH signs.
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
            a_minus_r = (a - r) % n
            for _, b_inv in b_invs:
                d_set.add((r_minus_a * b_inv) % n)
                d_set.add((a_minus_r * b_inv) % n)
        for d in d_set:
            votes_v3[d] += cnt

    s_direct = _stats(votes_direct, n, d_true)
    s_v3 = _stats(votes_v3, n, d_true)
    return {
        "parsed_triples": parsed,
        "direct": s_direct,
        "v3": s_v3,
    }


def run_one(m_bits: int, t: int, oracle_kind: str, shots: int,
            window: int, noise_from: str | None):
    c = get_challenge(m_bits)
    n = c.n
    curve = EllipticCurve(0, 7, c.p)
    G = curve.point(*c.G)
    Q = curve.point(*c.Q)

    ind = SubgroupIndexer(curve, G, n)
    if oracle_kind == "dense":
        if m_bits > 6:
            return {"skipped": "dense oracle requires bits<=6"}
        oracle = DenseUnitaryOracle(ind)
    else:
        oracle = RippleCarryOracle(ind)

    solver = ShorECDLPSolver(curve, G, Q, n, oracle=oracle, num_counting=t)
    plan = solver.plan()
    qc = solver.build_circuit()
    pt_w = oracle.point_register_width()

    if noise_from:
        if plan.total_qubits > 24:
            return {"skipped": f"noise sim impractical at {plan.total_qubits} qubits"}
        sim, pm, _ = _get_noisy_backend(noise_from)
        qc_t = pm.run(qc)
        transpiled_2q = sum(v for k_, v in qc_t.count_ops().items()
                            if k_ in ("cx", "ecr", "cz"))
    else:
        if plan.total_qubits > 32:
            return {"skipped": f"too many qubits ({plan.total_qubits}) for statevector"}
        sim = AerSimulator(method="automatic")
        qc_t = transpile(qc, sim, optimization_level=1)
        transpiled_2q = sum(v for k_, v in qc_t.count_ops().items()
                            if k_ in ("cx", "ecr", "cz"))

    t0 = time.time()
    counts = sim.run(qc_t, shots=shots).result().get_counts()
    sim_time = time.time() - t0

    stats = collective_vote_argmax(counts, n, t, pt_w,
                                    window=window,
                                    d_true=c.expected_d)

    return {
        "bits": m_bits,
        "m": (n - 1).bit_length(),
        "n": n,
        "t": t,
        "oracle": oracle_kind,
        "qubits": plan.total_qubits,
        "shots": shots,
        "transpiled_2q": transpiled_2q,
        "sim_time": sim_time,
        "noise_from": noise_from,
        "window": window,
        "d_true": c.expected_d,
        **stats,
    }


def fmt_row(r: dict) -> str:
    def _flag(s):
        return "✓" if s["argmax_is_d_true"] else "✗"
    return (
        f"{r['bits']:>3} {r['oracle']:<6} {r['qubits']:>2}q  "
        f"{r['shots']:>6}sh  n={r['n']:<8,}  "
        f"direct[{_flag(r['direct'])} rank={r['direct']['rank_d_true']:>6,}, "
        f"z={r['direct']['z_score']:+5.2f}σ]  "
        f"v3[{_flag(r['v3'])} rank={r['v3']['rank_d_true']:>6,}, "
        f"z={r['v3']['z_score']:+5.2f}σ]  sim={r['sim_time']:.1f}s"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--m", type=int, nargs="+", default=[6, 7, 8, 9, 10],
                    help="bit-lengths to scan (default: 6 7 8 9 10)")
    ap.add_argument("--t", type=int, default=None,
                    help="counting register width (default: m, full precision)")
    ap.add_argument("--shots", type=int, default=4096)
    ap.add_argument("--oracle", choices=["auto", "dense", "ripple"], default="auto",
                    help="auto = dense for m<=6, ripple otherwise")
    ap.add_argument("--window", type=int, default=0,
                    help="v3 cf_window (0 = direct + bitflip + mirror only)")
    ap.add_argument("--noise-from", default=None,
                    help="IBM backend name for noise model (e.g. ibm_fez)")
    args = ap.parse_args()

    label = f"noisy ({args.noise_from})" if args.noise_from else "noiseless"
    print(f"=== Signal-boundary scan ({label}) ===")
    print(f"  shots/m = {args.shots}, v3 cf_window = {args.window}")
    print()
    print(f"{'bits':<3} {'oracle':<6} {'q':<3}  {'2Q':<6} {'shots':<8} "
          f"{'collective vote argmax':<20}  ratio    z          sim")
    print("-" * 120)

    summary = []
    for m_bits in args.m:
        t = args.t if args.t is not None else m_bits
        oracle_kind = args.oracle
        if oracle_kind == "auto":
            oracle_kind = "dense" if m_bits <= 6 else "ripple"
        try:
            r = run_one(m_bits, t, oracle_kind, args.shots,
                        window=args.window, noise_from=args.noise_from)
        except Exception as e:
            print(f"{m_bits:>3} ERROR: {type(e).__name__}: {str(e)[:80]}")
            continue
        if "skipped" in r:
            print(f"{m_bits:>3} SKIPPED  ({r['skipped']})")
            continue
        print(fmt_row(r))
        summary.append(r)

    print()
    direct_passing = [r for r in summary if r["direct"]["argmax_is_d_true"]]
    v3_passing = [r for r in summary if r["v3"]["argmax_is_d_true"]]
    if direct_passing:
        print(f"==> direct-extraction signal works up to m = "
              f"{max(r['m'] for r in direct_passing)} ({label})")
    else:
        print(f"==> direct-extraction signal not detected in this scan "
              f"({label})")
    if v3_passing:
        print(f"==> v3-cf signal works up to m = "
              f"{max(r['m'] for r in v3_passing)} ({label})")


if __name__ == "__main__":
    sys.exit(main())
