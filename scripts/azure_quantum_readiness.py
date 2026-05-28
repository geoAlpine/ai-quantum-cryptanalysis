"""Azure Quantum readiness check.

Run before the first submission to confirm that:
  - azure-quantum SDK is importable
  - .env contains the required keys
  - az CLI login is active (token cached)
  - the configured Workspace is reachable
  - the Quantinuum targets are visible

Prints the next concrete step if any check fails.

Usage:
    python scripts/azure_quantum_readiness.py
"""
from __future__ import annotations

import os
import sys


def _check(label: str, fn):
    print(f"  {label}... ", end="", flush=True)
    try:
        msg = fn()
        print(f"OK  ({msg})" if msg else "OK")
        return True
    except Exception as e:
        print(f"MISSING — {type(e).__name__}: {str(e)[:120]}")
        return False


def main() -> int:
    print("=== Azure Quantum readiness ===\n")

    ok = True

    print("1. SDK")
    ok &= _check("azure.quantum imports", lambda: __import__("azure.quantum"))
    ok &= _check("azure.quantum.qiskit imports",
                  lambda: __import__("azure.quantum.qiskit",
                                      fromlist=["AzureQuantumProvider"]))
    ok &= _check("azure.identity imports", lambda: __import__("azure.identity"))

    print("\n2. .env credentials")
    from quantum_ecc import _read_env_kv
    resource_id = _read_env_kv("AZURE_QUANTUM_RESOURCE_ID")
    location = _read_env_kv("AZURE_QUANTUM_LOCATION")
    if resource_id:
        rid_short = resource_id.split("/")[-1] if "/" in resource_id else resource_id
        print(f"  AZURE_QUANTUM_RESOURCE_ID … OK  (...{rid_short})")
    else:
        print(f"  AZURE_QUANTUM_RESOURCE_ID … MISSING")
        ok = False
    if location:
        print(f"  AZURE_QUANTUM_LOCATION    … OK  ({location})")
    else:
        print(f"  AZURE_QUANTUM_LOCATION    … MISSING")
        ok = False

    print("\n3. Azure auth (DefaultAzureCredential)")
    try:
        from azure.identity import DefaultAzureCredential
        cred = DefaultAzureCredential()
        token = cred.get_token("https://quantum.microsoft.com/.default")
        # token has .expires_on, .token
        print(f"  CLI / env-var auth …. OK  (token len {len(token.token)} chars)")
    except Exception as e:
        print(f"  CLI / env-var auth … MISSING — {type(e).__name__}")
        ok = False

    if not ok:
        print()
        print("Next steps:")
        if not resource_id or not location:
            print("  - Create Azure Quantum Workspace at https://portal.azure.com")
            print("  - Copy resource_id (Overview > Properties) and location into .env")
        print("  - Run `az login` (install via `brew install azure-cli` first if needed)")
        print("  - Re-run this script")
        return 1

    print("\n4. Workspace reachability")
    try:
        from azure.quantum import Workspace
        ws = Workspace(resource_id=resource_id, location=location)
        targets = list(ws.get_targets())
        names = [getattr(t, "name", str(t)) for t in targets]
        quantinuum_targets = [n for n in names if "quantinuum" in n.lower()]
        print(f"  Workspace reachable … OK  ({len(targets)} targets total)")
        print(f"  Quantinuum targets visible:")
        for n in quantinuum_targets[:8]:
            print(f"    - {n}")
    except Exception as e:
        print(f"  Workspace reachable … FAILED — {type(e).__name__}: {str(e)[:150]}")
        return 2

    print("\nAll green. You can submit:")
    print("  python scripts/azure_quantum_submit.py --bits 4 --t 6 \\")
    print("    --oracle dense --extractor hnp --target h2-1sc --shots 16")
    print("  (start with h2-1sc — the FREE syntax checker)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
