param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Debug"
)

$ErrorActionPreference = "Stop"

$vbsRoot = Split-Path -Parent $PSScriptRoot
$outputDir = Join-Path $vbsRoot "x64\$Configuration"
$hostPath = Join-Path $outputDir "TrustCircuitHost.exe"
$enclavePath = Join-Path $outputDir "TrustCircuitEnclave.dll"

if (-not (Test-Path -LiteralPath $hostPath)) {
    throw "Missing host executable: $hostPath"
}

if (-not (Test-Path -LiteralPath $enclavePath)) {
    throw "Missing enclave DLL: $enclavePath"
}

Push-Location $outputDir
try {
    $output = & $hostPath 2>&1
    $hostExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

$output | ForEach-Object { Write-Host $_ }

if ($hostExitCode -ne 0) {
    throw "TrustCircuitHost exited with code $hostExitCode"
}

if ($output -notcontains "Result = 200") {
    throw "Expected output 'Result = 200' was not found"
}

Write-Host "PASS: TrustCircuit VBS enclave returned Result = 200"
