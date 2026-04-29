# quantum-ecc

> Autonomous AI-driven cryptanalysis of the Elliptic Curve Discrete Logarithm
> Problem (ECDLP) on IBM Quantum hardware. Built end-to-end by an LLM agent
> (Anthropic Claude Sonnet 4.6 via Claude Code) — see [`AGENT.md`](AGENT.md)
> for the workflow record.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Quantum: IBM Heron r2](https://img.shields.io/badge/Quantum-IBM_Heron_r2-blueviolet.svg)](https://www.ibm.com/quantum)
[![Q-Day Prize: submission](https://img.shields.io/badge/Q--Day_Prize-Round_2_submission-orange.svg)](https://www.qdayprize.org/)

## 🏆 Headline result

**Recovered the 22-bit (m = 22) ECDLP private key `d = 1,999,171` on IBM Quantum
`ibm_fez`** — **+7 algorithmic steps beyond Lelli's Q-Day Prize Round-1 winning
15-bit (m = 15) submission, and +6 beyond his highest documented success
(17-bit, m = 16)**. Job ID: `d7o5mr62jamc73bp87eg`.

| Submission | label | m | qubits | 2Q gates | Recovered d | Hits | Job |
|---|---|---|---|---|---|---|---|
| Lelli 2026 — Round-1 prize | 15-bit | 15 | (smaller) | (smaller) | (15-bit prize key) | — | (Round-1 award) |
| Lelli 2026 — best documented | 17-bit | 16 | 69 | 111,816 | 1,441 ✓ | 1+ | d790krrc6das739idasg |
| **This work — 22-bit** | 22-bit | **22** | 73 | 124,422 | **1,999,171 ✓** | **12** | **d7o5mr62jamc73bp87eg** |
| This work — 19-bit (independent confirm) | 19-bit | 19 | 67 | 103,708 | 36,124 ✓ | 1+ | d7o2dem2jamc73bp3jig |

**Note on bit-length labeling.** The Q-Day Prize challenges are labeled by the
prime `p`'s bit length, but the Shor algorithm's actual difficulty is governed
by the subgroup order `n` bit length (`m = ⌈log₂ n⌉`). The "17-bit challenge"
has m = 16 because n = 65,173 < 2¹⁶. Our "22-bit challenge" has m = 22 because
n = 2,098,699 ≥ 2²¹.

Submission writeup: [`brief.md`](brief.md). Full hardware reproduction
instructions below.

## Quick start

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Set IBM Quantum token
cp .env.example .env
# edit .env to add your IBM_QUANTUM_TOKEN (get one at https://quantum.cloud.ibm.com/)

# 3. Run on simulator (free, ≤6-bit)
python run_experiment.py --shor --shor-bits 6 --shots 4096

# 4. Run on real IBM Quantum hardware (uses ~1-7 min of monthly free QPU)
python scripts/submit_18bit.py --bits 22 --t 12 --shots 35000 --backend auto
python scripts/fetch_result.py results/_pending_22bit_t12_ibm.json
```

## Reproducing the headline 22-bit result from existing data

The 35,000-shot raw counts file (`results/_ibm_22bit_t12_counts.json`) is
shipped with the repository. To re-derive `d = 1,999,171` without any quantum
access:

```bash
python -c "
import sys, json; sys.path.insert(0, 'src')
from challenges import get_challenge
from ecc import EllipticCurve
from shor_ecdlp import ShorECDLPSolver, RippleCarryOracle, SubgroupIndexer
counts = json.load(open('results/_ibm_22bit_t12_counts.json'))['counts']
c = get_challenge(22); curve = EllipticCurve(0, 7, c.p)
G, Q = curve.point(*c.G), curve.point(*c.Q)
solver = ShorECDLPSolver(curve, G, Q, c.n,
    oracle=RippleCarryOracle(SubgroupIndexer(curve, G, c.n)), num_counting=12)
print(f'recovered d = {solver.extract(counts)}')  # → 1999171
"
```

## Layout

```
src/
  ecc.py              Classical EC arithmetic (point add, scalar mult, BSGS)
  shor_ecdlp.py       Two-register Shor for ECDLP. Strategy-pattern oracles.
                      Includes Adaptive Counting Precision (t<m) and
                      CF-Lift v2 Extractor (Stern-Brocot convergents).
  grover_ecdlp.py     Grover-based attack (legacy / comparison)
  quantum_ecc.py      IBM/IonQ runners, Aer wrappers, ZNE
  challenges.py       Q-Day Prize challenge curves (4-bit through 30-bit)
  analysis.py         χ², KL divergence, TVD, success probability

scripts/
  submit_18bit.py     Build & submit Shor circuit at chosen (bits, t)
                      Auto-selects best Heron r2 backend by 2Q-error;
                      enables Sampler-side dynamical decoupling + twirling.
  fetch_result.py     Poll IBM job and extract d
  apply_m3.py         Apply M3 readout-error mitigation post-hoc
  quimb_simulate.py   Tensor-network cross-validation (≤6-bit dense)
  agent_planner.py    Read past results, propose next experiment
  agent_loop.py       Autonomous plan→submit→poll→update loop

results/
  shor_*_ibm.json     Hardware run summary + recovered d
  _ibm_*_counts.json  Raw IBM counts (post-job pull)
  *_analysis.md       Step-by-step deep analysis reports

docs/
  22bit_attack_plan.md  Resource projections + execution plan

run_experiment.py     CLI entry point (Grover / Shor / dummy modes)
brief.md              Q-Day Prize submission writeup (2 pages)
AGENT.md              Record of autonomous AI workflow
```

## Algorithm summary

Two-register Shor variant for ECDLP:

1. Prepare counting registers `|j⟩|k⟩` in uniform superposition (Hadamard).
2. Apply controlled point additions: `|j⟩|k⟩|0⟩ → |j⟩|k⟩|jG + kQ⟩`.
3. Measure point register → collapses to some `r₀` on the cyclic group.
4. Apply inverse QFT to `j`, `k`.
5. Measure (j, k); enumerate `(a, b)` lifts via Stern-Brocot continued-fraction
   approximation toward fractions with denominator ≤ n.
6. For each `(a, b)`: candidate `d = (r₀ - a) · b⁻¹ mod n`.
7. Verify: accept only `d_cand · G == Q`.

The verification step is robust to noise: only the true `d` survives the
classical EC scalar-multiply check, so a small number of signal-bearing
shots suffices for recovery.

## Novel contributions

### 1. Adaptive Counting Precision

Standard Shor uses counting-register width `t = m = ⌈log₂ n⌉`. We use `t < m`
to reduce qubit count and circuit depth.

Mathematical threshold for QFT⁻¹ to extract structure: `4ᵗ / n ≥ 1`. For our
22-bit problem (n ≈ 2.1M), `t = 12` gives `4¹² / n ≈ 8`, sufficient with the
v2 extractor. This pushes the per-shot signal density from "would need t = 22
counting qubits" down to "12 suffice".

### 2. Continued-Fraction Lift Extractor v2

When `t < m`, the direct extraction formula `d = (r − j) · k⁻¹ mod n` loses
precision. v2 enumerates ~25 candidates per measured value via:

- Full Stern-Brocot CF convergent walk (every `p/q` with `q ≤ n`)
- Mediants between adjacent convergents (catches non-best approximations)
- Precision-gap-scaled symmetric perturbations
- BSGS-precomputed verifier for O(1) lookup

On the headline 22-bit IBM data: 0 verified hits with v1 (direct + ±2
perturbation) → **12 verified hits at d = 1,999,171** with v2.

### 3. Autonomous AI Agent Workflow

The complete pipeline runs as `agent_planner.py + agent_loop.py`. The planner
distills the strategic reasoning of this submission into a deterministic
policy (climb-on-success, reproduce-on-borderline, diagnose-on-fail). The
loop wraps `plan → submit → poll → update brief.md` with `--dry-run`,
`--max-iter`, and `--budget-cap-shots` safety guards.

## Honest framing

At depth 100K+ on Heron r2 with effective gate fidelity 0.997, the **verification
filter is the load-bearing classical post-processing step** that converts noisy
quantum measurements into a recovered key. We do not claim quantum advantage —
classical BSGS solves 22-bit ECDLP in milliseconds. Bitcoin's 256-bit ECDLP
remains unattainable on near-term hardware (Google Quantum AI 2026-03 estimate:
1,200 logical qubits, 90M Toffoli gates).

What this work does claim: the **largest publicly-reported ECDLP key recovery on
quantum hardware to date** (m = 22), achieved end-to-end by an LLM agent, and a
novel CF-lift v2 extractor that promotes raw measurements that were previously
unrecoverable into successful key recoveries.

See [`results/shor_22bit_t12_analysis.md`](results/shor_22bit_t12_analysis.md)
for the full smoking-gun analysis (P_hit/P_mean = 1.69 sample evidence + v1
vs v2 comparison).

## Citation

If you use this work, please cite via [`CITATION.cff`](CITATION.cff).

## License

[MIT](LICENSE).
