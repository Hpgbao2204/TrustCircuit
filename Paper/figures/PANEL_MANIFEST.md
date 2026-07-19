# TrustCircuit Phase 8 panel manifest

`python scripts/plot_all_results.py` emits twenty-six independent panels. Each panel is a separate 12 x 8 inch vector PDF and 600-dpi PNG (7200 x 4800 pixels). Panel letters are absent so the manuscript/LaTeX layer can add them. No panel combines multiple output files and no plotted point is created by interpolation.

| Panel stem | Source data | Evidence class | Visual question |
|---|---|---|---|
| `fig3a_ablation_throughput` | `results/processed/e2e_ablation_trials.csv` | locally measured; `no_tee` model-calibrated | Throughput distributions, p50 and p95 across six lifecycle ablations. |
| `fig3b_ablation_latency` | `results/processed/e2e_ablation_trials.csv` | locally measured; `no_tee` model-calibrated | End-to-end latency distributions rather than isolated summary points. |
| `fig3c_stage_breakdown` | `results/processed/e2e_stage_by_variant.csv` | locally measured | Absolute and normalized stage composition for every ablation. |
| `fig3d_cost_breakdown` | `results/processed/e2e_ablation_summary.csv` | locally measured | Latency--gas Pareto view with host working set and CPU encodings. |
| `fig4a_constraints` | `results/processed/zk_scaling.csv` | locally measured | R1CS constraints and witness size versus policy complexity. |
| `fig4b_proving_time` | `results/processed/zk_scaling_trials.csv` | locally measured | Per-run proving and verification distributions on a log scale. |
| `fig4c_proof_key_size` | `results/processed/zk_scaling.csv`, `zk_scaling_distribution.csv` | locally measured | Proof/key/resource footprint in a compact point-range view. |
| `fig4d_backend_throughput` | `results/processed/zk_backend_distribution.csv`, `zk_backend_circulation.csv`, `results/summary/zk_schemes_gas.csv` | model-calibrated from measured components | Backend efficiency frontier with proof size and verifier gas. |
| `fig5a_dp_relative_error` | `results/processed/dp_vbs_trials.csv`, `dp_composition.csv` | locally measured + analytical trend | Relative-error distributions and the analytical one-release trend. |
| `fig5b_cumulative_privacy_loss` | `results/processed/dp_composition.csv` | analytical from measured fixed-point cost | Staircase of cumulative privacy loss across releases. |
| `fig5c_rounding_gap` | `results/processed/dp_rounding_margin.csv`, `dp_rounding_summary.csv` | locally measured with analytical oracle | ECDF of conservative fixed-point rounding margins and zero under-report annotation. |
| `fig5d_budget_exhaustion` | `results/processed/budget_exhaustion_trajectory.csv` | locally measured local Hardhat | Remaining budget and accepted-request trajectories. |
| `fig6a_native_vs_vbs_latency` | `results/processed/vbs_performance_summary.csv`, `native_vbs_trials.csv` | locally measured paired | Native/VBS latency scaling with bootstrap confidence bands. |
| `fig6b_vbs_slowdown` | `results/processed/native_vbs_trials.csv` | locally measured paired | Slowdown and incremental process CPU distributions. |
| `fig6c_payload_throughput` | `results/processed/native_vbs_trials.csv` | locally measured paired | Native/VBS payload throughput scaling. |
| `fig6d_enclave_stage_breakdown` | `results/processed/vbs_stage_breakdown.csv` | locally measured enclave TSC | Absolute and normalized VBS stage composition. |
| `fig6e_memory_footprint` | `results/processed/native_vbs_trials.csv` | locally measured paired | Host CPU versus working set with payload size and processor shape. |
| `fig6f_transcript_attestation_overhead` | `results/processed/vbs_attestation_overhead.csv` | locally measured | Transcript, evidence, and validation latency distributions and shares. |
| `fig7a_context_substitution` | `results/processed/attack_binding_matrix.csv` | functional test evidence / analytical layer map | First rejecting layer for each context substitution. |
| `fig7b_tampering_replay` | `results/processed/protocol_attack_latency.csv` | locally measured local Hardhat | Rejection-latency distributions for tampering and replay. |
| `fig7c_concurrency_outcomes` | `results/processed/settlement_concurrency_summary.csv` | locally measured local Hardhat | Accepted/reverted requests and throughput versus concurrency. |
| `fig7d_concurrency_invariants_latency` | `results/processed/settlement_concurrency_trials.csv` | locally measured local Hardhat | Settlement latency and host CPU/RAM saturation; zero invariant violations annotated. |
| `fig8a_lifecycle_capabilities` | `results/processed/comparison_capabilities.csv` | analytical capability definition | Explicit lifecycle capability coverage of five controlled baselines. |
| `fig8b_comparison_latency_throughput` | `results/processed/comparison_trials.csv` | locally measured | Same-workload latency and throughput distributions. |
| `fig8c_comparison_pareto` | `results/processed/comparison_trials.csv`, `comparison_capabilities.csv` | locally measured + analytical coverage score | Gas--latency--coverage Pareto comparison with host working-set encoding. |
| `fig8d_comparison_overhead` | `results/processed/comparison_overhead.csv` | locally measured | Proof, attestation, budget, and other lifecycle overhead contributions. |

## Shared caveats

- VBS/Native Debug x64 measurements include process creation; process startup is reported separately where available. The host process is untrusted and host working set/private bytes are not enclave-only memory.
- Figure 4d is model-calibrated from measured backend/common components; it is not a public-network throughput claim.
- Figure 7 measures local Hardhat same-block contention, not simultaneous execution of 32 hardware enclaves.
- Figure 8 baselines are local feature-matched implementations, not external-system reproductions. Literature values remain separate.
- `results/raw/phase8/testnet/public_testnet_status.json` records that no public testnet measurement was executed.

