[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [ValidateRange(30, 100)]
    [int]$PerformanceReps = 30,
    [ValidateRange(30, 100)]
    [int]$PrivacyReps = 30,
    [ValidateRange(1, 20)]
    [int]$Warmups = 1,
    [string]$MSBuildPath = "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
    [switch]$SkipVbsBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    if (-not $SkipVbsBuild) {
        & $MSBuildPath `
            .\tee\vbs\TrustCircuitVbs.sln `
            /m `
            /t:Rebuild `
            "/p:Configuration=$Configuration" `
            /p:Platform=x64
        if ($LASTEXITCODE -ne 0) { throw "VBS rebuild/sign failed" }
    }

    & node .\zk\scripts\build_phase7.js
    if ($LASTEXITCODE -ne 0) { throw "Phase 7 circuit build failed" }
    & npm.cmd run compile
    if ($LASTEXITCODE -ne 0) { throw "Hardhat compilation failed" }
    & npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw "Hardhat regression tests failed" }

    # Fresh VBS evidence is generated immediately before proof/concurrency work
    # so every statement remains inside its five-minute validity interval.
    & python .\scripts\run_phase8_vbs_experiments.py `
        --configuration $Configuration `
        --performance-reps $PerformanceReps `
        --privacy-reps $PrivacyReps `
        --warmups $Warmups `
        --concurrency-bundles 32
    if ($LASTEXITCODE -ne 0) { throw "VBS/DP experiments failed" }

    & .\node_modules\.bin\hardhat.cmd run `
        .\benchmarks\phase8_chain_experiments.js `
        --network hardhat
    if ($LASTEXITCODE -ne 0) { throw "Phase 7 chain experiments failed" }

    & python .\scripts\run_attack_layer_audit.py
    if ($LASTEXITCODE -ne 0) { throw "Attack-layer audit failed" }

    & node .\zk\scripts\benchmark_zk.js
    if ($LASTEXITCODE -ne 0) { throw "ZK scaling experiment failed" }
    & node .\zk\scripts\benchmark_zk_schemes.js
    if ($LASTEXITCODE -ne 0) { throw "ZK backend experiment failed" }
    & .\node_modules\.bin\hardhat.cmd run `
        .\scripts\zk_schemes_gas.js `
        --network hardhat
    if ($LASTEXITCODE -ne 0) { throw "ZK backend gas experiment failed" }

    & python .\scripts\process_phase8_results.py
    if ($LASTEXITCODE -ne 0) { throw "Result processing failed" }
    & python .\scripts\plot_all_results.py
    if ($LASTEXITCODE -ne 0) { throw "Panel generation failed" }

    Write-Output "PASS: Phase 8 raw data, processed data, and all panels generated"
}
finally {
    Pop-Location
}
