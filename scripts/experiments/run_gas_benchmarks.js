"use strict";

// Gas and accounting benchmarks (Hardhat, chain 31337).
//   1. Settlement ablation: stage-wise vs sign-and-hash vs TrustCircuit
//      (identical contracts, 2-of-3 validator quorum, 30 settlements each,
//      TrustCircuit with real VCP v3 proofs)
//   2. Validator quorum sweep: k = 1, 2, 3 of n = 3
//   3. RDP ledger cost as a function of |O'| = 4, 8, 11, 16
//   4. On-chain cumulative RDP trace over 24 heterogeneous requests,
//      compared with an exact real-valued accountant
//
// Run: npx hardhat run scripts/experiments/run_gas_benchmarks.js
// Output: results/summary/gas_benchmarks.json,
//         results/raw/{settlement_gas,rdp_trace}.csv

const fs = require("fs");
const path = require("path");
const { ethers } = require("hardhat");
const S = require("../lib/v3_stack");

const ROOT = path.resolve(__dirname, "..", "..");
const RAW = path.join(ROOT, "results", "raw");
const SUMMARY = path.join(ROOT, "results", "summary", "gas_benchmarks.json");
const N_ABLATION = Number(process.env.TC_ABLATION_N || 30);
const N_SWEEP = Number(process.env.TC_SWEEP_N || 10);
const ALLOW = [[1n, 1n], [0n, 1n]];
const DELTA = 1e-5;
const CAL_MIX = [0.05, 0.1, 0.2, 0.5];
const ORDER_SETS = {
  4: [2, 4, 16, 64],
  8: [2, 3, 4, 8, 12, 16, 32, 64],
  11: S.DEFAULT_ORDERS,
  16: [2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 56, 64],
};

function sigmaFixedFor(epsilonCal, delta = DELTA) {
  // Gaussian mechanism calibration, Delta_2 f = 1, rounded up (more noise).
  return BigInt(Math.ceil((Math.sqrt(2 * Math.log(1.25 / delta)) / epsilonCal) * 1e6));
}

function quantile(values, q) {
  const s = [...values].sort((a, b) => a - b);
  const pos = (s.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}
const summarize = (values) => ({
  n: values.length,
  p50: quantile(values, 0.5),
  p95: quantile(values, 0.95),
  min: Math.min(...values),
  max: Math.max(...values),
  mean: values.reduce((a, b) => a + b, 0) / values.length,
});

async function gasOf(txPromise) {
  const receipt = await (await txPromise).wait();
  return Number(receipt.gasUsed);
}

async function lifecycle(stack, provider, consumer, asset, name, opts = {}) {
  const sigmaFixed = opts.sigmaFixed ?? sigmaFixedFor(CAL_MIX[opts.index % CAL_MIX.length]);
  const signers = opts.signers ?? stack.validators;
  const requestKey = `0x${S.enc.identifierDigest("request_id", name).toString("hex")}`;
  // Measure the reservation transaction separately from settlement.
  const request = await S.openRequest(stack, consumer, asset, {
    name, purposeId: 1, functionId: 2, sigmaFixed, stageAmount: 100_000,
  });
  const reserveTx = await ethers.provider.getTransactionReceipt(
    (await stack.settlement.queryFilter(
      stack.design === "stage" ? stack.settlement.filters.Admitted(requestKey) : stack.settlement.filters.ReservationForwarded(requestKey)
    )).at(-1).transactionHash
  );
  let settleGas;
  let proveMs = null;
  if (stack.design === "stage") {
    settleGas = await gasOf(S.settleStage(stack, request, ethers.id(`execution:${name}`), 7n, signers));
  } else {
    const bundle = await S.executeRequest(stack, request, { prove: stack.design === "trustcircuit" && opts.prove !== false, signers });
    proveMs = bundle.proveMs;
    settleGas =
      stack.design === "shs"
        ? await gasOf(S.settleShs(stack, request, bundle, 1, signers))
        : await gasOf(S.settleTrustCircuit(stack, request, bundle));
  }
  return { request, reserveGas: Number(reserveTx.gasUsed), settleGas, proveMs };
}

async function ablation(provider, consumer, validators) {
  const rows = [];
  const out = {};
  for (const design of ["stage", "shs", "trustcircuit"]) {
    const stack = await S.deployStack(ethers, design, { realVerifier: true, threshold: 2, validators });
    const asset = await S.registerAsset(stack, provider, {
      name: `ablation-${design}`, matrix: ALLOW, epsilonTotal: 1000, stageBudget: 10n ** 12n,
    });
    const settle = [];
    const reserve = [];
    const prove = [];
    for (let i = 0; i < N_ABLATION; i += 1) {
      const r = await lifecycle(stack, provider, consumer, asset, `ablation-${design}-${i}`, {
        index: i, signers: validators.slice(0, 2),
      });
      settle.push(r.settleGas);
      reserve.push(r.reserveGas);
      if (r.proveMs !== null) prove.push(r.proveMs);
      rows.push({ design, index: i, reserve_gas: r.reserveGas, settle_gas: r.settleGas, client_prove_ms: r.proveMs ?? "" });
    }
    out[design] = {
      settle_gas: summarize(settle),
      settle_gas_first: settle[0],
      settle_gas_after_first: summarize(settle.slice(1)),
      reserve_gas: summarize(reserve),
      client_prove_ms: prove.length ? summarize(prove) : null,
    };
    console.log(`[gas] ablation ${design}: settle p50 ${out[design].settle_gas.p50}`);
  }
  return { out, rows };
}

async function quorumSweep(provider, consumer, validators) {
  const out = {};
  for (const k of [1, 2, 3]) {
    const stack = await S.deployStack(ethers, "trustcircuit", { realVerifier: true, threshold: k, validators });
    const asset = await S.registerAsset(stack, provider, { name: `quorum-${k}`, matrix: ALLOW, epsilonTotal: 1000 });
    const settle = [];
    for (let i = 0; i < N_SWEEP; i += 1) {
      const r = await lifecycle(stack, provider, consumer, asset, `quorum-${k}-${i}`, { index: i, signers: validators.slice(0, k) });
      settle.push(r.settleGas);
    }
    out[`k${k}`] = { threshold: k, validators: validators.length, settle_gas: summarize(settle.slice(1)) };
    console.log(`[gas] quorum k=${k}: settle p50 ${out[`k${k}`].settle_gas.p50}`);
  }
  out.extra_gas_per_signature = {
    k1_to_k2: out.k2.settle_gas.p50 - out.k1.settle_gas.p50,
    k2_to_k3: out.k3.settle_gas.p50 - out.k2.settle_gas.p50,
  };
  return out;
}

async function orderSweep(provider, consumer, validators) {
  const out = {};
  for (const [size, orders] of Object.entries(ORDER_SETS)) {
    const stack = await S.deployStack(ethers, "trustcircuit", { realVerifier: true, threshold: 2, validators });
    const asset = await S.registerAsset(stack, provider, { name: `orders-${size}`, matrix: ALLOW, epsilonTotal: 1000, orders });
    const settle = [];
    const reserve = [];
    for (let i = 0; i < N_SWEEP; i += 1) {
      const r = await lifecycle(stack, provider, consumer, asset, `orders-${size}-${i}`, { index: i, signers: validators.slice(0, 2) });
      settle.push(r.settleGas);
      reserve.push(r.reserveGas);
    }
    out[`orders_${size}`] = {
      order_count: Number(size),
      orders,
      reserve_gas: summarize(reserve.slice(1)),
      settle_gas: summarize(settle.slice(1)),
      settle_gas_first: settle[0],
    };
    console.log(`[gas] |O'|=${size}: settle p50 ${out[`orders_${size}`].settle_gas.p50}, reserve p50 ${out[`orders_${size}`].reserve_gas.p50}`);
  }
  return out;
}

function exactEpsilon(rho, orders, delta) {
  let best = Infinity;
  orders.forEach((alpha, i) => {
    best = Math.min(best, rho[i] + Math.log(1 / delta) / (alpha - 1));
  });
  return best;
}

async function rdpTrace(provider, consumer, validators) {
  const stack = await S.deployStack(ethers, "trustcircuit", { realVerifier: false, threshold: 2, validators });
  const asset = await S.registerAsset(stack, provider, { name: "rdp-trace", matrix: ALLOW, epsilonTotal: 50 });
  const orders = asset.orders;
  const fullOrders = Array.from({ length: 63 }, (_, i) => i + 2);
  const rho = orders.map(() => 0);
  const rhoFull = fullOrders.map(() => 0);
  const rows = [];
  let maxGap = 0;
  let prevUsed = 0n;
  for (let q = 1; q <= 24; q += 1) {
    const epsilonCal = CAL_MIX[(q - 1) % CAL_MIX.length];
    const sigmaFixed = sigmaFixedFor(epsilonCal);
    const r = await lifecycle(stack, provider, consumer, asset, `trace-${q}`, { sigmaFixed, signers: validators.slice(0, 2), prove: false });
    const [, , used] = await stack.budget.getBudget(asset.assetKey);
    const z2 = (Number(sigmaFixed) / 1e6) ** 2;
    orders.forEach((alpha, i) => { rho[i] += alpha / (2 * z2); });
    fullOrders.forEach((alpha, i) => { rhoFull[i] += alpha / (2 * z2); });
    const epsCum = exactEpsilon(rho, orders, DELTA);
    const epsFull = exactEpsilon(rhoFull, fullOrders, DELTA);
    const gapUnits = Number(used) - 1e6 * epsCum;
    maxGap = Math.max(maxGap, gapUnits);
    if (gapUnits < 0 || gapUnits >= q + 1) throw new Error(`Lemma bound violated at q=${q}: gap ${gapUnits}`);
    rows.push({
      q,
      epsilon_cal: epsilonCal,
      sigma_fixed: sigmaFixed.toString(),
      reserved_b_req: r.request.reserved.toString(),
      charge_b_q: (used - prevUsed).toString(),
      onchain_used_U_q: used.toString(),
      exact_eps_cum_same_orders: epsCum.toFixed(6),
      exact_eps_cum_orders_2_64: epsFull.toFixed(6),
      gap_fixed_units: gapUnits.toFixed(3),
      bound_q_plus_1: q + 1,
    });
    prevUsed = used;
  }
  return {
    rows,
    summary: {
      requests: rows.length,
      orders,
      delta: DELTA,
      kappa: 1e6,
      final_onchain_epsilon: Number(prevUsed) / 1e6,
      final_exact_epsilon_same_orders: Number(rows.at(-1).exact_eps_cum_same_orders),
      final_exact_epsilon_orders_2_64: Number(rows.at(-1).exact_eps_cum_orders_2_64),
      max_gap_fixed_units: maxGap,
      max_gap_epsilon: maxGap / 1e6,
      lemma_bound_holds: true,
    },
  };
}

function writeCsv(file, rows) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const headers = Object.keys(rows[0]);
  fs.writeFileSync(file, `${headers.join(",")}\n${rows.map((r) => headers.map((h) => r[h]).join(",")).join("\n")}\n`);
}

async function main() {
  if (!S.haveProvingArtifacts()) throw new Error("VCP v3 proving artifacts are missing; run the ceremony first");
  const started = Date.now();
  const signers = await ethers.getSigners();
  const provider = signers[1];
  const consumer = signers[2];
  const validators = await S.makeValidators(ethers, 3);

  const { out: ablationOut, rows: ablationRows } = await ablation(provider, consumer, validators);
  writeCsv(path.join(RAW, "settlement_gas.csv"), ablationRows);
  const quorum = await quorumSweep(provider, consumer, validators);
  const orderOut = await orderSweep(provider, consumer, validators);
  const trace = await rdpTrace(provider, consumer, validators);
  writeCsv(path.join(RAW, "rdp_trace.csv"), trace.rows);

  const summary = {
    schema: "TrustCircuit.Revision.GasBenchmarks.v1",
    timestamp_utc: new Date().toISOString(),
    network: "hardhat (chain 31337), Solidity 0.8.24, optimizer 200 runs",
    ablation: { quorum: "2-of-3", settlements_per_design: N_ABLATION, ...ablationOut },
    quorum_sweep: quorum,
    rdp_order_sweep: orderOut,
    rdp_trace: trace.summary,
    seconds: (Date.now() - started) / 1000,
  };
  fs.mkdirSync(path.dirname(SUMMARY), { recursive: true });
  fs.writeFileSync(SUMMARY, `${JSON.stringify(summary, null, 2)}\n`);
  console.log(`[gas] done in ${summary.seconds.toFixed(1)} s`);
}

main()
  .catch((error) => {
    console.error(error);
    process.exitCode = 1;
  })
  .finally(() => process.exit(process.exitCode || 0));
