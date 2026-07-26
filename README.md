# TrustCircuit

TrustCircuit is a reproducible research prototype combining smart contracts, differential privacy, zero-knowledge proofs, CP-ABE, and trusted execution. The paper evaluation uses AWS Nitro Enclaves. The Windows VBS implementation is a later migration track and is not used as evidence for the paper's Nitro claims.

## Repository scope

The repository contains source code, tests, dependency locks, public input data, and the canonical non-image evidence needed to audit the reported paper values. Paper sources, generated figures, transient request bundles, build outputs, credentials, and local machine state are intentionally excluded.

`PAPER_EVIDENCE.json` maps each manuscript claim to raw data, summaries, configs, commands, measurement classes, row counts, and SHA-256 hashes. `REPRODUCIBILITY.json` separately covers the later VBS experiment suite. Measured, simulated, analytical, and model-projected values are not presented as the same evidence class.

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

The paper's seven-public-input circuit is preserved at `zk/circuits/paper_legacy_compliance_check.circom`. The current eleven-public-input circuit belongs to the later VBS migration and therefore produces different constraint and proof measurements.

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

Historical configs preserve their original commit, dirty-worktree flag, environment, seeds, warm-ups, and repetitions. The Base Sepolia evidence additionally retains public transaction hashes and canonical contract addresses. Secrets and deployment keys belong in `.env` and are never committed.
