# TrustCircuit VBS panel manifest

`python scripts/plot_all_results.py` emits every panel independently as a
12 x 8 inch vector PDF and a 600-dpi PNG preview. The PNG canvases are exactly
7200 x 4800 pixels. Panel letters are intentionally absent because LaTeX adds
them. Plots use raw observations or unsmoothed processed summaries; no values
are interpolated, smoothed, or replaced to make a trend appear.

| Panel files (`.pdf` + `.png`) | Source data | Producer | Description | Intended manuscript placement and subcaption |
|---|---|---|---|---|
| `fig3a_ablation_throughput` | `results/processed/e2e_ablation_summary.csv` | `plot_all_results.py::fig3` | Mean throughput with one-standard-deviation ranges on a log scale for six lifecycle ablations. | Figure 3a, main - End-to-end throughput across ablations. |
| `fig3b_ablation_latency` | `results/processed/e2e_ablation_summary.csv` | `plot_all_results.py::fig3` | Mean end-to-end latency with one-standard-deviation ranges; the no-TEE point is model-calibrated. | Figure 3b, main - End-to-end latency across ablations. |
| `fig3c_stage_breakdown` | `results/processed/e2e_stage_breakdown.csv` | `plot_all_results.py::fig3` | Stacked mean latency of access, budget, VBS, proof, settlement, and audit in the full path. | Figure 3c, main - Full-pipeline stage latency. |
| `fig3d_cost_breakdown` | `results/processed/e2e_gas_breakdown.csv` | `plot_all_results.py::fig3` | Local-Hardhat gas attributed to access, budget, proof setup, atomic settlement, and audit. | Figure 3d, main - Gas and settlement cost breakdown. |
| `fig4a_constraints` | `results/processed/zk_scaling.csv` | `plot_all_results.py::fig4` | Exact R1CS constraint counts for 1, 2, 4, 6, 8, and 10 policy rules. | Figure 4a, main - Constraints versus policy rules. |
| `fig4b_proving_time` | `results/processed/zk_scaling.csv` | `plot_all_results.py::fig4` | Groth16 mean proving time with one-standard-deviation ranges after warm-up. | Figure 4b, main - Proving time versus policy rules. |
| `fig4c_proof_key_size` | `results/processed/zk_scaling.csv` | `plot_all_results.py::fig4` | Observed proof-bundle points and proving-key growth; proof-size points are not smoothed. | Figure 4c, appendix - Proof and proving-key size. |
| `fig4d_backend_throughput` | `results/processed/zk_backend_circulation.csv` | `plot_all_results.py::fig4` | Full-circulation throughput computed from separately measured common-path and backend timings. | Figure 4d, appendix - Throughput across proof backends. |
| `fig5a_dp_relative_error` | `results/processed/dp_error_summary.csv` | `plot_all_results.py::fig5` | Mean relative error with one-standard-deviation ranges over 30 enclave releases per epsilon. | Figure 5a, main - DP relative error versus epsilon. |
| `fig5b_cumulative_privacy_loss` | `results/processed/dp_composition.csv` | `plot_all_results.py::fig5` | Unsmoothed staircase of conservative privacy charge across 1-32 releases. | Figure 5b, main - Cumulative privacy loss under repeated releases. |
| `fig5c_rounding_gap` | `results/processed/dp_rounding_margin.csv` | `plot_all_results.py::fig5` | ECDF of 96 conservative margins measured around 48 fixed-point boundaries. | Figure 5c, appendix - Conservative fixed-point rounding-margin distribution. |
| `fig5d_budget_exhaustion` | `results/processed/budget_exhaustion_trajectory.csv` | `plot_all_results.py::fig5` | Staircases for remaining budget and cumulative accepted requests at four epsilon values. | Figure 5d, main - Budget exhaustion under repeated queries. |
| `fig6a_native_vs_vbs_latency` | `results/raw/phase8/native_vbs_performance.csv`; `results/processed/vbs_performance_summary.csv` | `plot_all_results.py::fig6` | Paired median Native and VBS Enclave process latency with empirical 2.5-97.5 percentile bands. | Figure 6a, main - Native versus VBS Enclave latency. |
| `fig6b_vbs_slowdown` | `results/raw/phase8/native_vbs_performance.csv`; `results/processed/vbs_performance_summary.csv` | `plot_all_results.py::fig6` | Paired VBS/Native slowdown median and empirical percentile band. | Figure 6b, main - VBS slowdown relative to Native. |
| `fig6c_payload_throughput` | `results/raw/phase8/native_vbs_performance.csv`; `results/processed/vbs_performance_summary.csv` | `plot_all_results.py::fig6` | Native and VBS Enclave payload throughput medians with empirical percentile bands. | Figure 6c, main - Payload throughput. |
| `fig6d_enclave_stage_breakdown` | `results/processed/vbs_stage_breakdown.csv` | `plot_all_results.py::fig6` | Stacked enclave TSC timing for decrypt, aggregate, DP, transcript, and evidence generation; DP is explicitly zero because paired runs disable noise. | Figure 6d, main - Enclave stage-level latency. |
| `fig6e_memory_footprint` | `results/processed/vbs_performance_summary.csv` | `plot_all_results.py::fig6` | Native and VBS host peak RSS medians with empirical percentile ranges. | Figure 6e, appendix - Host-process memory footprint. |
| `fig6f_transcript_attestation_overhead` | `results/processed/vbs_attestation_overhead.csv` | `plot_all_results.py::fig6` | Thirty-sample distributions for transcript hashing, evidence generation, and external validation at the largest payload, with mean share of validated VBS wall time. | Figure 6f, main - Transcript and attestation overhead. |
| `fig7a_context_substitution` | `results/processed/attack_binding_matrix.csv`; `results/raw/phase8/attack_binding_matrix_config.json` | `plot_all_results.py::fig7` | Heatmap locating the first rejecting layer for 15 context-substitution variants. | Figure 7a, main - Context binding and first rejection layer. |
| `fig7b_tampering_replay` | `results/processed/protocol_attack_latency.csv` | `plot_all_results.py::fig7` | Thirty-sample rejection-latency distributions for transcript, evidence, staleness, proof, and replay attacks. | Figure 7b, appendix - Tampering and replay rejection latency. |
| `fig7c_concurrency_outcomes` | `results/processed/settlement_concurrency_summary.csv` | `plot_all_results.py::fig7` | Mean accepted and reverted requests over 30 same-block trials at each concurrency. | Figure 7c, main - Settlement outcomes under concurrency. |
| `fig7d_concurrency_invariants_latency` | `results/processed/settlement_concurrency_trials.csv` | `plot_all_results.py::fig7` | Thirty-sample settlement-latency distributions at concurrency 1, 2, 4, 8, 16, and 32. | Figure 7d, main - Settlement latency under concurrency. |

## Evidence audit and placement recommendation

| Panel | Evidence classification | Recommended location | Audit judgment |
|---|---|---|---|
| 3a | Model-calibrated (contains one calibrated no-TEE point) | Main paper | Suitable when the no-TEE marker and local-chain scope remain explicit. |
| 3b | Model-calibrated (contains one calibrated no-TEE point) | Main paper | Suitable with the same caveat as 3a. |
| 3c | Measured | Main paper | Suitable; directly decomposes the full measured path. |
| 3d | Measured | Main paper | Suitable for relative local gas, not public fee claims. |
| 4a | Measured | Main paper | Suitable; deterministic compiler output. |
| 4b | Measured | Main paper | Suitable; 12 repetitions after two warm-ups. |
| 4c | Measured | Appendix | Useful supporting artifact-size evidence. |
| 4d | Model-calibrated | Appendix | Keep out of primary throughput claims because components are summed. |
| 5a | Measured | Main paper | Suitable for the tested bounded-MEAN workload only. |
| 5b | Analytical | Main paper | Suitable when described as RDP/fixed-point accounting, not an empirical privacy guarantee. |
| 5c | Measured with analytical oracle | Appendix | Suitable evidence of conservatism at fixed-point boundaries. |
| 5d | Measured | Main paper | Suitable local-ledger exhaustion trace. |
| 6a | Measured | Main paper | Suitable paired baseline; Debug x64 and process-startup scope must be stated. |
| 6b | Measured | Main paper | Suitable paired slowdown evidence under the same scope. |
| 6c | Measured | Main paper | Suitable paired payload-throughput evidence. |
| 6d | Measured | Main paper | Suitable structured enclave-stage evidence; DP zero is disclosed. |
| 6e | Measured | Appendix | Host RSS only; no separate secure-kernel/enclave working-set counter. |
| 6f | Measured | Main paper | Suitable; 30 observations per stage at the largest payload. |
| 7a | Functional-test evidence | Main paper | Suitable to show first rejection, not later-layer behavior. |
| 7b | Measured | Appendix | Useful local rejection-cost evidence; not a security-strength metric. |
| 7c | Measured | Main paper | Suitable local same-block budget-contention evidence. |
| 7d | Measured | Main paper | Suitable; zero invariant violations belong in caption/table, not as a flat plotted line. |

## Scope and substitutions

- Figures 6a-6c now use the real `TrustCircuitNative.exe` baseline. The legend
  labels are exactly `Native` and `VBS Enclave`; no Python reference appears.
  Both executables use x64 C++20, toolset v143, the same runtime configuration,
  shared TCVBSDS1 parsing/aggregation code, identical encrypted inputs, and the
  same response fields used for parity checks.
- The paired processor runs use Debug x64 and include process creation. They do
  not claim optimized Release or persistent-host latency.
- Figure 6e reports Native-process and VBS-host RSS. Windows did not expose a
  separate enclave working-set counter to this harness.
- Figures 7c-7d measure same-block local-Hardhat settlement contention. They do
  not claim simultaneous execution of 32 hardware enclaves.
- Figure 4d is model-calibrated, not a public-network throughput measurement.
- `results/raw/phase8/testnet/public_testnet_status.json` records that no public
  testnet was run because the repository has no RPC/account configuration. No
  testnet value was fabricated.
