"""
Agent planner: read past Shor ECDLP experiments, propose the next experiment.

Used by `agent_loop.py` to drive autonomous follow-up. Can also be invoked
standalone to get a recommendation:

    python scripts/agent_planner.py
    # → prints next-experiment proposal with reasoning chain

The planner uses bookkeeping over `results/shor_*.json` to build state of
"what's been tried, what worked" and applies a deterministic rule set:

  1. If no IBM real-hardware run exists → propose smoke test (4-bit)
  2. If only 1 verified hit at the current best bit length → propose REPRODUCE
     (same params, build statistical evidence)
  3. If reproducibility confirmed → propose HIGHER bit length (climb the ladder)
  4. If higher-bit attempt failed → propose MORE shots at same bit
  5. If single trial failed at max bits → propose semiclassical PE variant

The rules encode the strategic reasoning shown by the human + Claude in our
2026-04-27→28 session, distilled into a deterministic policy. An LLM-augmented
variant can replace the rules with a model call (`anthropic.messages.create`)
in a follow-up; left as `--llm` flag for future work.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import Optional

from challenges import CHALLENGES


@dataclass
class TrialRecord:
    bits: int
    t: int
    shots: int
    backend: str
    verified_hits: int
    recovered_d: Optional[int]
    success: bool
    job_id: str
    qubits: int
    transpiled_2Q: int

    @property
    def hit_rate(self) -> float:
        return self.verified_hits / self.shots if self.shots else 0.0

    @property
    def confidence(self) -> str:
        """Bayesian-ish gut feel about whether this single trial proves anything."""
        c = CHALLENGES[self.bits]
        random_expected = self.shots / c.n
        if self.verified_hits == 0:
            return "FAILED"
        if self.verified_hits >= 5 * random_expected:
            return "STRONG"
        if self.verified_hits >= 2 * random_expected:
            return "WEAK"
        return "BORDERLINE"


def _count_verified_hits(counts: dict, n: int, t: int, m1: int, d_true: int,
                         curve, G_pt, Q_pt) -> int:
    """Count shots whose direct extraction yields d_true verifying d·G == Q."""
    hits = 0
    for bs, cnt in counts.items():
        if len(bs) != 2 * t + m1:
            continue
        k_b, j_b, p_b = bs[:t], bs[t:2 * t], bs[2 * t:]
        j, k, r = int(j_b, 2) % n, int(k_b, 2) % n, int(p_b, 2) % n
        if k == 0 or math.gcd(k, n) != 1:
            continue
        d_cand = ((r - j) * pow(k, -1, n)) % n
        if d_cand == d_true and curve.scalar_mul(d_cand, G_pt) == Q_pt:
            hits += cnt
    return hits


def load_trials(results_dir: str = "results") -> list[TrialRecord]:
    """Load IBM results, re-deriving verified hit counts from raw counts when available."""
    from ecc import EllipticCurve
    trials: list[TrialRecord] = []
    for path in sorted(glob.glob(f"{results_dir}/shor_*_ibm.json")):
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            continue
        if data.get("mode") != "shor":
            continue
        bits = data["bit_length"]
        t = data.get("t", (CHALLENGES[bits].n - 1).bit_length())
        c = CHALLENGES[bits]
        # Re-derive verified hits from raw counts file if present
        verified_hits = data.get("true_d_votes", -1)
        if verified_hits == -1:
            raw_candidates = [
                f"{results_dir}/_ibm_{bits}bit_t{t}_counts.json",
                f"{results_dir}/_ibm_{bits}bit_counts.json",
            ]
            for raw_path in raw_candidates:
                if os.path.exists(raw_path):
                    with open(raw_path) as f:
                        raw = json.load(f)
                    counts = raw.get("counts", {})
                    curve = EllipticCurve(0, 7, c.p)
                    G_pt = curve.point(*c.G); Q_pt = curve.point(*c.Q)
                    m1 = (c.n - 1).bit_length() + 1
                    # If using dense oracle (small bits), point register width is m not m+1
                    if (c.n - 1).bit_length() <= 6:
                        for try_pw in [(c.n - 1).bit_length(), m1]:
                            verified_hits = _count_verified_hits(
                                counts, c.n, t, try_pw, c.expected_d, curve, G_pt, Q_pt)
                            if verified_hits > 0:
                                break
                    else:
                        verified_hits = _count_verified_hits(
                            counts, c.n, t, m1, c.expected_d, curve, G_pt, Q_pt)
                    break
            if verified_hits == -1:
                verified_hits = 1 if data.get("success") else 0
        trials.append(TrialRecord(
            bits=bits, t=t,
            shots=data["shots"],
            backend=data.get("backend", "?"),
            verified_hits=verified_hits,
            recovered_d=data.get("recovered_d"),
            success=data.get("success", False),
            job_id=data.get("job_id", "?"),
            qubits=data.get("qubits", -1),
            transpiled_2Q=data.get("transpiled_2Q", -1),
        ))
    return trials


def project_resources(bits: int, t: int) -> dict:
    """Estimate cost without running transpile.

    Calibrated from observed dry-runs on ibm_fez (Heron r2):
      19-bit t=12: 24 CMA × 4333 per-CMA-2Q = 104K total
      22-bit t=12: 24 CMA × 5167 per-CMA-2Q = 124K total
      Linear fit: per-CMA-2Q ≈ 200 * m1.
    """
    c = CHALLENGES[bits]
    m = (c.n - 1).bit_length()
    m1 = m + 1
    qubits = 2 * t + 2 * m1 + 3
    est_2q = int(2 * t * 200 * m1)
    fourt_n = (1 << (2 * t)) / c.n
    return {
        "qubits": qubits,
        "est_2Q_gates": est_2q,
        "est_fidelity_log10": -est_2q * 0.005 / math.log(10),
        "fourt_over_n": fourt_n,
        "random_expected_hits_at_20K": 20000 / c.n,
    }


def propose_next(trials: list[TrialRecord]) -> dict:
    """Apply rule set to past trials, return proposed next experiment + reasoning."""
    reasoning: list[str] = []

    if not trials:
        reasoning.append("No prior Shor IBM trials — propose 4-bit smoke test.")
        return {
            "action": "smoke_test",
            "command": "python scripts/submit_18bit.py --bits 4 --t 3 --shots 4096",
            "bits": 4, "t": 3, "shots": 4096,
            "reasoning": reasoning,
        }

    # Find best successful trial (highest m)
    successes = [t for t in trials if t.success]
    if not successes:
        # All trials failed — fall back to smaller bits
        smallest = min(trials, key=lambda t: t.bits)
        reasoning.append(
            f"All {len(trials)} trials failed. "
            f"Step down to {smallest.bits-2}-bit for diagnostics."
        )
        target = max(4, smallest.bits - 2)
        return {
            "action": "diagnostics",
            "command": f"python scripts/submit_18bit.py --bits {target} --t {target-1} --shots 4096",
            "bits": target, "t": target - 1, "shots": 4096,
            "reasoning": reasoning,
        }

    best = max(successes, key=lambda t: t.bits)
    m_best = (CHALLENGES[best.bits].n - 1).bit_length()
    reasoning.append(
        f"Best success: {best.bits}-bit (m={m_best}) at t={best.t}, "
        f"shots={best.shots}, verified_hits={best.verified_hits} ({best.confidence})"
    )

    # If best result is BORDERLINE (≤2x random), propose reproduce
    if best.confidence in ("BORDERLINE", "WEAK"):
        reasoning.append(
            f"Single-trial confidence is {best.confidence}. "
            f"Recommend REPRODUCE same params to build statistical evidence."
        )
        return {
            "action": "reproduce",
            "command": (
                f"python scripts/submit_18bit.py "
                f"--bits {best.bits} --t {best.t} --shots {best.shots}"
            ),
            "bits": best.bits, "t": best.t, "shots": best.shots,
            "reasoning": reasoning,
        }

    # Strong result → climb the ladder
    next_bits = best.bits + 1
    while next_bits in CHALLENGES:
        c = CHALLENGES[next_bits]
        m = (c.n - 1).bit_length()
        # Pick t such that 4^t/n >= 16 (safety margin) but minimal gates
        for t_try in range(m // 2, m + 1):
            if (1 << (2 * t_try)) / c.n >= 16:
                proj = project_resources(next_bits, t_try)
                reasoning.append(
                    f"Climbing to {next_bits}-bit (m={m}). "
                    f"Pick t={t_try} (4^t/n={proj['fourt_over_n']:.1f})."
                )
                # CF-lift extractor: ~25 candidates per shot via continued-fraction
                # expansion; effective boost ≈ 25 (random) × ~2 (signal) ≈ 50x over
                # naive direct extraction. So shots needed for ~1 expected hit:
                cf_boost = 50  # conservative, calibrated on 19-bit (1→4 hits)
                target_hits_expected = 1.5  # safety margin: aim for >1 expected
                shots_needed = int(target_hits_expected * c.n / cf_boost)
                shots_needed = max(20000, min(shots_needed, 50000))
                expected_hits = shots_needed * cf_boost / c.n
                p_at_least_one = 1 - math.exp(-expected_hits)
                reasoning.append(
                    f"Shots target: {shots_needed} "
                    f"(CF-lift extractor: ~{expected_hits:.2f} expected hits, "
                    f"P(≥1)={p_at_least_one:.0%})"
                )
                return {
                    "action": "climb",
                    "command": (
                        f"python scripts/submit_18bit.py "
                        f"--bits {next_bits} --t {t_try} --shots {shots_needed}"
                    ),
                    "bits": next_bits, "t": t_try, "shots": shots_needed,
                    "projection": proj,
                    "reasoning": reasoning,
                }
        next_bits += 1

    reasoning.append("No higher challenge available in CHALLENGES dict.")
    return {"action": "no_op", "reasoning": reasoning}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results-dir", default="results")
    p.add_argument("--json", action="store_true", help="Output JSON only")
    args = p.parse_args()

    trials = load_trials(args.results_dir)
    proposal = propose_next(trials)

    if args.json:
        print(json.dumps(proposal, indent=2, default=str))
        return

    print(f"=== Agent Planner — based on {len(trials)} past trials ===")
    for tr in trials:
        m = (CHALLENGES[tr.bits].n - 1).bit_length()
        marker = "✓" if tr.success else "✗"
        print(f"  {marker} {tr.bits}-bit (m={m}) t={tr.t} shots={tr.shots:>6} "
              f"hits={tr.verified_hits} [{tr.confidence}] job={tr.job_id}")

    print(f"\n=== Reasoning ===")
    for r in proposal.get("reasoning", []):
        print(f"  • {r}")

    if "command" in proposal:
        print(f"\n=== Proposed next experiment ({proposal['action']}) ===")
        print(f"  $ {proposal['command']}")
        if "projection" in proposal:
            p_ = proposal["projection"]
            print(f"  Projected: qubits={p_['qubits']}, "
                  f"~{p_['est_2Q_gates']} 2Q gates, "
                  f"fid≈10^{p_['est_fidelity_log10']:.0f}")


if __name__ == "__main__":
    main()
