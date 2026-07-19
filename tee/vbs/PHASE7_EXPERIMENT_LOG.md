# Phase 7 and VBS experiment command log

This file records commands executed by Codex for Phase 7 integration and the
paper experiment refresh. Commands are run from `D:\1\TrustCircuit` unless a
different working directory is stated. It intentionally contains no private
key material, certificate exports, plaintext datasets, or DP randomness.

## Pre-edit inspection (2026-07-19)

All repository reads below completed before the first source edit. The first
two failed commands are retained because the log is intended to be complete.

| Result | Command / purpose |
|---|---|
| exit 0 | Read the five required skill instruction files: `trustcircuit-architect`, `zk-circom-compliance`, `solidity-budget-ledger`, `benchmark-evaluator`, and `dp-accounting-lab`. |
| exit 0 | `Get-Content -Raw .\AGENTS.md; Get-Content -Raw .\PROJECT_STATE.json; Get-Content -Raw .\tee\vbs\IMPLEMENTATION_LOG.md; Get-Content -Raw .\tee\vbs\ATTESTATION_LOG.md; Get-Content -Raw .\tee\vbs\PROTOCOL.md; Get-ChildItem -Path . -Filter AGENTS.md -Recurse -File | Select-Object -ExpandProperty FullName` — confirmed that only the root `AGENTS.md` is scoped to this work. |
| exit 1 | `$paths=@('.\tee\vbs\IMPLEMENTATION_LOG.md','.\tee\vbs\ATTESTATION_LOG.md','.\tee\vbs\PROTOCOL.md'); foreach($path in $paths){$lines=Get-Content -LiteralPath $path; Write-Output "$path`t$($lines.Count) lines"}; rg --files | Sort-Object; Write-Output '--- LATEX CANDIDATES ---'; rg --files -g '*.tex' -g '*.ltx' | Sort-Object; Write-Output '--- REVIEWER CANDIDATES ---'; rg --files | rg -i 'review|reviewer|comment|response|rebuttal|decision'` — inventory succeeded; the final reviewer search returned no tracked match because `Paper/` is ignored. |
| exit 0 | `$lines=Get-Content -LiteralPath .\tee\vbs\IMPLEMENTATION_LOG.md; $lines[0..240]; $lines[241..481]` — read the complete Phase 2–5 log. |
| exit 0 | `$lines=Get-Content -LiteralPath .\tee\vbs\ATTESTATION_LOG.md; $lines[0..180]; $lines[181..361]` — read the complete Phase 6 log. |
| exit 0 | `git status --short --untracked-files=all` plus recursive `Paper` and ignored LaTeX/reviewer discovery — worktree was clean; found `Paper/main-old.tex` and immutable `Paper/Comment.txt`. |
| exit 0 | Counted `main-old.tex` (1,648 lines) and `Comment.txt` (249 lines), then inspected the first LaTeX block. |
| exit 0 | `Get-Content -Raw -LiteralPath .\Paper\main-old.tex` — inspected the current manuscript source; no edits were made. |
| exit 0 | `Get-Content -Raw -LiteralPath .\Paper\Comment.txt` — read the immutable reviewer comments; no edits were made. |
| exit 0 | Read `package.json`, `hardhat.config.js`, enumerated contracts/tests/ZK/benchmark/scripts/results, and read `.gitignore`. |
| exit 0 | Read `BudgetLedger.sol`, `ComplianceVerifier.sol`, `AuditLedger.sol`, `DataRegistry.sol`, `AccessController.sol`, and `zk/circuits/compliance_check.circom`. |
| exit 1 | Attempted a combined test/ZK/VBS read with `Get-ChildItem .\tee\vbs -File, ...`; PowerShell rejected the malformed parameter list. No files changed. |
| exit 0 with read errors | Corrected the VBS listing and read current tests/scripts. The command also proved that `zk/package.json`, `setup_zk.js`, `generate_input.js`, and `verify_zk.js` do not exist; actual tracked ZK entrypoints were discovered next. |
| exit 1 | Enumerated tracked ZK/VBS files and current result summaries; `npx` was blocked by the local PowerShell execution policy. Subsequent commands use `npm.cmd` or direct Node CLI paths. |
| exit 0 | Read `benchmark_zk_schemes.js`, `e2e_ablation.js`, `proof_binding_attacks.js`, `budget_double_spend.js`, and `budget_composition.js`. |
| exit 0 | Searched canonical VBS transcript/attestation fields, checked tool versions, Git commit, OS, and CPU. Commit: `666dd5c4f4ed3e5b3d25368e5b46fc218690305c`; Windows build 26200; AMD Ryzen 7 7840HS; Circom 2.2.2; Node 22.13.0; npm 10.9.2; snarkjs 0.7.5. The combined Python import stopped at missing `cryptography`; the VBS reference path does not require that package. |
| exit 0 | Checked Python packages individually (`numpy`, `matplotlib`, `psutil`, `scipy` present; `pandas` absent), read the VBS README build/test commands, and inventoried prior Q1 results. |
| exit 0 | Read the canonical transcript/evidence sections of `PROTOCOL.md`, all of `attestation_validator.py`, and the canonical serialization functions in `tests/vbs_reference.py`. |

## Pre-edit findings

- The VBS transcript already binds the complete request AAD, result, fixed-point
  cost, enclave identity, and execution time inside the enclave. Phase 7 should
  reuse it unchanged.
- The existing Circom/Solidity interface has seven public signals and does not
  bind policy version, function, result hash, transcript hash, or the actual
  compact-attestation digest.
- Proof verification, budget consumption, request completion, and audit logging
  are separate transactions. An orchestrating contract is required for atomic
  settlement.
- The repository has no configured public-testnet network or credentials. Local
  Hardhat measurements are feasible; a public-testnet result must not be
  fabricated.
- The repository has no native C++ non-enclave processor executable. Any Phase 8
  native comparison must either add such a backend or be explicitly identified
  as a faithful replacement baseline rather than mislabeled as native C++.

## Implementation record

All source edits were made with patch-based edits. No command modified the
Microsoft sample at `D:\Dev\VbsEnclaveTooling\SampleApps\HelloWorld`, and no
private signing material was read or written.

The Phase 7 implementation added one eleven-signal settlement context in this
order: request ID, asset ID, consumer ID, policy hash, policy version, function
ID, result hash, actual privacy cost, nullifier, transcript hash, and validated
attestation digest. Python and JavaScript share the same domain-separated
identifier-to-field conversion; the existing enclave transcript bytes are not
re-encoded. `TrustCircuitSettlement` performs proof verification, budget
consumption, nullifier update, request completion, and audit emission in one
transaction.

## Phase 7 build and test commands

| Result | Command / purpose |
|---|---|
| exit 0 | `node .\zk\scripts\build_phase7.js` — compiled the canonical Phase 7 circuit, generated/reused its matching Groth16 key, and exported `Phase7Groth16Verifier.sol`. Final R1CS SHA-256: `ac6e8892365cfc44ca073f2f5e33d41ddf4ac0cd59fb459a4d1cdc65ed9b2ec7`. |
| exit 1, then exit 0 | `npm.cmd run compile` — the first implementation exposed Solidity's stack-depth limit in the adapter; the expectation lookup was split into small internal binding checks. The corrected contract compiled. |
| exit 0 | `npm.cmd test` — final result: 42 passing tests, including valid atomic settlement and every required rejection case. |
| exit 0 | `npm.cmd run benchmark` — the existing pipeline benchmark completed and wrote `results/raw/e2e_pipeline.csv`. |
| exit 0 | `.\node_modules\.bin\hardhat.cmd run .\benchmarks\proof_binding_attacks.js --network hardhat` — the legacy proof-binding entrypoint ran against the eleven-signal ABI and wrote `results/q1/raw/proof_binding_attacks.csv`. |
| timeout after CSV, then exit 0 | `.\node_modules\.bin\hardhat.cmd run .\benchmarks\e2e_ablation.js --network hardhat` used its 50-run default and exceeded the 240-second command limit. A two-run diagnostic proved the CSV had completed but a snarkjs worker kept Node alive. The entrypoint now exits explicitly; `node .\benchmarks\e2e_ablation.js --runs 1 --out results\q1\raw\e2e_ablation_phase7_smoke.csv` then completed in 2.3 seconds. |
| exit 0 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_trustcircuit_e2e.ps1 -Configuration Debug -SkipVbsBuild -SkipZkBuild` — fresh validated VBS evidence, Groth16 proof, and local-chain atomic settlement succeeded. Final raw receipt: `results/raw/e2e/20260718T225341324Z/settlement.json`; atomic settlement gas: 488263; budget used: 1011807; reserved balance: 0; request status: completed; nullifier used: true; audit events: 1. |

One earlier E2E command produced a complete receipt but retained a snarkjs worker.
The exact repository-owned Node process tree was inspected with
`Get-CimInstance Win32_Process -Filter "Name = 'node.exe'"` and terminated by
explicit PID after its output was verified. `run_trustcircuit_e2e.js` and the
legacy ablation entrypoint now use explicit success/failure exits.

## Phase 8 experiment commands and results

The first full orchestration command was:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_all_phase8_experiments.ps1 `
  -Configuration Debug
```

It was intentionally decomposed after two concrete failures so successful raw
measurements would not be discarded:

| Result | Command / purpose |
|---|---|
| exit 1, then exit 0 | `python .\scripts\run_phase8_vbs_experiments.py --configuration Debug --performance-reps 5 --privacy-reps 8 --warmups 1 --concurrency-bundles 32` — the initial epsilon grid included 2.0 and 4.0, which the enclave correctly rejected as outside its supported bound. The experiment grid was restricted to 0.05–1.0 without weakening enclave validation. Six payload sizes, 30 warmed VBS samples, 48 DP samples, composition rows, and 32 fresh evidence bundles were then recorded. |
| exit 1 twice, then exit 0 | `.\node_modules\.bin\hardhat.cmd run .\benchmarks\phase8_chain_experiments.js --network hardhat` — the long combined run let five-minute VBS evidence expire. The runner was corrected to reset the local chain before each evidence-dependent trial and to generate evidence immediately before use. It then recorded 32 real proof runs, 12 rejected attacks, six concurrency levels, five ablation repetitions, and budget-exhaustion trials. Expiry validation remains enabled. |
| exit 0 | `node .\zk\scripts\benchmark_zk.js` — 1/2/4/6/8/10-rule Groth16 measurements, two warm-ups and 12 measured proofs per size, written to `results/raw/phase8/zk_scaling.csv`. |
| exit 0 | `node .\zk\scripts\benchmark_zk_schemes.js` — Groth16, PLONK, and fflonk measurements, two warm-ups and 12 measured proofs per backend, written to `results/raw/phase8/zk_backends.csv`. |
| exit 0 | `python .\scripts\process_phase8_results.py` — created 15 processed CSV/JSON artifacts. |
| exit 0 | `python .\scripts\plot_all_results.py` — created 22 independent vector PDFs and 22 300-dpi PNG previews. |

The public-testnet branch was not run: `hardhat.config.js` defines only the
local Hardhat network and the repository supplies neither an RPC endpoint nor
an account configuration. This is recorded in
`results/raw/phase8/testnet/public_testnet_status.json`; no public-network value
was synthesized.

The requested native C++ reference also does not exist. Figures 6a–6c therefore
use the closest faithful replacement, the independently measured Python
aggregate reference, and label it as such in the manifest and captions. It is
not reported as native C++.

## Final clean regression (2026-07-19)

| Result | Command |
|---|---|
| exit 0 | `& "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" .\tee\vbs\TrustCircuitVbs.sln /m /t:Rebuild /p:Configuration=Debug /p:Platform=x64 /nologo /v:minimal` — clean x64 rebuild; EDL generation, VEIID, SignTool, enclave DLL, and host EXE succeeded. SignTool emitted only the documented VBS compatibility warning. |
| exit 0 | `powershell -NoProfile -ExecutionPolicy Bypass -File .\tee\vbs\tests\smoke.ps1 -Configuration Debug` — `Result = 200`. |
| exit 0 | `python .\tee\vbs\tests\phase2_hash_buffer.py` — 5/5. |
| exit 0 | `python .\tee\vbs\tests\phase3_aggregates.py` — 10/10. |
| exit 0 | `python .\tee\vbs\tests\phase4_encrypted_path.py` — 9/9. |
| exit 0 | `python .\tee\vbs\tests\phase5_dp_pipeline.py` — 7/7. |
| exit 0 | `python .\tee\vbs\tests\phase6_attestation.py` — 8/8. |
| exit 0 | `node .\zk\scripts\build_phase7.js`; `npm.cmd run compile`; `npm.cmd test` — circuit/key match, Solidity compile, 42/42 tests. |
| exit 0 | `python .\scripts\process_phase8_results.py`; `python .\scripts\plot_all_results.py` — 15 processed artifacts and all 44 panel exports regenerated. |
| exit 0 | `python -m py_compile tee/vbs/phase7_encoding.py tee/vbs/pipeline_client.py scripts/prepare_phase7_bundle.py scripts/run_phase8_vbs_experiments.py scripts/process_phase8_results.py scripts/plot_all_results.py`; `node --check` on the new JavaScript runners/encoders/ZK scripts — syntax checks passed. |
| exit 0 | Pillow/PDF header validation over `Paper/figures/panels` — 22 paired stems, no missing or unexpected panel, no empty/invalid PDF, and every PNG reports approximately 300 dpi. |

Generated Groth16/PLONK/fflonk verifier whitespace was normalized mechanically
after export; this changed no bytecode semantics. `Paper/main-old.tex` and
`Paper/Comment.txt` remain untouched.

## Trust and measurement labels

- VBS evidence and validation are real but same-machine/local-development
  evidence. The development certificate is not a production trust anchor.
- Chain gas and concurrency are measured on the local in-process Hardhat chain.
- Figure 4d and the no-TEE ablation combine directly measured components and are
  explicitly marked `model_calibrated` in raw/processed metadata.
- Figure 6e reports process RSS; the current Windows user-mode harness cannot
  isolate secure-kernel/enclave RSS.
- Statistical DP results use repeated trials and never assert exact noise.

## Metadata/warm-up audit

The final reproducibility audit found that the first chain and ZK config files
did not all carry the commit/seed/warm-up fields already present in the VBS
config. The runners were corrected and the affected measurements were rerun;
no raw numeric file was hand-edited.

| Result | Command |
|---|---|
| exit 0 | `.\node_modules\.bin\hardhat.cmd run .\benchmarks\phase8_chain_experiments.js --network hardhat` — reran in 53.9 seconds after one discarded Groth16 warm-up, one discarded full-pipeline warm-up, and one discarded budget-concurrency warm-up. The config now records timestamp, commit, dirty state, seed, warm-ups, OS, CPU, run counts, and duration. |
| exit 0 | `node .\zk\scripts\benchmark_zk.js` — reran in 63.5 seconds; the printed Circom errors are the deliberately invalid policy, budget, and nullifier witnesses and were recorded as successful rejections. Metadata now includes timestamp, commit/dirty state, deterministic-input label, machine, and warm-up/repetition counts. |
| exit 0 | `node .\zk\scripts\benchmark_zk_schemes.js` — reran in 129.3 seconds with the same metadata additions. |
| exit 0 | `python .\scripts\process_phase8_results.py`; `python .\scripts\plot_all_results.py`; `npm.cmd run compile`; `npm.cmd test` — regenerated the 15 processed artifacts and 22 PDF/PNG pairs, compiled regenerated verifier contracts, and passed all 42 tests. |
| exit 0 | Mechanical trailing-whitespace normalization of the three snarkjs-generated verifier files followed by `git diff --check`; no whitespace errors remain. Line-ending notices are Git's existing Windows conversion policy. |
| exit 0 | Final Python/Pillow/CSV/JSON integrity check plus repository-owned Node-process inspection — 22 paired panels, 22 manifest entries, no invalid PDF/PNG, 12 attacks with zero acceptance, six concurrency levels with zero budget invariant violations, successful attestation/proof/settlement state, and no leftover repository Node process. |

## Reproducible full-suite confirmation

The published top-level Phase 8 entrypoint was finally rerun as one uninterrupted
command after all fixes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_all_phase8_experiments.ps1 `
  -Configuration Debug `
  -SkipVbsBuild
```

Result: exit 0 in 260.1 seconds. It rebuilt the Phase 7 circuit interface,
compiled Solidity, collected 36 VBS performance rows and 54 privacy rows,
generated 32 fresh request/evidence bundles, ran the chain/attack/concurrency
suite, reran Groth16 scaling and Groth16/PLONK/fflonk comparisons, processed 15
artifacts, and regenerated all 22 PDF plus 22 PNG panels. The final line was
`PASS: Phase 8 raw data, processed data, and all panels generated`.

After snarkjs verifier export, the same mechanical whitespace normalization was
applied, then `npm.cmd run compile`, `npm.cmd test`, and `git diff --check` all
returned exit 0; the test result remained 42 passing.

## Legacy binding benchmark artifact fix

The final legacy-entrypoint audit noticed that `proof_binding_attacks.js` exited
zero but reported `honest_valid raw=0 adapter=0`. Root cause: it paired
`compliance_2_calldata.txt` from the scaling benchmark's Groth16 setup with the
final `ComplianceGroth16Verifier.sol` exported by the backend benchmark's
different Groth16 setup. The script now reads
`zk/build/cmp_2_groth16_calldata.txt`, which is generated alongside that final
verifier. No verification rule was relaxed.

```powershell
.\node_modules\.bin\hardhat.cmd run `
  .\benchmarks\proof_binding_attacks.js `
  --network hardhat
```

Final result: exit 0; honest case `mock=1 raw=1 adapter=1`; every context,
budget, and replay attack remains accepted by mock/raw but rejected by the
adapter; the tampered proof is rejected by both raw and adapter.
