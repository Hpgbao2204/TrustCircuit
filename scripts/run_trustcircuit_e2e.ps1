[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug",
    [ValidateSet("COUNT", "MEAN")]
    [string]$Function = "MEAN",
    [ValidateRange(1, 100000)]
    [int]$Rows = 256,
    [int]$Seed = 20260719,
    [double]$Epsilon = 1.0,
    [double]$Delta = 0.00001,
    [string]$MSBuildPath = "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe",
    [switch]$SkipVbsBuild,
    [switch]$SkipZkBuild
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$runId = [DateTimeOffset]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
$runDirectory = Join-Path $repoRoot "results\raw\e2e\$runId"
$bundlePath = Join-Path $runDirectory "vbs_bundle.json"
$settlementPath = Join-Path $runDirectory "settlement.json"
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null

Push-Location $repoRoot
try {
    if (-not $SkipZkBuild) {
        & node .\zk\scripts\build_phase7.js
        if ($LASTEXITCODE -ne 0) { throw "Phase 7 circuit build failed" }
    }

    if (-not $SkipVbsBuild) {
        if (-not (Test-Path -LiteralPath $MSBuildPath -PathType Leaf)) {
            throw "MSBuild not found: $MSBuildPath"
        }
        & $MSBuildPath `
            .\tee\vbs\TrustCircuitVbs.sln `
            /m `
            /t:Rebuild `
            "/p:Configuration=$Configuration" `
            /p:Platform=x64
        if ($LASTEXITCODE -ne 0) { throw "VBS x64 build/sign failed" }
    }

    & npm.cmd run compile
    if ($LASTEXITCODE -ne 0) { throw "Hardhat compilation failed" }

    & python .\scripts\prepare_phase7_bundle.py `
        --output $bundlePath `
        --configuration $Configuration `
        --function $Function `
        --rows $Rows `
        --seed $Seed `
        --epsilon $Epsilon `
        --delta $Delta
    if ($LASTEXITCODE -ne 0) { throw "VBS execution/attestation failed" }

    $previousBundle = $env:TRUSTCIRCUIT_PHASE7_BUNDLE
    $previousOutput = $env:TRUSTCIRCUIT_PHASE7_OUTPUT
    try {
        $env:TRUSTCIRCUIT_PHASE7_BUNDLE = $bundlePath
        $env:TRUSTCIRCUIT_PHASE7_OUTPUT = $settlementPath
        & .\node_modules\.bin\hardhat.cmd run .\scripts\run_trustcircuit_e2e.js --network hardhat
        if ($LASTEXITCODE -ne 0) { throw "Phase 7 on-chain settlement failed" }
    }
    finally {
        $env:TRUSTCIRCUIT_PHASE7_BUNDLE = $previousBundle
        $env:TRUSTCIRCUIT_PHASE7_OUTPUT = $previousOutput
    }

    $result = Get-Content -Raw -LiteralPath $settlementPath | ConvertFrom-Json
    if ($result.ok -ne $true -or $result.settlement.audit_events -ne 1) {
        throw "Phase 7 output invariant failed"
    }
    Write-Output "PASS: TrustCircuit Phase 7 E2E settled request $($result.request_key)"
    Write-Output "Raw result: $settlementPath"
}
finally {
    Pop-Location
}

