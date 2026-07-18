# TrustCircuit VBS protocol (Phases 2-6)

All strings are UTF-8. All integers in binary canonical data are little-endian.
Current limits are 1 MiB for `HashBuffer`, 100,000 dataset rows, 128 bytes per
identifier, 1,024 bytes for the encrypted payload path, and 4,096 AAD bytes.

## Dataset payload

```text
offset  size  type     value
0       8     bytes    TCVBSDS1
8       4     uint32   version = 1
12      4     uint32   row_count
16      8*N   int64    values at fixed-point scale 1e6
```

The enclave rejects a non-exact length, unsupported version/function, more than
100,000 rows, values outside the request bounds, empty MEAN, and integer
overflow. Function IDs are `1 = COUNT`, `2 = MEAN`. COUNT and MEAN results use
fixed-point scale 1e6; integer division truncates toward zero.

## JSON request

`TrustCircuitHost.exe <request.json>` accepts one flat object containing:

```text
operation = "execute"
request_id, asset_id, consumer_id
policy_hash (64 lowercase SHA-256 hex characters)
policy_version, function_id
epsilon_requested, delta_requested
epsilon_requested_fixed = ceil(epsilon_requested * 1e6)
delta_requested_fixed = ceil(delta_requested * 1e12)
encrypted_payload_path
key_hex (development-only 32-byte AES key)
nonce (12-byte hex)
authentication_tag (16-byte hex)
aad (canonical AAD hex)
data_hash (SHA-256 of plaintext payload)
lower_bound_fixed, upper_bound_fixed
deadline_unix_ms
apply_dp
```

The development key handoff through the untrusted host is not production key
provisioning. It exists only to complete and test the local VBS data path.

## Canonical AAD

The byte sequence begins with `TrustCircuit.Request.v1` followed by `00`.
Each string is encoded as `uint32 byte_length || UTF-8 bytes`, in this order:

```text
request_id, asset_id, consumer_id, policy_hash, encrypted_payload_path
```

It then appends:

```text
data_hash[32]
policy_version:uint64
function_id:uint32
epsilon_requested_fixed:uint64
delta_requested_fixed:uint64
lower_bound_fixed:int64
upper_bound_fixed:int64
deadline_unix_ms:uint64
apply_dp:uint8 (0 or 1)
```

The enclave reconstructs and constant-time compares this AAD before decrypting.
AES-256-GCM also authenticates ciphertext, nonce, tag, and AAD.

## DP and output hashes

Gaussian noise uses BCrypt system-preferred randomness. For epsilon in `(0,1]`
and delta in `(0,1)`, the noise multiplier is:

```text
sqrt(2 * ln(1.25 / delta)) / epsilon
```

COUNT sensitivity is 1. MEAN sensitivity is `(upper-lower)/row_count`.
The reported cost is:

```text
ceil(max(requested epsilon, min RDP conversion for alpha=2..64) * 1e6)
```

`result_hash` is SHA-256 over `TrustCircuit.Result.v1 || 00 || result_fixed`.

## Canonical execution transcript

The processor enclave calls `EnclaveGetEnclaveInformation` and hashes the
following identity bytes:

```text
TrustCircuit.EnclaveIdentity.v1 || 00
OwnerId[32] || UniqueId[32] || AuthorId[32]
FamilyId[16] || ImageId[16]
EnclaveSvn:uint32
SecureKernelSvn:uint32
PlatformSvn:uint32
Flags:uint32
SigningLevel:uint32
EnclaveType:uint32
```

The canonical transcript is serialized and hashed inside the processor enclave:

```text
TrustCircuit.Execution.v1 || 00
canonical_aad
execution_unix_ms:uint64
result_fixed:int64
actual_privacy_cost_fixed:uint64
result_hash[32]
enclave_identity_hash[32]
```

Because `canonical_aad` contains request ID, asset ID, consumer ID, policy hash
and version, function ID, committed data hash, privacy request, bounds,
deadline, payload path, and DP flag, the transcript binds all of those fields.
The Python reference in `tests/vbs_reference.py` independently reconstructs the
same bytes.

## Native VBS evidence

The 64-byte `EnclaveData` challenge passed to
`EnclaveGetAttestationReport` is:

```text
transcript_hash[32]
SHA256(TrustCircuit.Attestation.v1 || 00 || transcript_hash)[32]
```

The returned bytes are a real Windows `VBS_ENCLAVE_REPORT_PKG_HEADER`, signed
statement, and RSA-PSS signature. They are not a mock and are never parsed as a
trusted result in ordinary host code.

`attestation_validator.py` starts a separate `TrustCircuitHost.exe` process,
which loads another VBS enclave instance. The validator enclave calls
`EnclaveVerifyAttestationReport`, reconstructs the complete transcript, checks
the challenge, checks the caller's expected identity, and requires the report
identity to equal its own current code identity. It also checks:

```text
issued_at_unix_ms = execution_unix_ms
expires_at_unix_ms = min(deadline_unix_ms, execution_unix_ms + 300000)
issued_at_unix_ms <= validator current time <= expires_at_unix_ms
```

This is deliberately same-machine validation: Windows only permits
`EnclaveVerifyAttestationReport` inside another VBS enclave and only for reports
generated on the current system.

## Compact signed statement

After successful enclave validation, the external validator obtains the local
certificate identified by `ValidatorSigningThumbprint` from CurrentUser/My. It
hashes the certificate DER with SHA-256 to form `validator_identity` and signs:

```text
TrustCircuit.AttestationStatement.v1 || 00
transcript_hash[32]
enclave_identity_hash[32]
issued_at_unix_ms:uint64
expires_at_unix_ms:uint64
native_evidence_sha256[32]
validator_identity[32]
```

The detached signature algorithm is RSA-PSS-SHA256 with a 32-byte salt. The
compact JSON statement contains `format`, `validated`, `transcript_hash`,
`enclave_identity`, issue/expiry times, `validator_identity`,
`evidence_sha256`, `signature_algorithm`, `signature`, and
`native_verification`. The raw native report is omitted from the final
`run_pipeline.py` output after validation.

## Trust assumptions and limitations

- Native report authenticity and same-machine identity validation rely on the
  Windows VBS secure kernel and `EnclaveVerifyAttestationReport`.
- The current Debug build, Test Signing mode, and development certificates are
  not production remote attestation or a production trust anchor.
- VBS native reports do not supply a trusted wall-clock timestamp. Freshness
  uses the external validator host's Windows clock and the transcript-bound
  request deadline.
- The compact signer runs outside the enclave. Its executable, certificate
  pin, private-key ACL, and CurrentUser certificate store are part of the local
  validator trust boundary. A production compressor should use a separately
  protected service key and independent authorization/audit controls.
- Native evidence is same-machine only; Phase 6 does not prove host boot-state
  attestation to a remote verifier, nor does it integrate Circom or Solidity.

Enclave stage timings use TSC with host calibration. They are measurement
metadata, not trusted security inputs.
