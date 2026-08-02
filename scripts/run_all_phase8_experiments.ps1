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
    & npm.cmd run vcp:test:real
    if ($LASTEXITCODE -ne 0) { throw "VCP v2 real-proof integration failed" }

    & python .\scripts\run_phase8_vbs_experiments.py `
        --configuration $Configuration `
        --performance-reps $PerformanceReps `
        --privacy-reps $PrivacyReps `
        --warmups $Warmups `
        --concurrency-bundles 32
    if ($LASTEXITCODE -ne 0) { throw "VBS/DP experiments failed" }

    & python .\scripts\run_attack_layer_audit.py
    if ($LASTEXITCODE -ne 0) { throw "Attack-layer audit failed" }

    & npm.cmd run vcp:benchmark
    if ($LASTEXITCODE -ne 0) { throw "VCP v2 benchmark failed" }

    Write-Output "PASS: current VBS and VCP v2 raw evidence generated"
}
finally {
    Pop-Location
}
