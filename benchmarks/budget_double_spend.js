/*
 * Experiment 4 (Q1 plan): concurrent budget double-spend stress test.
 *
 * Many requests are submitted into the SAME block (automine disabled) and each
 * tries to reserve epsilon from a fixed asset budget. A correct ledger must
 * accept at most floor(budget/epsilon) of them regardless of concurrency, so
 * the on-chain conservation invariant holds even under a same-block race.
 *
 * Sweep: concurrency x epsilon x budget, repeated `trials` times.
 * Metrics: overspend_accepted_rate, blocked_rate, attack_success_rate,
 *          final_budget_consistent.
 *
 * Output: results/q1/raw/budget_double_spend.csv
 *
 * Usage: npx hardhat run benchmarks/budget_double_spend.js
 */
const fs = require("fs");
const path = require("path");
const { ethers, network } = require("hardhat");

const EPSILON_SCALE = 1_000_000n;
const CONCURRENCY = [2, 4, 8, 16, 32];
const EPSILONS = [0.25, 0.5, 1.0];
const BUDGETS = [2.0, 5.0, 10.0];
const TRIALS = 50;

function toFixed(x) {
  return BigInt(Math.round(x * Number(EPSILON_SCALE)));
}

function csvEscape(v) {
  const t = String(v ?? "");
  return /[",\n]/.test(t) ? `"${t.replaceAll('"', '""')}"` : t;
}

function writeCsv(filePath, rows) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const headers = Object.keys(rows[0]);
  const content = [headers.join(","), ...rows.map((r) => headers.map((h) => csvEscape(r[h])).join(","))].join("\n");
  fs.writeFileSync(filePath, `${content}\n`);
}

async function setAutomine(on) {
  await network.provider.send("evm_setAutomine", [on]);
}

async function mine() {
  await network.provider.send("evm_mine", []);
}

async function runTrial(budgetLedger, concurrency, epsilon, budget, trial) {
  const epsFixed = toFixed(epsilon);
  const totalFixed = toFixed(budget);
  const assetId = ethers.id(`ds:${concurrency}:${epsilon}:${budget}:${trial}:${Math.random()}`);
  await (await budgetLedger.registerBudget(assetId, totalFixed)).wait();

  const capacity = Number(totalFixed / epsFixed); // max correctly-acceptable

  // queue `concurrency` reservations into one block, then mine together.
  await setAutomine(false);
  const sent = [];
  for (let i = 0; i < concurrency; i += 1) {
    const requestId = ethers.id(`ds-req:${assetId}:${i}`);
    sent.push(budgetLedger.reserveBudget(assetId, requestId, epsFixed).catch((e) => ({ __err: e })));
  }
  const submitted = await Promise.all(sent);
  await mine();
  await setAutomine(true);

  // resolve receipts: a tx is "accepted" iff it was mined successfully.
  let accepted = 0;
  for (const txOrErr of submitted) {
    if (txOrErr && txOrErr.__err) continue;
    try {
      const rec = await txOrErr.wait();
      if (rec && rec.status === 1) accepted += 1;
    } catch (e) {
      /* reverted in-block -> blocked */
    }
  }

  const blocked = concurrency - accepted;
  const overspendAccepted = Math.max(0, accepted - capacity);
  // verify the ledger's own state never went negative.
  const [total, reserved, used, remaining] = await budgetLedger.getBudget(assetId);
  const consistent = reserved + used <= total && remaining >= 0n;

  return {
    concurrency,
    epsilon,
    budget,
    trial,
    capacity,
    accepted,
    blocked,
    overspend_accepted: overspendAccepted,
    attack_success: overspendAccepted > 0 ? 1 : 0,
    reserved_fixed: reserved.toString(),
    used_fixed: used.toString(),
    remaining_fixed: remaining.toString(),
    final_budget_consistent: consistent ? 1 : 0,
  };
}

async function main() {
  const BudgetLedger = await ethers.getContractFactory("BudgetLedger");
  const budgetLedger = await BudgetLedger.deploy();
  await budgetLedger.waitForDeployment();

  const rows = [];
  for (const concurrency of CONCURRENCY) {
    for (const epsilon of EPSILONS) {
      for (const budget of BUDGETS) {
        for (let trial = 0; trial < TRIALS; trial += 1) {
          rows.push(await runTrial(budgetLedger, concurrency, epsilon, budget, trial));
        }
      }
    }
    process.stdout.write(`[double-spend] concurrency=${concurrency} done\n`);
  }
  // ensure automine restored even if something threw mid-run.
  await setAutomine(true);

  const out = path.join("results", "q1", "raw", "budget_double_spend.csv");
  writeCsv(out, rows);
  console.log(out);
}

main().catch(async (e) => { console.error(e); try { await setAutomine(true); } catch { } process.exitCode = 1; });
