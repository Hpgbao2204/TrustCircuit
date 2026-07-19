# TrustCircuit VBS Enclave - Phases 1-7

This directory contains the independent x64 Windows VBS Enclave path for
TrustCircuit. Phase 1 smoke remains available; Phases 2-5 add bounded SHA-256,
COUNT/MEAN, AES-256-GCM decryption, Gaussian DP, fixed-point privacy accounting,
and a JSON subprocess protocol. Phase 6 adds canonical execution-transcript
binding, native Windows VBS evidence, and external validation/compression.
Phase 7 projects the validated context into BN254 public signals, generates a
Groth16 proof, and performs atomic local-EVM settlement.

See `PROTOCOL.md` for canonical byte layouts, Phase 7 field projection,
evidence format, and trust limits.

## Local configuration

Copy the template and update it for the current machine:

```powershell
Copy-Item `
  .\tee\vbs\TrustCircuitVbs.Local.props.example `
  .\tee\vbs\TrustCircuitVbs.Local.props
```

`TrustCircuitVbs.Local.props` is ignored by Git. It contains local package/tool
paths plus public thumbprints for the enclave and validator development
certificates. The two thumbprints may refer to the same local certificate for
development, but production deployments should separate those roles. Never put
a private key or exported certificate key material in this repository.

## Build

From the repository root:

```powershell
& "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" `
  .\tee\vbs\TrustCircuitVbs.sln `
  /m `
  /t:Rebuild `
  /p:Configuration=Debug `
  /p:Platform=x64
```

The enclave project applies VEIID first and invokes SignTool second. SignTool
exit code `2` is mapped to success-with-warning; other nonzero exits fail the
build. EDL-derived C++/FlatBuffers files are generated during the build under
each project's `Generated Files` directory and are not committed.

## Smoke test

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tee\vbs\tests\smoke.ps1 `
  -Configuration Debug
```

Expected output:

```text
Hello World!
Result = 200
PASS: TrustCircuit VBS enclave returned Result = 200
```

## Existing-stack regression test

```powershell
npm.cmd test
```

## Phase tests

Run in order after a Debug x64 build:

```powershell
python .\tee\vbs\tests\phase2_hash_buffer.py --configuration Debug -v
python .\tee\vbs\tests\phase3_aggregates.py --configuration Debug -v
python .\tee\vbs\tests\phase4_encrypted_path.py --configuration Debug -v
python .\tee\vbs\tests\phase5_dp_pipeline.py --configuration Debug -v
python .\tee\vbs\tests\phase6_attestation.py --configuration Debug -v
```

## End-to-end encrypted DP request

```powershell
python .\tee\vbs\run_pipeline.py `
  --configuration Debug `
  --function MEAN `
  --rows 100 `
  --seed 20260719 `
  --epsilon 1.0 `
  --delta 0.00001
```

This command writes a temporary encrypted dataset and request, invokes the
processor host, then invokes a separate validator process/enclave instance. It
prints one JSON response containing the enclave result and a non-null compact,
signed `attestation_evidence`, then removes all temporary files.

See `PHASE1_COMMAND_LOG.md`, `IMPLEMENTATION_LOG.md`, and
`ATTESTATION_LOG.md` for exact commands and results.

## Phase 7 end-to-end settlement

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_trustcircuit_e2e.ps1 `
  -Configuration Debug `
  -Rows 256 `
  -Seed 20260719
```

The command builds the Phase 7 circuit and VBS solution, generates and encrypts
a synthetic dataset, obtains real validated VBS evidence, generates and checks
a Groth16 proof, then reserves and atomically consumes the privacy budget on a
local Hardhat chain. Raw bundles and settlement receipts are written beneath
`results/raw/e2e/` without persisting the AES key.

Run the contract and binding regression suite after `phase7:build`:

```powershell
npm.cmd run phase7:build
npm.cmd test
```

## Phase 8 experiments and panels

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_all_phase8_experiments.ps1 `
  -Configuration Debug
```

This creates raw data under `results/raw/phase8/`, processed tables under
`results/processed/`, and 22 independent vector-PDF/300-dpi-PNG panels under
`Paper/figures/panels/`. The repository has no configured public-testnet
network and no non-enclave native C++ processor; those two limitations are
recorded explicitly rather than replaced with fabricated measurements.

Every command executed during this work and its result is recorded in
`PHASE7_EXPERIMENT_LOG.md`.
