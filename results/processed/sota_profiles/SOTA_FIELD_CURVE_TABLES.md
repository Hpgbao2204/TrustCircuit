# Field-scale SOTA curve tables

The five external systems are minimal emulations of features described in the paper's Related Work table. Values measure this common 48-field contract, not the source implementations' runtime or security.

## Units

- `fields/request`: distinct protocol fields evaluated or mutated in one request.
- `checks/request`: field-layer enforcement checks accumulated in one request.
- `events/1,000 requests`: unique field-layer controls activated across a batch of 1,000 requests with repeated mutation attempts; repeated hits to the same field are deduplicated per request.
- Ribbons in both figures show the 10th-90th percentile across seeded field orders or mutation batches.

## Summary

| Profile | Year | Bound fields | Checks/request | Median layers/bound field | Unique control events/1,000 requests at 64 attempts |
| --- | --- | --- | --- | --- | --- |
| ProMark | 2024 | 31 | 68 | 2.0 | 50,322 |
| Veracruz | 2023 | 26 | 60 | 2.0 | 44,369 |
| VLDP | 2025 | 21 | 48 | 2.0 | 35,532 |
| VerifBFL | 2025 | 34 | 78 | 2.0 | 57,730 |
| VPrivKV | 2026 | 27 | 62 | 2.0 | 45,894 |
| TC-Lite | 2026 | 30 | 65 | 2.0 | 48,094 |
| TC-Protected | 2026 | 42 | 120 | 3.0 | 88,803 |
| TC-Full | 2026 | 48 | 180 | 3.5 | 133,240 |

## Reconstruction boundary

| Profile | Year | Source | Emulated slice | Explicit omissions |
| --- | --- | --- | --- | --- |
| ProMark | 2024 | [Hoang et al., IEEE TDSC](https://doi.org/10.1109/TDSC.2024.3478049) | campaign policy, participant binding, PoC relation, replay token, ledger audit | Fabric deployment, Pedersen/ECIES/MPC workflow, original PoC implementation |
| Veracruz | 2023 | [Brossard et al., IEEE TCC](https://arxiv.org/abs/2205.03322) | global policy, principals, transcript integrity, isolated-runtime attestation | Nitro/CCA/seL4 runtimes, TLS provisioning, proxy attestation service |
| VLDP | 2025 | [Bontekoe et al., PoPETs](https://petsymposium.org/popets/2025/popets-2025-0076.php) | authenticated LDP input, mechanism parameters, randomized output relation | Groth16 circuit, shuffle deployment, original cryptographic implementation |
| VerifBFL | 2025 | [Bellachia et al.](https://arxiv.org/abs/2501.04319) | training-task identity, model-update proof, round state, blockchain audit | federated training, Nova/IVC execution, Chainlink, IPFS and PBFT network |
| VPrivKV | 2026 | [Zhou et al., IEEE TIFS](https://doi.org/10.1109/TIFS.2025.3639964) | joint key sampling, interactive perturbation verification, enhanced ZK relation | coin-flipping transport, full PrivKV analytics and original ZK implementation |
| TC-Lite | 2026 | TrustCircuit deployment profile | encrypted authorization, canonical request fields, request state and audit | confidential execution, DP accounting and VCP proof |
| TC-Protected | 2026 | TrustCircuit deployment profile | TC-Lite plus attested computation, conservative privacy cost and budget state | VCP proof and proof-bound nullifier |
| TC-Full | 2026 | TrustCircuit deployment profile | request, attestation and proof binding with cumulative budget and atomic settlement | this emulator does not execute the real VBS, Groth16 or Solidity stack |

Interpretation boundary: a larger value means that the common emulator invokes more independent enforcement layers over the selected fields. It is not a normalized security score and must not be presented as source-system throughput, proof cost, or cryptographic strength.
