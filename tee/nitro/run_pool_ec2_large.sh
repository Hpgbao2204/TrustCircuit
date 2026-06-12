#!/usr/bin/env bash
set -euo pipefail

# Run on an AWS Nitro Enclaves parent instance with enough vCPUs.
# Recommended: m6i.4xlarge or larger.
#
# Each Nitro Enclave is assigned 2 vCPUs because Nitro requires full CPU cores.
# Worker counts 1, 2, and 4 therefore reserve 2, 4, and 8 vCPUs respectively.

cd ~/TrustCircuit

nitro-cli terminate-enclave --all || true

sudo tee /etc/nitro_enclaves/allocator.yaml > /dev/null <<'EOF'
---
memory_mib: 12288
cpu_count: 12
EOF
sudo systemctl restart nitro-enclaves-allocator.service

rm -f results/raw/nitro_pool.csv

run_workers() {
  count="$1"
  cids=""
  for i in $(seq 1 "$count"); do
    cid=$((15 + i))
    nitro-cli run-enclave \
      --eif-path tee/nitro/trustcircuit-nitro-worker.eif \
      --cpu-count 2 \
      --memory 1024 \
      --enclave-cid "$cid" >/tmp/nitro_run_"$cid".log
    cids="$cids $cid"
  done

  sleep 2
  echo "running Nitro pool benchmark: workers=$count cids=$cids"
  python3 tee/nitro/pool_benchmark.py \
    --cids $cids \
    --requests 120 \
    --payload-mib 1 \
    --out results/raw/nitro_pool.csv

  nitro-cli terminate-enclave --all || true
  sleep 1
}

run_workers 1
run_workers 2
run_workers 4
run_workers 6

python3 tee/nitro/plot_nitro_results.py
