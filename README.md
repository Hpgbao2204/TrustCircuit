# TrustCircuit

TrustCircuit is a reproducible research prototype combining smart contracts, differential privacy, zero-knowledge proofs, and a Windows VBS Enclave.

## Repository scope

The repository contains source code, tests, dependency locks, the public Adult dataset, and canonical raw evidence under `results/raw/phase8`. Paper sources, generated figures, processed tables, transient request bundles, build outputs, credentials, and local machine state are intentionally excluded.

`REPRODUCIBILITY.json` records the SHA-256 hash, row count, measurement class, and experiment config for every retained evidence file. Direct measurements, analytical results, functional evidence, and model-calibrated rows remain explicitly distinguished by `measurement_type`; they are not presented as the same evidence class.

## Install and test

Requirements: Node.js, Python 3, Visual Studio 2022 x64, Windows SDK 10.0.26100.0, and a configured VBS Enclave development environment.

```powershell
npm ci
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm run compile
npm test
```

Copy `tee/vbs/TrustCircuitVbs.Local.props.example` to `tee/vbs/TrustCircuitVbs.Local.props`, configure local tooling and signing, then run:

```powershell
msbuild tee/vbs/TrustCircuitVbs.sln /m /p:Configuration=Debug /p:Platform=x64
powershell -NoProfile -ExecutionPolicy Bypass -File tee/vbs/tests/smoke.ps1
npm run phase7:build
npm run phase7:e2e
```

## Reproduce experiments

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
