# Draft technical caption notes

These notes are manuscript support material, not final prose. All numeric
claims should be copied from the cited processed CSV rather than from this file.

## Figure 3 — End-to-end ablation

- **3a:** Six lifecycle variants, five runs each. The y-axis is logarithmic
  because the Python aggregate-only baseline is orders of magnitude faster than
  any chain/proof path. `No TEE*` is model-calibrated from measured components;
  all other bars are direct local measurements.
- **3b:** Mean end-to-end latency. Deployment gas/time is excluded; request
  registration, access, VBS/proof work, and settlement are included according
  to each variant's guarantees.
- **3c:** Full TrustCircuit stage decomposition. The proof bar includes measured
  proof generation and expectation registration; VBS includes processor and
  external evidence-validation wall time.
- **3d:** Gas uses local Hardhat receipts. It is suitable for relative cost
  attribution, not fiat/public-network fee claims.

## Figure 4 — VCP scaling and proof backends

- **4a:** The Phase 7 circuit has 11 public signals. Rule folding increases the
  constraint count monotonically from 1 to 10 rules.
- **4b:** Twelve measured Groth16 repetitions follow two warm-up repetitions per
  circuit. Error bars are one standard deviation.
- **4c:** The proof bundle contains proof plus public signals; the proving key is
  reported separately. Groth16 proof size stays nearly constant while key size
  grows with circuit size.
- **4d:** Groth16, PLONK, and fflonk use the same two-rule Phase 7 relation.
  Full-circulation throughput is a model-calibrated sum of measured common stages
  and measured backend prove/verify latency; state this explicitly.

## Figure 5 — Differential privacy and budget accounting

- **5a:** Eight non-warm-up VBS MEAN releases per epsilon on the same seeded
  1,000-row synthetic dataset. DP randomness remains enclave-generated, so the
  plot reports a distribution rather than exact output equality.
- **5b:** RDP composition covers 1–32 releases. The conservative fixed-point
  series uses the maximum measured per-release charge for each epsilon.
- **5c:** Enclave and Python accounting agree exactly at the `1e-6` fixed-point
  unit for this grid; the zero annotations are a result, not missing data.
- **5d:** A local `BudgetLedger` with total budget 5.0 accepts releases until the
  next conservative fixed-point charge cannot fit. All later requests revert
  and invariant violations remain zero.

## Figure 6 — VBS processor behavior

- **6a:** Six payloads from 1 KiB to 800,000 bytes, five measured runs after one
  warm-up. The comparison is against the available Python aggregate reference,
  not native C++; retain the asterisk/caveat in the manuscript.
- **6b:** Slowdown includes process creation and VBS enclave invocation. It must
  not be interpreted as steady-state named-pipe latency.
- **6c:** MiB/s is computed from plaintext bytes and structured wall timing.
- **6d:** Enclave TSC stages show payload-dependent decrypt/aggregate work and
  the comparatively fixed evidence-generation component.
- **6e:** Host peak RSS is sampled with `psutil`; the comparison is Python
  process RSS. Windows did not expose separate enclave RSS through this harness.
- **6f:** External validation runs in a second host/enclave instance and is
  intentionally separated from transcript and report-generation timing.

## Figure 7 — Robustness and concurrency

- **7a:** Every context substitution is rejected before state consumption:
  request, asset, consumer ID/address, policy, function, and result.
- **7b:** Changed transcript/evidence, stale evidence, tampered Groth16 proof,
  and replay are rejected. Failed final settlement rolls back proof/nullifier and
  budget state.
- **7c:** Reservations are submitted into one Hardhat block at concurrency
  1/2/4/8/16/32 with capacity fixed to half the batch (except one request).
  Accepted counts equal capacity; the rest revert.
- **7d:** The budget conservation invariant has zero violations at every tested
  concurrency. Latency is local same-block reserve/consume settlement time, not
  public-chain confirmation latency.

## Public-testnet note

No public-testnet panel is claimed. `hardhat.config.js` exposes only chain 31337
and the repository provides no public RPC/account configuration. The local-chain
results are the primary measurements; the status is preserved in
`results/raw/phase8/testnet/public_testnet_status.json`.

