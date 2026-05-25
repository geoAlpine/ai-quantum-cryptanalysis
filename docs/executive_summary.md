# quantum-ecc — Executive Summary

*One-pager for journalists, funders, collaborators, and reviewers.*

## What we did

Two qualitatively different quantum-hardware recoveries of the Elliptic
Curve Discrete Logarithm Problem (ECDLP), built end-to-end by an LLM
agent (Anthropic Claude) directing an autonomous Python pipeline:

**Phase 0 (April 2026)** — Recovered the 22-bit private key
``d = 1,999,171`` on IBM Quantum ``ibm_fez`` using 73 logical qubits
and 124K transpiled two-qubit gates. **+7 algorithmic steps beyond
Lelli's Q-Day Prize Round-1 winning 15-bit submission** (1 BTC, April
2026). MIT-licensed implementation, public at
``github.com/geoAlpine/ai-quantum-cryptanalysis``.

**Phase 1 (May 25, 2026)** — Recovered ``d = 6`` on
``ibm_kingston`` using 15 qubits and 1.2K two-qubit gates,
decoded by a **Hidden-Number-Problem-based cross-shot score** + top-K
verification, **not** by per-shot verification-filter brute force.
*This is the first publicly documented quantum-hardware ECDLP recovery
whose decode does not depend on the verification-filter regime that
all prior published results (including Lelli's prize win and our own
Phase 0) live in.*

## Why both matter

**Phase 0 is the scale record**: a real quantum computation on a real
problem at the largest bit-length so far. It's also a textbook example
of the *verification-filter regime* — a real quantum circuit produces
mostly noise, and a clever classical post-processor finds the right
``d`` by exhaustively checking candidates.

**Phase 1 is the methodology proof**: even at the smallest non-trivial
scale (``n = 7``), we recovered ``d`` using the structural signal from
the quantum measurement distribution itself, with verification used
only to break a single residual symmetry. This is the recovery mode
the Shor literature *describes* but no public hardware result has so
far demonstrated cleanly.

The two results together let us **rename the current Q-Day Prize era**
as the verification-filter era, and propose a sharp criterion
(``d_true`` HNP score rank, score-gap distribution, top-K size relative
to ``n``) for distinguishing future results.

## Why this is unusual

Built and operated by one person (Yosuke Aoki, GeoAlpine LLC) with an
LLM-agent partner over ≈ 4 weeks of part-time work. No academic
affiliation. No prior quantum-hardware experience entering the project.
The implementation, the test suite (≈ 30 tests, CI on GitHub Actions),
the diagnostic tooling (collective-vote test, noisy-Aer prediction,
HNP score search, lattice scaffolding, visualisation), and the writeup
are co-developed with Claude through the Claude Code interface.

This is direct evidence that **frontier AI workflow makes
cryptanalysis-scale research tractable for solo / small-team
operators** — a methodological contribution worth as much attention as
the result itself.

## What this means for cryptography

*Bitcoin is not in immediate danger.* Classical Baby-step / Giant-step
solves 22-bit ECDLP in milliseconds; the smallest Bitcoin-relevant
scale is 256 bits, and the most credible recent resource estimate
(Google Quantum AI 2026-03) puts the threshold at 1 200 logical qubits
and 90 M Toffoli gates.

*But* the boundary that has shifted is not "how big a key can be
attacked" — it's "how do we measure whether a published hardware
recovery actually used quantum information". Phase 1's recovery
methodology is the first one that lets us distinguish the two regimes
on actual hardware, with a one-command reproduction from this
repository.

## What's next

- Submit the work as an arXiv preprint (Section 5.5 of the outline is
  finalised with the actual Phase 1 numbers).
- Co-author outreach to Japanese academic groups for IBM Quantum
  Credits access (current open-plan budget is 10 min / 28 days).
- Phase 2 hardware datapoint at ``m ≥ 5`` once the iterative + dense
  oracle variant clears the ``t > m + ~2`` wraparound. Validate on
  ``ibm_kingston`` noise model first, submit on real hardware second.
- Continue the public-development loop (all code MIT, all results
  bundled with their counts files in the repository) so the field can
  build on the methodology rather than relitigate it.

## Quick links

- Phase 0 (22-bit) writeup: ``brief.md``
- Phase 1 (4-bit) writeup: README "Phase 1 — signal-regime recovery"
- Methodology paper outline: ``docs/honest_framing_preprint_outline.md``
- Full timeline: ``docs/PROJECT_TIMELINE.md``
- Repository: ``github.com/geoAlpine/ai-quantum-cryptanalysis``
- Contact: info@geoalpine.net
