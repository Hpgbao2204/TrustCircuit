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

The revised measurement used for `ab1_policy_time_revised_v2.pdf` and the
caption-free `ab1_policy_time_revised_v3.pdf` was run with separate output
paths so the earlier raw data also remained available:

```powershell
.\.venv\Scripts\python.exe crypto\run_cpabe_policy_benchmark.py `
  --policy-sizes 5 10 15 20 25 `
  --reps 30 `
  --warmups 5 `
  --payload-bytes 32 `
  --raw-output results\raw\cpabe_policy_benchmark_recheck_20260721.csv `
  --summary-output results\summary\cpabe_policy_summary_recheck_20260721.csv `
  --config-output results\summary\cpabe_policy_config_recheck_20260721.json

.\.venv\Scripts\python.exe crypto\plot_cpabe_policy.py `
  --summary results\summary\cpabe_policy_summary_recheck_20260721.csv
```

The benchmark builds the Rust binary in release mode and writes:

```text
results/raw/cpabe_policy_benchmark.csv
results/summary/cpabe_policy_summary.csv
results/summary/cpabe_policy_config.json
results/figures/abe/ab1_policy_time_revised.pdf
```

The raw CSV contains one row per operation and repetition. The summary reports
mean, standard deviation, median, and p95. The config records the toolchain,
host metadata, Git state, exclusions from timing, and the SHA-256 digest of the
raw CSV. The revised panel plots two-sided 95% Student-t confidence intervals
over the 30 independent repetitions. The original `ab1_policy_time.pdf` is
retained for side-by-side comparison.

## Interpretation boundary

These are implementation-level host measurements, not a proof that the two
cryptographic constructions provide equivalent security or identical runtime
semantics. AC17/FAME is the real pairing-based CP-ABE path; the KEM-DEM line is
the existing TrustCircuit baseline. The 32-byte payload deliberately isolates
policy-dependent key-encapsulation work rather than bulk AES throughput. Both
backends run on the same host with the same left-associated all-of-N topology
and the same 32-byte (256-bit) payload key. All N policy leaves are present in
the decryption key and participate in satisfying the policy; this is not a
fixed-k satisfying-set benchmark. In `rabe` AC17/FAME, the satisfying-row group
elements are aggregated before a fixed number of pairings, so pairing cost can
dominate the smaller N-dependent traversal and aggregation cost.
