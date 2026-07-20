# AES-256-GCM throughput and host-memory scaling

This experiment isolates host-side bulk symmetric encryption. It is not
access-control throughput, CP-ABE throughput, or enclave memory. CP-ABE policy
cost is measured separately in Fig. 5(b).

The runner uses synchronous `node:crypto` AES-256-GCM on one JavaScript thread,
backed by the OpenSSL version recorded in the config JSON. Each repetition runs
in a fresh process, performs an untimed warm-up, and excludes process startup,
payload allocation, and correctness comparison from the crypto timers.
Throughput is `payload MiB / measured wall-clock operation time`.

## Reproduce the measurements

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe crypto\run_aes_gcm_scaling.py `
  --sizes-mib 1 2 4 8 16 32 64 128 256 512 `
  --reps 10 `
  --chunk-mib 4
```

This writes:

```text
results/raw/aes_gcm_scaling_v2.csv
results/summary/aes_gcm_scaling_v2_summary.csv
results/summary/aes_gcm_scaling_v2_config.json
```

Render the revised panels with:

```powershell
.\.venv\Scripts\python.exe crypto\plot_aes_gcm_revised.py
```

The original `ab4_throughput.pdf` and `ab6_peak_rss.pdf` remain unchanged. The
clean, caption-free files are `ab4_throughput_revised_v2.pdf` and
`ab6_peak_rss_revised_v2.pdf`; the earlier revised PDFs also remain unchanged.
The older payload-time panel `ab3_payload_time.pdf` is retained only as
supplementary/raw-data validation because it is algebraically redundant with
the throughput panel and is not used as Fig. 5(c).

## Memory semantics

`idle_rss_mib` is sampled after warm-up and an explicit garbage collection.
`peak_rss_mib` is the largest host-process RSS observed at full-buffer stages
or chunk boundaries. The plotted metric is:

```text
incremental peak RSS = observed peak RSS - idle RSS
```

Full-buffer mode retains the plaintext, ciphertext, recovered plaintext, and
`Buffer.concat` copies concurrently. Chunked mode uses 4 MiB AES-GCM updates
and consumes each output chunk immediately. It models bounded-buffer
processing; it does not write the ciphertext to persistent storage. The 1×
payload line is a reference for the buffered representation, not a universal
lower bound: streaming incremental RSS can be smaller than the total payload.
RSS is sampled rather than OS event-traced, so a shorter transient peak between
samples may be missed.
