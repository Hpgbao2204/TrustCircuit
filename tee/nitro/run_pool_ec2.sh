#!/usr/bin/env bash
set -euo pipefail

cd ~/TrustCircuit

nitro-cli terminate-enclave --all || true

sudo tee /etc/nitro_enclaves/allocator.yaml > /dev/null <<'EOF'
---
memory_mib: 4096
cpu_count: 2
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
      --cpu-count 1 \
      --memory 1024 \
      --enclave-cid "$cid" >/tmp/nitro_run_"$cid".log
    cids="$cids $cid"
  done
  sleep 2
  echo "running pool benchmark count=$count cids=$cids"
  python3 tee/nitro/pool_benchmark.py --cids $cids --requests 60 --payload-mib 1
  nitro-cli terminate-enclave --all || true
  sleep 1
}

run_workers 1
run_workers 2
python3 tee/nitro/plot_nitro_results.py
