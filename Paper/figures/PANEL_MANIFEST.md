# TrustCircuit VBS panel manifest

Every entry is emitted independently as a vector PDF and a 300-dpi PNG preview
by `python scripts/plot_all_results.py`. Panel letters are intentionally absent
from the artwork because LaTeX supplies them.

| Panel files (`.pdf` + `.png`) | Source data | Producer | Description | Manuscript placement and subcaption |
|---|---|---|---|---|
| `fig3a_ablation_throughput` | `results/processed/e2e_ablation_summary.csv` | `plot_all_results.py::fig3` | Throughput of the six measured/model-calibrated lifecycle ablations on a log scale. | Figure 3a — End-to-end throughput across ablations. |
| `fig3b_ablation_latency` | `results/processed/e2e_ablation_summary.csv` | `plot_all_results.py::fig3` | Mean circulation latency for baseline, access-only, no-budget, no-ZK, no-TEE, and full variants. | Figure 3b — End-to-end latency across ablations. |
| `fig3c_stage_breakdown` | `results/processed/e2e_stage_breakdown.csv` | `plot_all_results.py::fig3` | Mean latency contribution of access, budget, VBS, proof, settlement, and audit stages in the full path. | Figure 3c — Full-pipeline stage latency. |
| `fig3d_cost_breakdown` | `results/processed/e2e_gas_breakdown.csv` | `plot_all_results.py::fig3` | Local-Hardhat gas attributed to access, budget, proof setup, atomic settlement, and audit operations. | Figure 3d — Gas/settlement cost breakdown. |
| `fig4a_constraints` | `results/processed/zk_scaling.csv` | `plot_all_results.py::fig4` | R1CS constraint growth for 1, 2, 4, 6, 8, and 10 policy rules. | Figure 4a — Constraints versus policy rules. |
| `fig4b_proving_time` | `results/processed/zk_scaling.csv` | `plot_all_results.py::fig4` | Warmed Groth16 mean proving time with standard-deviation error bars. | Figure 4b — Proving time versus policy rules. |
| `fig4c_proof_key_size` | `results/processed/zk_scaling.csv` | `plot_all_results.py::fig4` | Proof-bundle size and proving-key size as the rule count increases. | Figure 4c — Proof and proving-key size. |
| `fig4d_backend_throughput` | `results/processed/zk_backend_circulation.csv` | `plot_all_results.py::fig4` | Full-circulation throughput derived from measured common stages plus measured Groth16/PLONK/fflonk prove/verify times. | Figure 4d — Full-circulation throughput across proof backends. |
| `fig5a_dp_relative_error` | `results/processed/dp_error_summary.csv` | `plot_all_results.py::fig5` | Mean relative error with standard deviation over eight measured VBS releases per epsilon. | Figure 5a — DP relative error versus epsilon. |
| `fig5b_cumulative_privacy_loss` | `results/processed/dp_composition.csv` | `plot_all_results.py::fig5` | Conservative cumulative fixed-point privacy charge across 1–32 releases. | Figure 5b — Cumulative privacy loss under repeated releases. |
| `fig5c_rounding_gap` | `results/processed/dp_rounding_summary.csv` | `plot_all_results.py::fig5` | Maximum difference between enclave and independent Python fixed-point accounting; annotated zeros are intentional. | Figure 5c — Conservative fixed-point rounding gap. |
| `fig5d_budget_exhaustion` | `results/processed/budget_exhaustion_summary.csv` | `plot_all_results.py::fig5` | Accepted and reverted local-chain requests under a fixed 5.0 budget. | Figure 5d — Budget exhaustion under repeated queries. |
| `fig6a_native_vs_vbs_latency` | `results/processed/vbs_performance_summary.csv` | `plot_all_results.py::fig6` | VBS process latency versus the repository's measured Python aggregate reference across payload sizes. | Figure 6a — VBS versus available native reference latency. |
| `fig6b_vbs_slowdown` | `results/processed/vbs_performance_summary.csv` | `plot_all_results.py::fig6` | VBS process slowdown relative to the measured Python aggregate reference. | Figure 6b — VBS slowdown relative to the available reference. |
| `fig6c_payload_throughput` | `results/processed/vbs_performance_summary.csv` | `plot_all_results.py::fig6` | Payload throughput for VBS execution and the Python reference. | Figure 6c — Payload throughput. |
| `fig6d_enclave_stage_breakdown` | `results/processed/vbs_stage_breakdown.csv` | `plot_all_results.py::fig6` | Enclave TSC timing for decrypt, aggregate, DP noise, transcript, and evidence generation. | Figure 6d — Enclave stage-level latency. |
| `fig6e_memory_footprint` | `results/processed/vbs_performance_summary.csv` | `plot_all_results.py::fig6` | Peak TrustCircuit host RSS and Python-process RSS; Windows does not expose a separate enclave RSS counter here. | Figure 6e — Host/reference memory footprint. |
| `fig6f_transcript_attestation_overhead` | `results/processed/vbs_attestation_overhead.csv` | `plot_all_results.py::fig6` | Transcript hashing, native evidence generation, and external validation overhead. | Figure 6f — Transcript and attestation overhead. |
| `fig7a_context_substitution` | `results/processed/protocol_attack_summary.csv` | `plot_all_results.py::fig7` | Rejection outcomes for wrong request, asset, consumer identity/address, policy, function, and result. | Figure 7a — Context-substitution rejection. |
| `fig7b_tampering_replay` | `results/processed/protocol_attack_summary.csv` | `plot_all_results.py::fig7` | Rejection outcomes for changed transcript/evidence, stale evidence, tampered proof, and replay. | Figure 7b — Tampering and replay rejection. |
| `fig7c_concurrency_outcomes` | `results/processed/settlement_concurrency_summary.csv` | `plot_all_results.py::fig7` | Accepted and reverted same-block privacy-budget reservations for client concurrency 1–32. | Figure 7c — Accepted and reverted requests under concurrency. |
| `fig7d_concurrency_invariants_latency` | `results/processed/settlement_concurrency_summary.csv` | `plot_all_results.py::fig7` | Budget invariant violations and mean reserve/consume settlement latency under contention. | Figure 7d — Budget safety and settlement latency under concurrency. |

## Required substitutions and scope labels

- The repository does not contain a non-enclave native C++ processor. Figures
  6a–6c use the independently measured Python aggregate reference and label it
  explicitly; they must not be described as native C++ measurements. Adding a
  shared-core native C++ executable is future work.
- Figure 6e reports process RSS. A separate VBS secure-kernel/enclave working-set
  counter was not available from this user-mode harness.
- Figure 7c–7d measures same-block `BudgetLedger` settlement contention on the
  local Hardhat chain. Phase 7 proof settlement itself is measured in Figure 3;
  the concurrency panels do not claim 32 simultaneous hardware enclaves.
- Figure 4d is model-calibrated from directly measured common-pipeline and
  backend proof components. It is not a public-network throughput measurement.
- `results/raw/phase8/testnet/public_testnet_status.json` records that a public
  testnet run was not possible because the repository defines only the Hardhat
  network and supplies no RPC/account configuration. No testnet number is used.

