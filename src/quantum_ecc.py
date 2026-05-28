"""
Quantum attack on ECDLP using a variant of Shor's algorithm.

Strategy: Implement the quantum phase estimation approach for ECDLP.
Key improvement over the 15-bit prize submission:
  - Verify quantum advantage via statistical separation from /dev/urandom baseline
  - Use ZNE (Zero-Noise Extrapolation) for error mitigation
  - Target >= 30 bits where classical brute-force is non-trivial
"""

import os
import numpy as np
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.circuit.library import QFT
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from typing import Optional


def load_token() -> str:
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            if line.startswith("IBM_QUANTUM_TOKEN="):
                return line.strip().split("=", 1)[1]
    token = os.environ.get("IBM_QUANTUM_TOKEN", "")
    if not token:
        raise ValueError(".env に IBM_QUANTUM_TOKEN が設定されていません")
    return token


def _read_env_kv(key: str) -> str:
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line.startswith(f"{key}="):
                return line.split("=", 1)[1]
    return os.environ.get(key, "")


def load_azure_credentials() -> dict:
    """Load Azure Quantum Workspace credentials from .env.

    Expected .env keys (see https://learn.microsoft.com/azure/quantum):
      AZURE_QUANTUM_RESOURCE_ID  — full Azure resource ID of the Workspace
                                   (looks like /subscriptions/.../resourceGroups/.../
                                    providers/Microsoft.Quantum/Workspaces/...)
      AZURE_QUANTUM_LOCATION     — Azure region (e.g. "japaneast", "westus")

    Authentication uses DefaultAzureCredential — `az login` once in the
    shell, or environment variables (AZURE_TENANT_ID + AZURE_CLIENT_ID +
    AZURE_CLIENT_SECRET) for service-principal auth.

    Returns a dict suitable for ``Workspace(**load_azure_credentials())``.
    """
    resource_id = _read_env_kv("AZURE_QUANTUM_RESOURCE_ID")
    location = _read_env_kv("AZURE_QUANTUM_LOCATION")
    if not resource_id:
        raise ValueError(
            ".env に AZURE_QUANTUM_RESOURCE_ID が設定されていません — "
            "Azure Portal > Quantum Workspace > Overview の Resource ID を貼ってください"
        )
    if not location:
        raise ValueError(
            ".env に AZURE_QUANTUM_LOCATION が設定されていません — "
            "例: japaneast / westus / eastus"
        )
    return {"resource_id": resource_id, "location": location}


def run_on_ionq(circuit: QuantumCircuit, shots: int = 200) -> dict[str, int]:
    """
    Run on IonQ Aria via AWS Braket.
    Cost: $0.30 + $0.03/shot (200 shots ≈ $6.30)
    Requires AWS credentials: aws configure or environment variables.
    """
    from qiskit_braket_provider import BraketProvider
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    provider = BraketProvider()
    backend = provider.get_backend("IonQ Aria 1")
    print(f"    Backend: IonQ Aria 1 (trapped ion, full connectivity)")
    print(f"    Estimated cost: ${0.30 + shots * 0.03:.2f}")

    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    isa_circuit = pm.run(circuit)
    print(f"    Transpiled depth: {isa_circuit.depth()}")

    job = backend.run(isa_circuit, shots=shots)
    print(f"    Job ID: {job.job_id()}  (waiting for result...)")
    result = job.result()
    return result.get_counts()


def run_on_ibm(circuit: QuantumCircuit, shots: int = 4096) -> dict[str, int]:
    """Run on real IBM Quantum hardware (least-busy backend)."""
    from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler

    token = load_token()
    service = QiskitRuntimeService(channel="ibm_quantum_platform", token=token)
    backend = service.least_busy(operational=True, simulator=False,
                                  min_num_qubits=circuit.num_qubits)
    print(f"    Backend: {backend.name}")

    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    isa_circuit = pm.run(circuit)
    print(f"    Transpiled depth: {isa_circuit.depth()}")

    sampler = Sampler(backend)
    job = sampler.run([isa_circuit], shots=shots)
    print(f"    Job ID: {job.job_id()}  (waiting for result...)")
    result = job.result()

    # Extract counts from first PUB result
    pub_result = result[0]
    creg_name = circuit.cregs[0].name
    return pub_result.data.__dict__[creg_name].get_counts()


def build_qpe_circuit(n_bits: int, controlled_add_oracle) -> QuantumCircuit:
    """
    Quantum Phase Estimation circuit for ECDLP.

    Registers:
      - phase_reg: n_bits qubits for phase readout
      - work_reg:  ancilla for EC group operations
    """
    phase_reg = QuantumRegister(n_bits, "phase")
    work_reg = QuantumRegister(n_bits, "work")
    c_phase = ClassicalRegister(n_bits, "c_phase")

    qc = QuantumCircuit(phase_reg, work_reg, c_phase)

    # Superposition on phase register
    qc.h(phase_reg)

    # Initialize work register to |G> (encoded point)
    # (In a real implementation this encodes the EC point in binary)
    qc.x(work_reg[0])  # placeholder: |1> as proxy for generator G

    # Controlled EC scalar multiplication: |j>|G> -> |j>|j*G>
    for i, ctrl in enumerate(phase_reg):
        controlled_add_oracle(qc, ctrl, work_reg, 2**i)

    # Inverse QFT to extract phase
    qc.append(QFT(n_bits, inverse=True), phase_reg)

    qc.measure(phase_reg, c_phase)
    return qc


def dummy_shor_circuit(n_bits: int, secret_k: int) -> QuantumCircuit:
    """
    Simplified Shor-variant circuit for small ECDLP.
    Encodes the secret k into phase via controlled rotations.
    This is used to benchmark noise vs signal in realistic hardware.
    """
    phase_reg = QuantumRegister(n_bits, "phase")
    c_out = ClassicalRegister(n_bits, "c_out")
    qc = QuantumCircuit(phase_reg, c_out)

    qc.h(phase_reg)

    # Encode k as phase: R_k(theta) where theta encodes k/2^n
    for i, qubit in enumerate(phase_reg):
        angle = 2 * np.pi * secret_k / (2**n_bits) * (2**i)
        qc.p(angle, qubit)

    # Inverse QFT
    qc.append(QFT(n_bits, inverse=True), phase_reg)
    qc.measure(phase_reg, c_out)
    return qc


def run_on_simulator(
    circuit: QuantumCircuit,
    shots: int = 8192,
    noise_level: float = 0.0,
) -> dict[str, int]:
    """Run circuit on Aer simulator with optional depolarizing noise."""
    backend = AerSimulator()
    if noise_level > 0:
        from qiskit_aer.noise import depolarizing_error
        noise_model = NoiseModel()
        error = depolarizing_error(noise_level, 1)
        error2 = depolarizing_error(noise_level * 10, 2)
        # Cover both pre-transpile gates (h/p/x/u*) and post-transpile basis
        # gates (sx/rz/x for IBM-like; rx/ry for some Aer paths). Without this,
        # noise registered only on h/p/x silently fails to apply after
        # generate_preset_pass_manager rewrites everything to sx/rz.
        sim_1q = ["sx", "x", "rz", "rx", "ry", "h", "p", "u", "u1", "u2", "u3"]
        sim_2q = ["cx", "cz", "ecr"]
        noise_model.add_all_qubit_quantum_error(error, sim_1q)
        noise_model.add_all_qubit_quantum_error(error2, sim_2q)
        backend = AerSimulator(noise_model=noise_model)

    pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
    isa_circuit = pm.run(circuit)
    job = backend.run(isa_circuit, shots=shots)
    return job.result().get_counts()


def counts_to_candidate_k(counts: dict[str, int], n_bits: int) -> int:
    """Extract most likely k from measurement counts."""
    top_bitstring = max(counts, key=counts.get)
    return int(top_bitstring, 2)


def zero_noise_extrapolation(
    circuit: QuantumCircuit,
    shots: int,
    noise_levels: list[float],
) -> dict[str, int]:
    """
    ZNE: Run at multiple noise levels and extrapolate to zero noise.
    Returns extrapolated counts dict.
    """
    all_probs = []
    n_bits = circuit.num_clbits

    for noise in noise_levels:
        counts = run_on_simulator(circuit, shots=shots, noise_level=noise)
        total = sum(counts.values())
        probs = {k: v / total for k, v in counts.items()}
        all_probs.append(probs)

    # Collect all keys
    all_keys = set()
    for p in all_probs:
        all_keys.update(p.keys())

    # Linear extrapolation to noise=0 for each bitstring
    extrapolated = {}
    for key in all_keys:
        ys = [p.get(key, 0.0) for p in all_probs]
        xs = np.array(noise_levels)
        # Fit linear: y = a*x + b, extrapolate to x=0
        coeffs = np.polyfit(xs, ys, deg=min(1, len(xs) - 1))
        extrapolated[key] = max(0.0, float(np.polyval(coeffs, 0.0)))

    # Normalize and convert back to counts
    total_prob = sum(extrapolated.values())
    return {k: int(v / total_prob * shots) for k, v in extrapolated.items() if v > 0}
