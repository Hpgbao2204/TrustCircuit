# Figure evidence audit command log

Date: 2026-07-19 (Asia/Saigon)  
Repository: `D:\1\TrustCircuit`  
Configuration used for Native/VBS measurements: `Debug|x64`

This file records the commands run while adding the real Native C++ baseline,
repeating the revised measurements, regenerating the figures, and validating
the result. Read-only repository inspection (`rg`, `Get-Content`, `git status`,
and CSV header/sample inspection) was also performed before and during edits.

## Build and static validation

```powershell
& "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" `
  .\tee\vbs\TrustCircuitVbs.sln /m /t:Rebuild `
  /p:Configuration=Debug /p:Platform=x64 /nologo /v:minimal
```

Result: exit `0` on both the initial and final clean rebuilds. The final output
built `TrustCircuitNative.exe`, `TrustCircuitEnclave.dll`, and
`TrustCircuitHost.exe`; VEIID ran before SignTool; SignTool signed one enclave
with its documented VBS support warning and no failure.

```powershell
python -m py_compile scripts/run_attack_layer_audit.py `
  scripts/run_phase8_vbs_experiments.py scripts/process_phase8_results.py `
  scripts/plot_all_results.py tee/vbs/tests/native_baseline.py
node --check benchmarks/phase8_chain_experiments.js
python -m json.tool PROJECT_STATE.json
python -m json.tool results/raw/phase8/vbs_experiment_config.json
```

Result: all commands exited `0`.

## Native/VBS parity development checks

```powershell
python .\tee\vbs\tests\native_baseline.py --configuration Debug -v
```

Result: `3/3` passed (COUNT parity, MEAN parity/schema, and modified-tag
rejection by both processors).

```powershell
python .\scripts\run_phase8_vbs_experiments.py --configuration Debug `
  --performance-reps 1 --privacy-reps 1 --warmups 1 `
  --concurrency-bundles 1
```

First diagnostic result: failed closed on an exact fixed-point-boundary request
whose decimal-to-binary representation did not satisfy the host's requested
fixed-point consistency check. The boundary sampler was corrected to use the
requested `-0.49` and `+0.49` micro-epsilon offsets around each boundary; no
validation was disabled. The same smoke command then exited `0`, producing 12
performance rows, 12 DP rows, and 96 boundary rows.

## Attestation and attack-layer evidence

```powershell
python .\tee\vbs\tests\phase6_attestation.py --configuration Debug -v
python .\scripts\run_attack_layer_audit.py
```

Result: Phase 6 passed `12/12`, including request, asset, consumer, policy hash,
policy version, function, result, transcript, staleness, evidence substitution,
and enclave identity checks. The audit command exited `0` and wrote 25
first-rejecting-layer rows to
`results/raw/phase8/attack_binding_matrix.csv`. Its config records the exact
source commands and SHA-256 hashes of their passing outputs.

## Revised experiments

```powershell
python .\scripts\run_phase8_vbs_experiments.py --configuration Debug `
  --performance-reps 30 --privacy-reps 30 --warmups 1 `
  --concurrency-bundles 32
```

Result: exit `0` in 84.9 seconds. Outputs include:

- 186 Native/VBS performance rows: one warm-up plus 30 paired measurements for
  each of six payload sizes (180 measured pairs);
- 186 DP rows: one warm-up plus 30 measurements for each of six epsilons;
- 96 boundary samples around 48 fixed-point boundaries;
- 32 fresh VBS/proof concurrency bundles.

```powershell
& .\node_modules\.bin\hardhat.cmd run `
  .\benchmarks\phase8_chain_experiments.js --network hardhat
```

Result: exit `0` in 79.6 seconds. The command generated 32 proofs, 30 trials for
each of 12 attack cases (360 rows), 30 trials for each concurrency level
1/2/4/8/16/32 (180 rows), and five runs for each of six ablations (30 rows).

The following PowerShell audit was run over the raw CSVs:

```powershell
$perf = Import-Csv results/raw/phase8/native_vbs_performance.csv |
  Where-Object is_warmup -eq '0'
$attacks = Import-Csv results/raw/phase8/protocol_attacks.csv
$concurrency = Import-Csv results/raw/phase8/settlement_concurrency.csv
$rounding = Import-Csv results/raw/phase8/dp_rounding_boundaries.csv
# Group/Measure-Object checks for repetitions, parity, acceptance,
# invariant violations, and under-reporting.
```

Result: 180 measured pairs, six payload groups, minimum 30 repetitions per
payload, zero parity failures, 360 rejected attack trials with zero acceptance,
180 concurrency trials with zero budget-invariant violations, and 96 boundary
samples with zero under-reports.

## Processing and panel generation

```powershell
python .\scripts\process_phase8_results.py
python .\scripts\plot_all_results.py
```

Result: processing wrote 20 machine-readable processed CSVs. The final plotting
run exited `0` and wrote 22 PDFs plus 22 PNG previews. Plotting was rerun after
visual QA adjustments; no experiment values were changed between plot runs.

PNG metadata was verified with `System.Drawing.Image`:

```powershell
Add-Type -AssemblyName System.Drawing
Get-ChildItem Paper/figures/panels -Filter *.png | ForEach-Object {
  $img = [System.Drawing.Image]::FromFile($_.FullName)
  try {
    # Assert Width=7200, Height=4800, HorizontalResolution=600,
    # VerticalResolution=600.
  } finally { $img.Dispose() }
}
```

Result: 22 PDFs, 22 PNGs, zero empty files, zero PNG metadata failures; every
PNG is 7200 x 4800 at 600 dpi. Representative panels 3c, 5c, 5d, 6a, 6d, 6f,
7a, 7b, 7c, and 7d were visually inspected after generation.

## Final regression suite

After the final clean rebuild, the following tests were run sequentially:

```powershell
python .\tee\vbs\tests\native_baseline.py --configuration Debug -v
python .\tee\vbs\tests\phase2_hash_buffer.py --configuration Debug -v
python .\tee\vbs\tests\phase3_aggregates.py --configuration Debug -v
python .\tee\vbs\tests\phase4_encrypted_path.py --configuration Debug -v
python .\tee\vbs\tests\phase5_dp_pipeline.py --configuration Debug -v
python .\tee\vbs\tests\phase6_attestation.py --configuration Debug -v
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\tee\vbs\tests\smoke.ps1 -Configuration Debug
npm.cmd test
```

Result: Native `3/3`, Phase 2 `5/5`, Phase 3 `10/10`, Phase 4 `9/9`, Phase 5
`7/7`, Phase 6 `12/12`, smoke `Result = 200`, and Hardhat `42/42` all passed.

## Interpretation limits

- Native/VBS performance uses Debug x64 and includes process startup.
- Figure 6e is process RSS, not separate enclave memory.
- Figure 4d and the no-TEE ablation are explicitly model-calibrated.
- Figure 7a is functional-test evidence locating the first rejecting layer.
- Concurrency uses a local Hardhat chain, not concurrent hardware enclaves.
- No public testnet was run because the repository has no public network/RPC or
  account configuration.
