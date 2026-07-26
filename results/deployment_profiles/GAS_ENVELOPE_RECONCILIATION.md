# TC-Full 1.37M Gas Envelope Reconciliation

## Conclusion

The approximately **1.37 million gas** TC-Full profile envelope is traceable to
the raw Phase 8 experiment. It is not reconstructed by adding the
component-level lifecycle costs in Table 4 to the isolated Groth16 verifier
cost in Table 5.

The reported value is the mean aggregate gas across 30 non-warm-up
`full_trustcircuit` runs:

| Integrated profile stage | Mean gas | Share of total |
|---|---:|---:|
| Access initialization | 376,849.4 | 27.50% |
| Budget initialization and reservation | 221,762.2 | 16.18% |
| Expectation registration | 283,373.8 | 20.68% |
| Atomic settlement | 488,259.4 | 35.63% |
| **TC-Full total** | **1,370,244.8** | **100%** |

Additional summary statistics:

| Statistic | Total gas |
|---|---:|
| Mean | 1,370,244.8 |
| Median | 1,370,254 |
| Standard deviation | 42.94 |
| Minimum | 1,370,122 |
| Maximum | 1,370,290 |

## Integrated Profile Boundary

Each TC-Full profile run aggregates the receipts of seven top-level
transactions:

1. `registerAssetV2`
2. `registerBudget`
3. `requestAccessV2`
4. `approveRequest`
5. `reserveBudgetForRequest`
6. `registerExpectation`
7. `settle`

The final `settle` transaction internally performs:

- request, asset, consumer, policy, result, transcript, and attestation-context
  checks;
- Groth16 verification and nullifier consumption;
- privacy-budget consumption;
- access-request completion;
- settlement-audit recording.

Contract deployment is excluded. The benchmark deploys the contracts before
creating the gas accumulator. Off-chain TEE execution and proof generation are
included in the latency profile where applicable, but they do not consume EVM
gas.

The raw CSV field `proof_gas` requires careful interpretation: its approximately
283K gas value is the `registerExpectation` transaction, not the isolated
Groth16 verifier. Actual on-chain proof verification occurs inside `settle` and
is therefore included in `settlement_gas`.

## Why Tables 4 and 5 Sum to Only 893,793 Gas

The visible component sum is:

```text
Table 4 initialization      209,388
Table 4 request lifecycle   428,648
Table 5 isolated verifier   255,757
                            -------
Total                       893,793 gas
```

Table 4 uses a narrower component benchmark:

- `registerAsset` and `requestAccess` rather than the context-rich V2 calls;
- direct standalone budget operations rather than settlement-wrapper calls;
- `MockComplianceVerifier.submitProof`, which only records mock proof metadata;
- standalone request completion and basic audit recording.

Table 5 measures only the exported Groth16 verifier call. It excludes the
expectation state, wrapper validation, nullifier update, budget transition,
request completion, and settlement audit surrounding verification in the
integrated path.

The approximately 476K difference can be reconciled at the corresponding
boundary level:

| Corresponding boundary | Integrated profile gas | Tables 4--5 gas | Difference |
|---|---:|---:|---:|
| Context-rich access setup | 376,849.4 | 304,398 | +72,451.4 |
| Wrapped budget setup and reservation | 221,762.2 | 193,065 | +28,697.2 |
| Full expectation persistence versus mock metadata | 283,373.8 | 25,338 | +258,035.8 |
| Atomic verification and settlement | 488,259.4 | 370,992 | +117,267.4 |
| **Total** | **1,370,244.8** | **893,793** | **+476,451.8** |

This table is a measurement-boundary reconciliation, not an opcode-level gas
attribution. The component and integrated experiments call different entry
points and compose state transitions differently.

## Paper-Ready Explanation

> The TC-Full gas envelope is the mean aggregate gas of seven top-level
> transactions in a fresh integrated-profile run: `registerAssetV2`,
> `registerBudget`, `requestAccessV2`, `approveRequest`,
> `reserveBudgetForRequest`, `registerExpectation`, and `settle`. The final
> settlement transaction atomically performs request-context validation,
> Groth16 verification and nullifier consumption, privacy-budget consumption,
> access completion, and settlement-audit recording. Across 30 non-warm-up
> runs, these stages consume 376,849, 221,762, 283,374, and 488,259 gas on
> average, respectively, yielding 1,370,245 gas in total. Contract deployment
> and off-chain TEE and proving work are excluded.

> This integrated boundary differs from the component benchmark in
> Table~\ref{tab:onchain_lifecycle_cost}, which uses direct standalone entry
> points and a mock proof-metadata call, and from
> Table~\ref{tab:zk_compliance_cost}, which measures the exported verifier in
> isolation. The component values therefore do not reconstruct the profile
> envelope by addition.

## Evidence and Reproducibility

- Raw trials: `results/raw/phase8/e2e_ablation.csv`
- Raw experiment configuration:
  `results/raw/phase8/chain_experiment_config.json`
- Reused profile trials:
  `results/deployment_profiles/raw/deployment_profile_trials.csv`
- Profile summary:
  `results/deployment_profiles/summary/deployment_profile_summary.csv`
- Processed gas-stage breakdown:
  `results/processed/e2e_gas_breakdown.csv`
- Integrated benchmark implementation:
  `benchmarks/phase8_chain_experiments.js`
- Component benchmark implementation: `scripts/gas-benchmark.js`
- Component summary: `results/summary/contract_gas_summary.csv`

The profile result is a measured local Hardhat result under configuration hash
`ea091c96144cb733288085c0aa09e1893c72f7a689eb8649f66e8f0d052be86c`.
