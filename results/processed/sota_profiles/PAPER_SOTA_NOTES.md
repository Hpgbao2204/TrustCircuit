# Paper-ready SOTA comparison notes

## Core interpretation

- **TC-Full provides the broadest integrated lifecycle enforcement.** In the common 48-field contract, TC-Full binds 48 fields using 180 field-layer checks per request. At 128 repeated mutation attempts, it activates 167,836 unique field-layer controls per 1,000 requests, compared with 72,737 for the strongest external profile in this experiment, VerifBFL.
- **TC-Protected is the middle assurance point.** Removing the VCP relation and proof-bound nullifier reduces the endpoint to 111,916 control activations, but it retains attested execution, privacy-cost accounting, cumulative budget state, and audit binding.
- **TC-Lite is intentionally comparable to narrower ledger or mechanism-specific profiles.** Its endpoint is 60,602, between VPrivKV (57,810) and ProMark (63,403). This is expected because TC-Lite omits confidential execution, privacy accounting, and zero-knowledge compliance.

## Assurance-cost trade-off using measured deployment-profile data

| Profile | Mean latency | Mean throughput | Mean gas | Unique controls at 128 attempts |
| --- | ---: | ---: | ---: | ---: |
| TC-Lite | 6.3 ms | 159.84 req/s | 433,332 gas | 60,602 |
| TC-Protected | 148.0 ms | 6.84 req/s | 685,560 gas | 111,916 |
| TC-Full | 378.6 ms | 2.65 req/s | 1,370,245 gas | 167,836 |

The correct argument is therefore not that TC-Full is faster. TC-Lite is the fastest and cheapest profile, whereas TC-Full trades latency, throughput, and gas for broader cross-stage binding. TC-Protected occupies the practical middle point when confidential computation and cumulative privacy-budget enforcement are required but on-chain VCP verification is not.

## Candidate paragraph for the paper

> Under the common 48-field feature contract, TrustCircuit's deployment profiles expose a clear assurance-cost frontier. TC-Lite activates a number of unique field-layer controls comparable to specialized ledger and verifiable-privacy profiles, while retaining the lowest measured latency and gas envelope. TC-Protected adds attested execution and cumulative privacy-budget state, substantially increasing cross-stage mutation coverage without incurring proof-generation cost. TC-Full provides the broadest integrated binding across request identity, policy, execution evidence, privacy cost, proof context, nullifier state, and audit settlement; this additional assurance is accompanied by higher latency and gas, with the measured overhead concentrated in proof generation. These results support configurable deployment rather than a claim that every application should use the complete stack.

## Claims to avoid

- Do not call the control-activation curves runtime, throughput, or cryptographic-security measurements of the original related systems.
- Do not claim that TrustCircuit subsumes the mechanism-specific proof guarantees of VLDP, VPrivKV, or VerifBFL.
- Do not say TC-Full is faster; say it offers broader integrated enforcement at higher measured cost.
- Always describe the external curves as minimal feature-contract emulations derived from the cited systems' published contributions.
