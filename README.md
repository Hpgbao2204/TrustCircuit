# TrustCircuit

TrustCircuit is a reproducible research prototype combining smart contracts, differential privacy, zero-knowledge proofs, CP-ABE, and trusted execution. The retained paper evaluation uses AWS Nitro Enclaves for the historical trusted-processor measurements. The current Windows VBS path and VCP v2 stack are separate evidence classes and must not be presented as Nitro measurements.

## Install and test

Requirements for local experiments: Node.js 22, Python 3.12, Rust, Circom 2.2.2, and snarkjs 0.7.5. Nitro reruns additionally require an AWS Nitro Enclaves host.

```powershell
npm ci
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm run compile
npm test
```

Verify every retained evidence hash, row count, and reported numerical claim without generating figures:

```powershell
python scripts/verify_paper_evidence.py
```

The paper's seven-public-input circuit is preserved at `zk/circuits/paper_legacy_compliance_check.circom`. The canonical VCP v2 circuit exposes 24 public inputs and is implemented consistently by `zk/circuits/compliance_check.circom`, `scripts/lib/phase7_encoding.js`, `contracts/ComplianceVerifier.sol`, and `contracts/TrustCircuitSettlement.sol`. Historical 7-input and 11-input measurements are not valid measurements of VCP v2.

VCP v2 binds request, asset, consumer, policy and version, purpose/function, dataset, DP configuration, freshness, reserved and actual cost, nullifier, validated execution context, attestation statement, result, and audit digest. Native certificate-chain or platform-root validation, arbitrary program correctness, DP random-sampling correctness, and legal compliance remain outside the circuit.

## Rerun paper experiments

Local benchmark entry points are:

```powershell
npx.cmd hardhat run scripts/gas-benchmark.js
python dp/experiment.py --seed 42 --rows 50000 --trials 500
python crypto/run_cpabe_policy_benchmark.py
node crypto/abe_scaling.js
```

Nitro source and host-side clients are under `tee/nitro`. Build the EIF from its Dockerfile, start the enclave, then run the payload, native-attestation, and worker-pool clients. Direct measurements cover payloads 1--128 MiB and worker counts 1, 2, and 4. Larger values are explicitly retained as model projections.

Base Sepolia evidence includes public transaction hashes. A new testnet run requires a user-supplied RPC endpoint and funded test account in `.env`; secrets are not archived.

## VBS migration track

Copy `tee/vbs/TrustCircuitVbs.Local.props.example` to `tee/vbs/TrustCircuitVbs.Local.props`, configure local tooling and signing, then run:

```powershell
msbuild tee/vbs/TrustCircuitVbs.sln /m /p:Configuration=Debug /p:Platform=x64
powershell -NoProfile -ExecutionPolicy Bypass -File tee/vbs/tests/smoke.ps1
npm run phase7:build
npm run phase7:e2e
```

The VCP build retains the generated Solidity verifier at `contracts/VCPGroth16Verifier.sol` and a hash/dimension manifest at `zk/vcp_v2_metadata.json`. The local proving key, WASM, witness files, and development ceremony outputs remain ignored build artifacts. The metadata labels the deterministic local ceremony as development-only.

On the verified Windows host, a clean VCP build completed in about five minutes; allow roughly 5--15 minutes under normal load. A setup that remains at the same heartbeat for an hour should be investigated rather than treated as normal. The build prints six pipeline checkpoints, streams verbose snarkjs output, reports numeric `x/y` substages as percentages, and emits a heartbeat every 30 seconds. Pipeline checkpoint percentages mean completed phases, not an ETA; substage percentages may restart when snarkjs moves to another internal operation. Completed setup and contribution phases have hash-checked local resume checkpoints, so a later interruption does not repeat a completed long phase.

Quickly validate the progress display and compile the 24-input R1CS without starting setup:

```powershell
npm run vcp:progress:selftest
npm run vcp:build:smoke
```

Run the real-proof integration check after the VCP build:

```powershell
npm run vcp:test:real
```

It proves two different policy matrices with the same verification key, rejects a mutation of every one of the 24 public fields, and checks atomic budget, request, nullifier, and audit updates.

Measure the current VCP v2 rather than the historical circuit:

```powershell
npm run vcp:benchmark
```

The benchmark uses two warm-ups and 30 retained repetitions by default. It writes per-run data, a summary, and a config to `results/raw/phase8/vcp_v2_runs.csv`, `results/summary/vcp_v2_summary.csv`, and `results/summary/vcp_v2_config.json`. Proof-only ABI size, proof JSON size, proof-plus-public-input size, witness time, proving time, off-chain verification time, key sizes, and isolated verifier gas are reported separately.

Verify the retained VCP v2 hashes, row counts, statistics, key binding, integration result, and serialization definitions with:

```powershell
npm run vcp:verify
```

`VCP_V2_EVIDENCE.json` is the canonical manifest for current VCP v2 claims. `PAPER_EVIDENCE.json` remains the immutable manifest for historical Nitro/legacy-circuit paper evidence.

The retained 30-run VCP v2 benchmark reports 40,161 constraints, 1,006.86 ms mean proving time after witness generation, 1,080.05 ms mean witness-plus-prove time, 8.43 ms mean off-chain verification, and 374,753 gas at the isolated-verifier median. The Groth16 A/B/C ABI is 256 bytes; snarkjs proof JSON varies from 719 to 725 bytes, and proof-plus-24-public-input JSON varies from 1,757 to 1,763 bytes. These serialization boundaries must not be conflated.

## Reproduce VBS experiments

Regenerate processed tables and figures from the retained raw evidence:

```powershell
python scripts/process_phase8_results.py
python scripts/plot_all_results.py
```

Rerun the full local experiment suite:

```powershell
npm run phase8:experiments
```

This current-suite command runs VBS experiments, the VCP v2 real-proof integration, attack-layer audit, and the 30-repetition VCP v2 benchmark. Historical 7/11-input ZK scaling and backend scripts remain in the repository only to audit previously reported rows.

After a successful local VCP build and compile, smoke-test the final eight-contract stack on Base Sepolia with one request, then run the 30-request campaign:

```powershell
npm run testnet:base:smoke
npm run testnet:base
npm run testnet:base:process
```

The retained final-stack campaign contains 135 successful transactions and 30 atomic settlements. It reports 554,496 gas at the settlement median (554,543 p95), 3.326976 micro-ETH median total fee, and 2.964 s median one-confirmation inclusion (3.196 s p95). Deploying the eight contracts consumed 6,714,037 gas and 29,517 bytes of calldata. The processor validates the campaign, writes canonical summaries, and regenerates the four Base Sepolia paper panels.
