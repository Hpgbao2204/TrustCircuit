# Draft technical caption notes

Every panel is an independent 12 x 8 inch vector PDF plus a 600-dpi PNG. The plotting code reads raw/processed CSV files and keeps direct observations, analytical relations, model-calibrated estimates, and literature-reported values distinct.

## Figure 3 -- End-to-end system performance

- **3a:** Boxplots show retained throughput observations for six ablations; black circles and open triangles mark p50 and p95. Each variant has one warm-up and 30 retained local observations. The `no_tee` configuration is model-calibrated from measured components and must remain labelled as such.
- **3b:** The same retained runs show end-to-end latency distributions. Deployment is excluded from timed lifecycle windows; stages absent from an ablation are not imputed.
- **3c:** Absolute and normalized stacked stage composition retains access, budget, TEE, proof, settlement, and audit contributions for every ablation.
- **3d:** The Pareto view uses median latency and mean local-Hardhat gas. Marker area encodes p95 host working set and color encodes p95 normalized host CPU; neither counter is enclave-only memory.

## Figure 4 -- Proof-system scalability

- **4a:** Compiler-derived constraint counts and measured witness sizes grow with policy-rule count.
- **4b:** Boxplots use 30 retained per-run proving and verification samples after two excluded warm-ups. The logarithmic axis is used because proving and verification have materially different scales.
- **4c:** Proof size, proving-key size, and p95 prover working set are shown as separate log-scaled point-range views. No key/proof point is smoothed.
- **4d:** Groth16, PLONK, and fflonk use the same Phase 7 relation. Backend prove/verify observations and verifier gas are local; the full-circulation throughput is model-calibrated from separately measured common components and is labelled accordingly.

## Figure 5 -- Differential privacy and budget behavior

- **5a:** Thirty retained VBS MEAN releases per epsilon form the relative-error distributions. The diamond trend is analytical RDP reference output, not an additional measured sample.
- **5b:** Conservative fixed-point cost is composed analytically over 1--32 releases; the staircase is not a stochastic privacy experiment.
- **5c:** Ninety-six boundary requests are compared with an analytical oracle. The ECDF shows the measured rounding-margin distribution; zero under-reporting is annotated rather than drawn as a flat series.
- **5d:** Local-Hardhat budget trajectories show remaining fixed-point budget and cumulative accepted requests across repeated queries for the epsilon grid. Rejections leave the ledger state unchanged.

## Figure 6 -- Native and Windows VBS execution

- **6a:** Native and VBS Enclave receive byte-identical encrypted inputs. Six payload sizes have one warm-up and 30 retained paired runs; bands are bootstrap 95% intervals around the retained medians.
- **6b:** Per-pair VBS/Native slowdown and incremental process CPU time are shown as distributions. Process startup is retained as a separate raw field.
- **6c:** Payload throughput is computed from the same process wall times used in 6a, with no Python baseline mixed into the legend.
- **6d:** VBS decrypt, aggregate, DP-noise, transcript, and evidence-generation stages are shown in absolute and normalized forms. Deterministic parity runs intentionally disable DP noise.
- **6e:** Peak normalized host CPU and peak working set are plotted for Native and VBS Enclave; marker size is payload. These are host-process counters and do not measure secure-kernel or enclave-only memory.
- **6f:** At the largest payload, transcript, evidence-generation, and external-validation latency distributions are paired with their percentage contribution to validated VBS wall time.

## Figure 7 -- Security and concurrency

- **7a:** The heatmap marks the first rejecting layer backed by named Phase 4/6 and Hardhat tests. Blank later cells are not acceptance claims.
- **7b:** Thirty rejection trials per listed attack case show operational rejection-latency distributions. Latency is not a security-strength score.
- **7c:** Local same-block trials show accepted/reverted requests and achieved throughput at concurrency 1--32.
- **7d:** Settlement-latency distributions are paired with host CPU/working-set saturation. The budget-invariant violation count is zero across the retained trials and is stated as an annotation rather than a zero curve.

## Figure 8 -- Controlled comparative evaluation

- **8a:** The heatmap describes explicit capabilities of Access Ledger, TEE-only, ZK Release, Local DP Ledger, and TrustCircuit. These are neutral local baselines, not reproductions of external authors' implementations.
- **8b:** Each configuration has one warm-up and 30 retained locally measured samples on the same 1,000-row bounded MEAN workload (`epsilon=0.5`, `delta=1e-5`). Access Ledger and ZK Release use the same request schema/context but intentionally omit the capabilities listed in `COMPARISON_METHODOLOGY.md`.
- **8c:** Median latency and mean local-Hardhat gas are compared with marker area for host working set and color for the analytical capability-coverage score. No public-network fee is implied.
- **8d:** Directly measured proof, attestation, budget, and other lifecycle contributions are decomposed across the five configurations. A zero contribution means that the baseline deliberately omits that component, not that the component is free in TrustCircuit.

## Reproducibility and limits

- Run metadata, seeds, compiler/tool versions, OS/CPU, warm-ups, repetitions, config hashes, and resource definitions are in `results/raw/phase8/*_config.json`.
- Raw per-sample rows remain under `results/raw/phase8`; processed summaries add bootstrap confidence intervals without replacing raw observations.
- No public testnet result is claimed. The local validator/certificate is a same-machine development trust anchor, not production remote attestation.
- The VCP proves only its encoded relation; these plots do not establish arbitrary program correctness, legal compliance, or resistance to all hardware side channels.

