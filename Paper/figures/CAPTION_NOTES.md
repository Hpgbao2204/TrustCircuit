# Draft technical caption notes

These are manuscript support notes, not final prose. Numeric claims must come
from the cited CSV files. Every final panel is an independent 12 x 8 inch PDF
plus a 600-dpi PNG preview. Flat and zero results are retained and disclosed.

## Figure 3 - End-to-end ablation

- **3a:** Six lifecycle variants, five runs each. Points show means and ranges
  show one standard deviation. The log scale preserves the directly observed
  separation rather than compressing it. `No TEE*` is model-calibrated from
  measured components; the other variants are direct local measurements.
- **3b:** End-to-end latency uses the same runs and classification as 3a.
  Deployment is excluded; each variant includes only the stages it retains.
- **3c:** The stacked bar is the full TrustCircuit path. VBS includes processor
  execution and external evidence validation; proof includes proof generation
  and expectation registration. Small access/budget/audit values are retained.
- **3d:** Gas values come from local Hardhat receipts and support relative
  attribution only. They are not public-network fees.

## Figure 4 - VCP scaling and proof backends

- **4a:** The Phase 7 circuit has 11 public signals. Constraint counts are exact
  compiler outputs for 1, 2, 4, 6, 8, and 10 rules.
- **4b:** Each circuit has two warm-ups followed by 12 Groth16 proving runs.
  Points show means and ranges show one standard deviation.
- **4c:** Proof bundles are plotted as unsmoothed observations because their
  serialized size fluctuates slightly; the proving-key line shows its measured
  growth with rules.
- **4d:** Groth16, PLONK, and fflonk implement the same two-rule relation.
  Backend prove/verify timings are measured, while full-circulation throughput
  is model-calibrated by adding separately measured common stages.

## Figure 5 - Differential privacy and budget accounting

- **5a:** Thirty non-warm-up VBS MEAN releases per epsilon use the same seeded
  1,000-row bounded dataset. Noise is enclave-generated, so the plot reports
  mean and standard deviation rather than exact result equality.
- **5b:** The unsmoothed staircase shows analytical RDP/fixed-point composition
  across 1-32 releases. Each per-release charge is the conservative measured
  fixed-point value for that epsilon.
- **5c:** Ninety-six real VBS requests sample offsets of -0.49 and +0.49
  micro-epsilon around 48 fixed-point boundaries. The ECDF includes ten exact
  zero margins, median 0.4207, maximum 0.9983 micro-epsilon, and zero
  under-reports (`results/processed/dp_rounding_summary.csv`).
- **5d:** A local ledger with total epsilon budget 5.0 is queried 32 times for
  each epsilon. Solid staircases show remaining budget; same-color dashed
  staircases show cumulative accepted requests. Rejections leave budget flat.

## Figure 6 - Native and VBS processor behavior

- **6a:** `TrustCircuitNative.exe` and `TrustCircuitHost.exe` receive the same
  request JSON, AES key, nonce, AAD, ciphertext, and TCVBSDS1 payload. Execution
  order alternates. Each of six payload sizes has one warm-up and 30 paired
  measurements. Lines are medians; bands are empirical 2.5-97.5 percentiles.
  Deterministic aggregate and result-hash parity is 100%.
- **6b:** The slowdown is computed per paired observation as VBS Enclave wall
  time divided by Native wall time, then summarized without smoothing. Both
  processes are Debug x64 C++20/v143 with the same MSVC runtime configuration.
- **6c:** Throughput uses plaintext payload bytes divided by the same process
  wall times as 6a. Legend labels are only `Native` and `VBS Enclave`.
- **6d:** Enclave TSC stages separate decrypt, aggregate, DP, transcript, and
  evidence generation. Paired performance requests disable DP noise so exact
  aggregate parity is possible; the observed DP stage is zero and is labeled.
- **6e:** Peak RSS is sampled for the Native executable and VBS host process.
  It is not a separate secure-kernel or enclave-memory measurement.
- **6f:** At the largest 800,000-byte payload, 30 observations per stage show
  transcript hashing, in-enclave evidence generation, and external validation.
  Mean shares of validated VBS wall time are 0.010%, 0.843%, and 33.319%,
  respectively. External validation intentionally launches the validation path
  separately and therefore remains a distinct distribution.

## Figure 7 - Robustness and concurrency

- **7a:** The heatmap is backed by named passing tests in Phase 4, Phase 6, and
  the Hardhat suite. A colored cell means the earliest tested rejecting layer.
  Blank later cells do not mean that a later layer would accept the attack.
- **7b:** Transcript tampering, evidence substitution, stale evidence, proof
  tampering, and replay each have 30 measured local rejection latencies and a
  100% rejection rate. The distribution is operational overhead, not security
  strength.
- **7c:** At concurrency 1/2/4/8/16/32, capacity is half the batch except at
  one request. Bars show mean accepted/reverted counts across 30 local same-block
  trials per level.
- **7d:** Boxplots show the 30 observed mean settlement latencies per level.
  Across all 180 trials, the budget-invariant violation count is exactly zero;
  that flat zero is reported here and in processed tables rather than drawn.

## Reproducibility and limitations

- VBS/Native metadata, seeds, compiler, OS, CPU, warm-ups, repetitions, and
  sanity checks are in `results/raw/phase8/vbs_experiment_config.json`.
- Chain metadata and run counts are in
  `results/raw/phase8/chain_experiment_config.json`.
- Figure 7a test commands and output hashes are in
  `results/raw/phase8/attack_binding_matrix_config.json`.
- The Native/VBS comparison is Debug x64 and includes process startup. A
  Release build and persistent-host benchmark are separate future experiments.
- No public-testnet panel is claimed. `hardhat.config.js` has no public RPC or
  account configuration; the explicit status remains in
  `results/raw/phase8/testnet/public_testnet_status.json`.
