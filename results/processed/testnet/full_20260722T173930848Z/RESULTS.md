# Base Sepolia Public-Testnet Settlement Results

- Run: `full_20260722T173930848Z`
- Chain: Base Sepolia (`84532`)
- Transactions: 302 (272 successful, 30 reverted as intended)
- Deployer: `0x862dAd21b3C2F6702fB3b7D784346b0b89Fa8b9F`
- Settlement contract: `0x5b7219a19b93E2174d2f1fc11C46fDD65cFe7C61`
- Groth16 verifier: `0xc8AB37AC465111817Ff7B039EEa31E8F0AE4B722`
- Test ETH spent: 0.000664189 ETH
- Scope: blockchain deployment and settlement only; proof preparation and VBS/Nitro are excluded from measured chain latency.

| Operation | Runs | Success/revert | Median gas | Median calldata (B) | Inclusion p50 / p95 (ms) | 5-conf p50 (ms) | 12-conf p50 (ms) | Rollback pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Application contract suite deployment | 10 | 10/0 | 3,704,429 | 16,449 | 23,067.4 / 23,915.6 |  |  |  |
| Groth16 verifier deployment | 10 | 10/0 | 552,207 | 2,342 | 3,754.7 / 4,362.7 | 11545.617 | 25359.794 |  |
| Valid atomic settlement | 30 | 30/0 | 471,163 | 772 | 3,719.2 / 4,133.4 | 11429.530 | 25409.946 |  |
| Attack-control valid settlement | 10 | 10/0 | 471,151 | 772 | 3,536.0 / 3,922.6 | 11091.408 | 25242.834 |  |
| Context-mismatch revert | 10 | 0/10 | 70,746 | 772 | 3,241.0 / 4,108.6 | 10991.760 | 24786.001 | 1.000 |
| Tampered-proof revert (2M gas cap) | 10 | 0/10 | 1,913,622 | 772 | 3,337.7 / 3,790.6 | 10913.593 | 24776.919 | 1.000 |
| Replay revert | 10 | 0/10 | 54,825 | 772 | 3,386.6 / 3,745.0 | 10741.924 | 24643.626 | 1.000 |

The tampered-proof trials flip a Groth16 curve coordinate and are submitted with an explicit 2,000,000 gas limit. They measure mined malformed-proof revert behavior; their gas is conditional on that cap and is not a normal successful-verifier cost.

## Canonical deployment

| Contract | Address |
|---|---|
| registry | [`0x61B895790a2abe3770ac19085432eb9e6d1008e5`](https://sepolia-explorer.base.org/address/0x61B895790a2abe3770ac19085432eb9e6d1008e5) |
| access_controller | [`0x10356BF756aeBe217a19655f970B338530eB159b`](https://sepolia-explorer.base.org/address/0x10356BF756aeBe217a19655f970B338530eB159b) |
| budget_ledger | [`0xc9a03c279250735440652C08Eab43B4a81ca9E22`](https://sepolia-explorer.base.org/address/0xc9a03c279250735440652C08Eab43B4a81ca9E22) |
| audit_ledger | [`0x57B62d9A0d9B43374964Ee95B5EdAdF8d144cEEA`](https://sepolia-explorer.base.org/address/0x57B62d9A0d9B43374964Ee95B5EdAdF8d144cEEA) |
| groth16_verifier | [`0xc8AB37AC465111817Ff7B039EEa31E8F0AE4B722`](https://sepolia-explorer.base.org/address/0xc8AB37AC465111817Ff7B039EEa31E8F0AE4B722) |
| compliance_adapter | [`0x2409EC3511D10FF9D5bbC042fB24C3D93b7D2be4`](https://sepolia-explorer.base.org/address/0x2409EC3511D10FF9D5bbC042fB24C3D93b7D2be4) |
| settlement | [`0x5b7219a19b93E2174d2f1fc11C46fDD65cFe7C61`](https://sepolia-explorer.base.org/address/0x5b7219a19b93E2174d2f1fc11C46fDD65cFe7C61) |

## Artifacts

- `summary.csv` and `summary.json`: calculated statistics.
- `distribution_summary.csv` and `distribution_summary.json`: tidy per-operation distributions with min, p25, median, mean, standard deviation, p75, p95, p99, and max.
- `FIGURE_TABLES.md`: exact values used by the four standalone figures, plus interpretation notes.
- Figures are exported as PDF only.

## Figure guide

| Figure | Visual form | Research question |
|---|---|---|
| `figure_1a_deployment_resources.pdf` | Bar + smoothed measured-point guide | Deployment gas and calldata by contract. |
| `figure_1b_settlement_gas.pdf` | Bar + smoothed measured-point guide | Settlement and mined-revert gas p50/p95. |
| `figure_1c_settlement_fees.pdf` | Stacked bar + smoothed measured-point guide | L1/L2 median fees and p95 total fee. |
| `figure_2a_settlement_latency.pdf` | Bar + one smoothed measured-point guide | Inclusion and valid-settlement confirmation p50/p95; p99 remains in `FIGURE_TABLES.md`. |

These figures establish public-testnet settlement feasibility. They do not constitute a direct mainnet measurement; mainnet claims require mainnet or multi-regime validation.
