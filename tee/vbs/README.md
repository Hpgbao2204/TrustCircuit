# TrustCircuit VBS Enclave - Phase 1

This directory contains the independent x64 Windows VBS Enclave skeleton for
TrustCircuit. Phase 1 implements only a generated EDL call that multiplies
`10 * 20` inside `TrustCircuitEnclave.dll` and returns `Result = 200` through
`TrustCircuitHost.exe`.

It does not implement request JSON, hashing, encryption, differential privacy,
attestation, blockchain settlement, or proof integration.

## Local configuration

Copy the template and update it for the current machine:

```powershell
Copy-Item `
  .\tee\vbs\TrustCircuitVbs.Local.props.example `
  .\tee\vbs\TrustCircuitVbs.Local.props
```

`TrustCircuitVbs.Local.props` is ignored by Git. It contains local package/tool
paths and the public thumbprint of the local test-signing certificate. Never put
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

See `PHASE1_COMMAND_LOG.md` for the exact commands run during implementation.
