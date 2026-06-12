#!/usr/bin/env bash
set -uo pipefail

# TrustCircuit Nitro Enclaves worker-pool benchmark for m6i.8xlarge.
#
# m6i.8xlarge has 32 vCPUs and 128 GiB RAM. AWS Nitro Enclaves allows at most
# four enclaves per parent EC2 instance, so this script measures 1--4 real
# workers. plot_nitro_results.py then extrapolates the scaling curves to 64
# workers and labels those points as projected.

cd ~/TrustCircuit || exit 1

EIF="tee/nitro/trustcircuit-nitro-worker.eif"
OUT="results/raw/nitro_pool.csv"

if [[ ! -f "$EIF" ]]; then
  echo "Missing EIF: $EIF"
  echo "Build it first with:"
  echo "  cd ~/TrustCircuit/tee/nitro"
  echo "  docker build -t trustcircuit-nitro-worker ."
  echo "  nitro-cli build-enclave --docker-uri trustcircuit-nitro-worker:latest --output-file trustcircuit-nitro-worker.eif"
  exit 1
fi

echo "== cleaning old enclaves =="
nitro-cli terminate-enclave --all || true

echo "== configuring Nitro allocator for m6i.8xlarge =="
sudo tee /etc/nitro_enclaves/allocator.yaml > /dev/null <<'EOF'
---
memory_mib: 8192
cpu_count: 8
EOF

sudo systemctl restart nitro-enclaves-allocator.service
systemctl status nitro-enclaves-allocator.service --no-pager

mkdir -p results/raw results/summary results/figures/nitro
rm -f "$OUT"

run_workers() {
  local count="$1"
  local cids=""

  echo
  echo "== launching $count Nitro worker enclave(s) =="
  nitro-cli terminate-enclave --all || true
  sleep 2

  for i in $(seq 1 "$count"); do
    local cid=$((15 + i))
    if ! nitro-cli run-enclave \
      --eif-path "$EIF" \
      --cpu-count 2 \
      --memory 1024 \
      --enclave-cid "$cid" >/tmp/nitro_run_"$cid".log; then
      echo "Launch failed at worker $i / target $count. Keeping previous successful results."
      cat /tmp/nitro_run_"$cid".log || true
      nitro-cli terminate-enclave --all || true
      return 1
    fi
    cids="$cids $cid"
  done

  sleep 3
  echo "== benchmarking workers=$count cids=$cids =="
  if ! python3 tee/nitro/pool_benchmark.py \
    --cids $cids \
    --requests 240 \
    --payload-mib 1 \
    --out "$OUT"; then
    echo "Benchmark failed for workers=$count. Keeping previous successful results."
    nitro-cli terminate-enclave --all || true
    return 1
  fi

  nitro-cli terminate-enclave --all || true
  sleep 2
}

for workers in 1 2 3 4; do
  if ! run_workers "$workers"; then
    echo "Stopping scale-up after failed target: $workers"
    break
  fi
done

echo
echo "== regenerating Nitro figures =="
python3 tee/nitro/plot_nitro_results.py
python3 tee/nitro/plot_nitro_figure6.py

echo
echo "== done =="
echo "Raw CSV:      $OUT"
echo "Summary CSV:  results/summary/nitro_pool_summary.csv"
echo "Figures dir:  results/figures/nitro"
