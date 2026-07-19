# Full CP-ABE Policy-Latency Benchmark

This benchmark replaces the two-curve CP-ABE-style wrapper panel with a
four-curve, directly measured comparison:

- TrustCircuit KEM-DEM baseline: LSSS all-of-N policy, secp256k1 ECIES per
  policy leaf, and AES-256-GCM;
- Full CP-ABE: pairing-based AC17/FAME CP-ABE from `rabe` 0.4.2.

Both implementations use the same policy sizes (`5, 10, 15, 20, 25`), the
same 32-byte plaintext, five warm-up executions per policy size, and 30 timed
repetitions. Scheme setup and user-key generation occur outside the timed
region. Every timed decryption is checked against the original plaintext.

The all-of-N policy is encoded as a binary conjunction because the AC17 policy
parser requires exactly two children per AND node. The user key contains all N
attributes, so every tested policy is satisfied.

## Reproduce

Install Rust with the official `rustup` installer, then run from the repository
root:

```powershell
npm.cmd run abe:cpabe:benchmark
npm.cmd run abe:cpabe:plot
```

The benchmark builds the Rust binary in release mode and writes:

```text
results/raw/cpabe_policy_benchmark.csv
results/summary/cpabe_policy_summary.csv
results/summary/cpabe_policy_config.json
results/figures/abe/ab1_policy_time.pdf
```

The raw CSV contains one row per operation and repetition. The summary reports
mean, standard deviation, median, and p95. The config records the toolchain,
host metadata, Git state, exclusions from timing, and the SHA-256 digest of the
raw CSV.

## Interpretation boundary

These are implementation-level host measurements, not a proof that the two
cryptographic constructions provide equivalent security or identical runtime
semantics. AC17/FAME is the real pairing-based CP-ABE path; the KEM-DEM line is
the existing TrustCircuit baseline. The 32-byte payload deliberately isolates
policy-dependent public-key work rather than bulk AES throughput.
