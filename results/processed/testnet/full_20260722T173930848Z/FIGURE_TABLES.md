# Base Sepolia Figure Tables

Run: `full_20260722T173930848Z`; measured on Base Sepolia (`84532`). Exact values below come from `transactions.csv`; figures contain no synthetic observations.

## Table for Figure 1a — deployment resources

| Contract | n | Gas p50 | Gas p95 | Calldata p50 (B) | Inclusion p50 (ms) | Inclusion p95 (ms) |
|---|---:|---:|---:|---:|---:|---:|
| Data registry | 10 | 438,043 | 438,043 | 1,813 | 3,765.2 | 4,352.9 |
| Access controller | 10 | 707,598 | 707,598 | 3,061 | 3,823.3 | 4,184.4 |
| Budget ledger | 10 | 549,451 | 549,451 | 2,329 | 4,093.2 | 4,384.4 |
| Audit ledger | 10 | 205,562 | 205,562 | 737 | 3,805.8 | 3,936.3 |
| Groth16 verifier | 10 | 552,207 | 552,207 | 2,342 | 3,754.7 | 4,362.7 |
| Compliance adapter | 10 | 897,995 | 897,995 | 4,032 | 3,891.1 | 4,387.9 |
| Settlement | 10 | 905,780 | 905,780 | 4,477 | 3,779.8 | 4,170.1 |

## Table for Figure 1b — settlement and revert gas

| Operation | n | Observed outcome | Gas p50 | Gas p95 | Gas p99 | Calldata p50 (B) |
|---|---:|---|---:|---:|---:|---:|
| Valid settlement | 30 | success | 471,163 | 471,187 | 483,311 | 772 |
| Valid control | 10 | success | 471,151 | 471,175 | 471,175 | 772 |
| Context mismatch | 10 | expected revert | 70,746 | 70,770 | 70,770 | 772 |
| Tampered proof | 10 | expected revert | 1,913,622 | 1,913,625 | 1,913,625 | 772 |
| Replay | 10 | expected revert | 54,825 | 54,849 | 54,849 | 772 |

## Table for Figure 1c — fee decomposition

All fee values are micro-ETH (`10^12 wei`).

| Operation | n | L1 fee p50 | L2 fee p50 | Total fee p50 | Total fee p95 | Total fee p99 |
|---|---:|---:|---:|---:|---:|---:|
| Valid settlement | 30 | 0.0371 | 2.8270 | 2.8641 | 2.8671 | 2.9366 |
| Valid control | 10 | 0.0384 | 2.8269 | 2.8655 | 2.8670 | 2.8675 |
| Context mismatch | 10 | 0.0382 | 0.4245 | 0.4627 | 0.4639 | 0.4641 |
| Tampered proof | 10 | 0.0383 | 11.4817 | 11.5200 | 11.5213 | 11.5214 |
| Replay | 10 | 0.0381 | 0.3290 | 0.3671 | 0.3690 | 0.3695 |

## Table for Figure 2a — latency and confirmations

| Operation | n | Inclusion p50 | p95 | p99 | 5-conf p50 | p95 | p99 | 12-conf p50 | p95 | p99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Valid settlement | 30 | 3,719.2 | 4,133.4 | 4,204.3 | 11,429.5 | 11,848.1 | 11,937.8 | 25,409.9 | 25,921.3 | 26,074.2 |
| Valid control | 10 | 3,536.0 | 3,922.6 | 3,929.6 | 11,091.4 | 11,567.9 | 11,582.0 | 25,242.8 | 25,594.0 | 25,606.1 |
| Context mismatch | 10 | 3,241.0 | 4,108.6 | 4,352.9 | 10,991.8 | 11,503.0 | 11,586.0 | 24,786.0 | 25,337.4 | 25,463.0 |
| Tampered proof | 10 | 3,337.7 | 3,790.6 | 3,834.7 | 10,913.6 | 11,322.7 | 11,328.0 | 24,776.9 | 25,018.3 | 25,066.1 |
| Replay | 10 | 3,386.6 | 3,745.0 | 3,780.0 | 10,741.9 | 11,130.8 | 11,154.5 | 24,643.6 | 25,030.6 | 25,075.8 |

All latency values are milliseconds and are client-observed from submission through the stated milestone.

## Interpretation notes

- `Valid control` intentionally invokes the same successful settlement path as `Valid settlement`. It is interleaved with attack trials to show that a valid proof/context still succeeds around the revert probes; near-identical gas and fee values are expected, not duplicate fabricated measurements.
- The valid-control row remains in the tables for traceability but is omitted from the figures to avoid a visually redundant category.
- The calldata/compute-density panel was removed because every settlement input is 772 bytes, so the calldata bars add no discriminating evidence.
- The 100% expected-outcome panel was removed because all tested outcomes passed and the flat visualization added little information; raw pass/revert and rollback fields remain in `transactions.csv`.
- The execution-order trace was removed because operation class and run order are partially confounded.
- Smooth curves are PCHIP visual guides through the measured summary markers. They add no samples and should not be interpreted as continuous measurements between categorical operations.
- Figure 2a shows p50 bars and a single p95 guide to avoid overlapping percentile curves; p99 remains available in the table above.
- The tampered-proof revert uses an explicit 2,000,000 gas limit; its gas and fee values are conditional on that cap.
- These results support public-testnet settlement feasibility, not a direct mainnet-performance claim.
