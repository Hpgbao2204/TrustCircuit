# Claim-to-evidence table for the Phase 8 VBS revision

Every claim below is scoped to the local machine/configuration recorded in the cited raw JSON. A plot never treats an interpolated point as a measured run.

| Candidate claim | Exact evidence | Panel(s) | Evidence class and caveat |
|---|---|---|---|
| Lifecycle ablations have distinct throughput distributions. | `results/raw/phase8/e2e_ablation.csv`; `results/processed/e2e_ablation_trials.csv` | 3a | Locally measured, 6 variants × 30 retained runs; `no_tee` is model-calibrated from measured components. |
| Lifecycle ablations have distinct end-to-end latency distributions. | `results/raw/phase8/e2e_ablation.csv`; `results/processed/e2e_ablation_trials.csv` | 3b | Same local scope and caveat as 3a; deployment is excluded. |
| Stage composition differs across every ablation. | `results/processed/e2e_stage_by_variant.csv` | 3c | Locally measured stage timings; absent stages are zero by design, not imputed. |
| Latency--gas trade-offs correlate with host resource footprint. | `results/processed/e2e_ablation_summary.csv` | 3d | Local-Hardhat gas and host-process counters; no public fee or enclave-memory claim. |
| Constraints and witness size grow with policy complexity. | `results/raw/phase8/zk_scaling.csv`; `results/raw/phase8/zk_scaling_runs.csv` | 4a | Locally measured/compiler-derived for 1, 2, 4, 6, 8, 10 rules. |
| Proving and verification latency distributions are measurable after warm-up. | `results/raw/phase8/zk_scaling_runs.csv`; `results/processed/zk_scaling_distribution.csv` | 4b | Locally measured, 30 retained per rule count after 2 warm-ups. |
| Proof/key/prover-resource footprint is observable per policy size. | `results/processed/zk_scaling.csv`; `zk_scaling_distribution.csv` | 4c | Locally measured; proof/key sizes are not smoothed. |
| Backend efficiency differs across Groth16, PLONK, and fflonk. | `results/raw/phase8/zk_backend_runs.csv`; `results/summary/zk_schemes_gas.csv`; `results/processed/zk_backend_circulation.csv` | 4d | Backend timings/gas locally measured; full-circulation throughput model-calibrated from measured components. |
| Relative error changes with epsilon for the tested bounded MEAN workload. | `results/raw/phase8/dp_vbs.csv`; `results/processed/dp_vbs_trials.csv` | 5a | Locally measured, 6 epsilon values × 30 retained VBS releases; no arbitrary-dataset generalization. |
| Conservative fixed-point privacy charge accumulates under repeated releases. | `results/raw/phase8/dp_composition.csv` | 5b | Analytical RDP composition from measured conservative per-release cost. |
| Fixed-point rounding does not under-report at sampled boundaries. | `results/raw/phase8/dp_rounding_boundaries.csv`; `results/processed/dp_rounding_summary.csv` | 5c | Locally measured with analytical oracle; 96 boundary requests, zero under-reports. |
| Budget exhaustion rejects releases without changing remaining budget. | `results/raw/phase8/budget_exhaustion.csv`; `results/processed/budget_exhaustion_trajectory.csv` | 5d | Locally measured local-Hardhat ledger trajectories. |
| Native and VBS produce identical deterministic result/hash outputs. | `results/raw/phase8/native_vbs_performance.csv`; `results/processed/native_vbs_trials.csv` | 6a--6c | Locally measured paired, 6 payload sizes × 30 retained; exact parity is a deterministic check. |
| VBS slowdown and incremental CPU cost vary with payload. | `results/processed/native_vbs_trials.csv` | 6b | Locally measured paired; process creation is included in wall time and reported separately. |
| Payload throughput scales differently for Native and VBS. | `results/processed/native_vbs_trials.csv` | 6c | Locally measured paired; no Python baseline. |
| VBS stage timing can be decomposed. | `results/processed/vbs_stage_breakdown.csv` | 6d | Locally measured enclave TSC; DP is intentionally disabled in parity runs. |
| Host CPU and working-set footprint are observable. | `results/processed/native_vbs_trials.csv` | 6e | Locally measured host-process counters only, never enclave-only memory. |
| Transcript, evidence, and external validation have distinct latency distributions. | `results/processed/vbs_attestation_overhead.csv` | 6f | Locally measured at largest payload; application timing is not attestation evidence. |
| Context substitutions are first rejected at identifiable protocol layers. | `results/raw/phase8/attack_binding_matrix.csv`; `results/processed/attack_binding_matrix.csv` | 7a | Functional test evidence/analytical layer map; blank later layers are not acceptance claims. |
| Tampering, stale evidence, proof tampering, and replay reject consistently. | `results/raw/phase8/protocol_attacks.csv`; `results/processed/protocol_attack_latency.csv` | 7b | Locally measured, 12 attack cases × 30 retained trials; rejection latency is operational overhead. |
| Same-block contention yields accepted/reverted outcomes and throughput changes. | `results/raw/phase8/settlement_concurrency.csv`; `results/processed/settlement_concurrency_summary.csv` | 7c | Locally measured local Hardhat, 6 levels × 30 retained trials; not simultaneous enclave execution. |
| Settlement latency and host saturation are measurable with zero budget invariant violations observed. | `results/processed/settlement_concurrency_trials.csv` | 7d | Locally measured; zero is an annotation/table result, not a plotted flat curve. |
| Five neutral baselines expose different lifecycle capabilities. | `results/raw/phase8/comparison_capabilities.csv`; `Paper/figures/COMPARISON_METHODOLOGY.md` | 8a | Analytical capability definition; baselines are local proxies, not external-system reproductions. |
| End-to-end latency and throughput differ across the five controlled configurations. | `results/raw/phase8/comparison_performance.csv`; `results/processed/comparison_trials.csv` | 8b | Locally measured, 5 configurations × 30 retained runs after one warm-up, same 1,000-row workload. |
| Gas--latency trade-offs vary with explicit capability coverage. | `results/processed/comparison_trials.csv`; `comparison_capabilities.csv` | 8c | Local measurements plus analytical capability score; local gas only. |
| Proof, attestation, budget, and other lifecycle contributions differ by configuration. | `results/processed/comparison_overhead.csv` | 8d | Locally measured component windows; omitted components are deliberate baseline scope. |

## Evidence-class inventory

| Class | Current files/uses |
|---|---|
| Locally measured | All `*_trials.csv`, local Hardhat receipt CSVs, `zk_*_runs.csv`, Native/VBS raw rows, comparison rows. |
| Analytical | `dp_composition.csv`, capability matrix, fixed-point oracle columns and annotations. |
| Model-calibrated | `zk_backend_circulation.csv`, `no_tee` ablation rows and any explicitly marked component sums. |
| Literature-reported | Legacy/SOTA comparison tables outside Figure 8; never merged into local distributions. |

