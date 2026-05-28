"""IBM Quantum cloud + backend availability check.

Use before submitting jobs: tells you in <30 seconds whether IBM is up
and which Heron r2 backends are processing jobs. The 2026-05-28 session
hit silent hangs on flaky IBM responses — running this first would have
caught the outage immediately.

Usage:
    python scripts/ibm_status.py                 # check all standard backends
    python scripts/ibm_status.py --backend ibm_kingston
"""
from __future__ import annotations

import argparse
import socket
import sys
import time

# Belt-and-braces global timeout — many qiskit-ibm-runtime internals
# don't honour per-call timeouts. socket.setdefaulttimeout makes any
# urllib3 / requests call abort instead of hanging indefinitely (the
# failure mode we hit on 2026-05-28 when IBM Cloud was flaky).
socket.setdefaulttimeout(20.0)

from quantum_ecc import load_token
from qiskit_ibm_runtime import QiskitRuntimeService


_DEFAULT_BACKENDS = ["ibm_kingston", "ibm_fez", "ibm_marrakesh"]


def check_one(svc, name: str, timeout_s: float = 15.0) -> dict:
    """Return a status dict for one backend. Times out fast on network hangs."""
    out = {"name": name, "ok": False, "elapsed": None,
           "pending_jobs": None, "operational": None, "error": None}
    t0 = time.time()
    try:
        backend = svc.backend(name)
        status = backend.status()
        out["ok"] = True
        out["pending_jobs"] = status.pending_jobs
        out["operational"] = status.operational
        out["status_msg"] = getattr(status, "status_msg", "")
        out["num_qubits"] = backend.num_qubits
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:100]}"
    out["elapsed"] = round(time.time() - t0, 2)
    if out["elapsed"] > timeout_s and not out["ok"]:
        out["error"] = (out["error"] or "") + f" (slow: {out['elapsed']}s)"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="append",
                    help="Specific backend to check (can repeat). "
                         "Default: all 3 standard Heron r2 machines.")
    ap.add_argument("--timeout", type=float, default=15.0,
                    help="Per-backend timeout in seconds (default 15)")
    args = ap.parse_args()

    backends = args.backend or _DEFAULT_BACKENDS

    print("=== IBM Quantum status ===")
    t0 = time.time()
    try:
        svc = QiskitRuntimeService(
            channel="ibm_quantum_platform", token=load_token()
        )
    except Exception as e:
        print(f"  Service init FAILED: {type(e).__name__}: {e}")
        sys.exit(1)
    print(f"  service init: {time.time() - t0:.1f}s\n")

    print(f"{'Backend':<18} {'ok':>3} {'pending':>8} {'op':>4} "
          f"{'qubits':>6} {'elapsed(s)':>10}  notes")
    print("-" * 80)
    any_ok = False
    for name in backends:
        r = check_one(svc, name, timeout_s=args.timeout)
        if r["ok"]:
            any_ok = True
            tag = "✓" if r["operational"] else "·"
            print(f"  {r['name']:<16} {tag:>3} "
                  f"{r['pending_jobs']:>8} {str(r['operational']):>4} "
                  f"{r['num_qubits']:>6} {r['elapsed']:>10}  "
                  f"{r.get('status_msg','')}")
        else:
            print(f"  {r['name']:<16} {'✗':>3} {'?':>8} {'?':>4} "
                  f"{'?':>6} {r['elapsed']:>10}  {r['error']}")
    print()
    if any_ok:
        print("OK: at least one backend responsive.")
        sys.exit(0)
    else:
        print("FAIL: no backend responded. IBM cloud may be down.")
        sys.exit(2)


if __name__ == "__main__":
    main()
