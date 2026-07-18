# TrustCircuit VBS protocol (Phases 2-5)

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
`transcript_hash` binds canonical AAD, execution time, noisy fixed result,
privacy cost, result hash, and the Phase 5 enclave identity string. Native VBS
attestation is intentionally deferred to Phase 6; `attestation_evidence` is
therefore `null` and its timing is zero.

Enclave stage timings use TSC with host calibration. They are measurement
metadata, not trusted security inputs.
