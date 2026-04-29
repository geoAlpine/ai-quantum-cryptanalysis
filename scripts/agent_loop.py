"""
Autonomous self-improvement loop for ECDLP cryptanalysis.

Driven by `agent_planner.py` proposals, executes:
  1. Planner reads past results, proposes next experiment
  2. (Optional) Human confirms (interactive) or --yes for autonomous
  3. Submit job to IBM Quantum via submit_18bit.py
  4. Poll for completion via fetch_result.py
  5. Re-run planner, update brief.md if new record

Built-in safety:
  - --dry-run: only plan, never submit
  - --max-iter N: stop after N iterations (default 1, prevents runaway)
  - --budget-cap-shots N: refuse experiments exceeding shot budget

Usage:
    # Just see what the agent would do next (no QPU spent)
    python scripts/agent_loop.py --dry-run

    # Single iteration with confirmation
    python scripts/agent_loop.py

    # Autonomous 3-iteration loop (only do this if you trust the planner)
    python scripts/agent_loop.py --yes --max-iter 3 --budget-cap-shots 50000
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from agent_planner import load_trials, propose_next, project_resources


def banner(text: str) -> None:
    print()
    print("=" * 70)
    print(f"  {text}")
    print("=" * 70)


def confirm(prompt: str, default_yes: bool) -> bool:
    if default_yes:
        print(f"{prompt} [auto-yes]")
        return True
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in ("y", "yes")


def run_subprocess(cmd: list[str]) -> int:
    """Run subprocess, stream output, return exit code."""
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd).returncode


def find_pending_metadata(bits: int, t: int) -> str | None:
    """Locate the _pending_*_ibm.json file submit_18bit.py just wrote."""
    path = f"results/_pending_{bits}bit_t{t}_ibm.json"
    return path if os.path.exists(path) else None


def update_brief_headline_if_new_record(trials: list, new_trial_path: str) -> None:
    """If the new trial set a new max-bits success record, update brief.md headline."""
    if not os.path.exists(new_trial_path):
        return
    with open(new_trial_path) as f:
        new = json.load(f)
    if not new.get("success"):
        return
    new_bits = new.get("bit_length")
    prior_max = max((t.bits for t in trials if t.success), default=0)
    if new_bits <= prior_max:
        return

    brief_path = "brief.md"
    if not os.path.exists(brief_path):
        return
    with open(brief_path) as f:
        content = f.read()
    # Naive headline replace: find "X-bit ECDLP" pattern in title line
    import re
    pattern = re.compile(r"Recovery of \d+-bit ECDLP")
    new_content, n_replacements = pattern.subn(
        f"Recovery of {new_bits}-bit ECDLP", content)
    if n_replacements:
        with open(brief_path, "w") as f:
            f.write(new_content)
        print(f"  → Updated brief.md headline to '{new_bits}-bit ECDLP'")


def iterate(args, iteration: int) -> bool:
    """One iteration of plan → submit → poll → analyze. Returns True if continued."""
    banner(f"Iteration {iteration} — agent planning")

    trials = load_trials()
    proposal = propose_next(trials)

    print(f"\n  Past trials ({len(trials)}):")
    for tr in trials:
        m = (tr.bits if tr.bits not in [16, 17, 18, 24] else "?")
        marker = "✓" if tr.success else "✗"
        print(f"    {marker} {tr.bits}-bit t={tr.t} shots={tr.shots} hits={tr.verified_hits}")

    print(f"\n  Reasoning:")
    for r in proposal.get("reasoning", []):
        print(f"    • {r}")

    if proposal["action"] == "no_op":
        print("\n  Agent has no further proposal. Done.")
        return False

    cmd_str = proposal["command"]
    print(f"\n  Proposed: {cmd_str}")

    # Budget check
    shots = proposal.get("shots", 0)
    if shots > args.budget_cap_shots:
        print(f"  ✗ REFUSED: proposed shots ({shots}) > cap ({args.budget_cap_shots})")
        return False

    if args.dry_run:
        print("\n  --dry-run: stopping before submission.")
        return False

    if not confirm("\n  Proceed with submission?", args.yes):
        print("  User declined.")
        return False

    banner(f"Iteration {iteration} — submitting")
    bits = proposal["bits"]
    t = proposal["t"]
    cmd_parts = cmd_str.split() + ["--backend", args.backend]
    rc = run_subprocess(cmd_parts)
    if rc != 0:
        print(f"  ✗ submission failed (exit {rc})")
        return False

    # Find pending file
    pending = find_pending_metadata(bits, t)
    if not pending:
        print(f"  ✗ Could not find _pending file for bits={bits} t={t}")
        return False

    banner(f"Iteration {iteration} — polling job")
    rc = run_subprocess(["python", "scripts/fetch_result.py", pending])
    if rc != 0:
        print(f"  ✗ polling failed (exit {rc})")
        return False

    # Update brief.md if new record
    result_path = f"results/shor_{bits}bit_t{t}_{shots}shots_ibm.json"
    if os.path.exists(result_path):
        update_brief_headline_if_new_record(trials, result_path)

    print(f"  ✓ Iteration {iteration} complete")
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="Plan only, no submission")
    p.add_argument("--yes", action="store_true",
                   help="Auto-confirm submissions (autonomous mode)")
    p.add_argument("--max-iter", type=int, default=1,
                   help="Maximum iterations (default 1)")
    p.add_argument("--budget-cap-shots", type=int, default=20000,
                   help="Refuse experiments above this shot count (default 20K)")
    p.add_argument("--backend", default="ibm_fez")
    args = p.parse_args()

    for i in range(1, args.max_iter + 1):
        cont = iterate(args, i)
        if not cont:
            break
        if i < args.max_iter:
            print(f"\n  Sleeping 30s before next iteration...")
            time.sleep(30)

    banner("Loop complete")


if __name__ == "__main__":
    main()
