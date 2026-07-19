/*
 * Phase 8 local-chain experiments over real Phase 6 VBS evidence and the real
 * Phase 7 Groth16 verifier. Outputs machine-readable CSV/JSON only; plotting is
 * performed later from these files.
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");
const snarkjs = require("snarkjs");
const { buildPoseidon } = require("circomlibjs");
const { ethers, network } = require("hardhat");
const {
  buildProofInput,
  contextFields,
} = require("../scripts/lib/phase7_encoding");

const ROOT = path.resolve(__dirname, "..");
const RAW = path.join(ROOT, "results", "raw", "phase8");
const BUNDLES = path.join(RAW, "concurrency_bundles");
const WASM = path.join(ROOT, "zk", "build", "phase7_js", "phase7.wasm");
const ZKEY = path.join(ROOT, "zk", "build", "phase7_final.zkey");
const VKEY = path.join(ROOT, "zk", "build", "phase7_vkey.json");
const CONCURRENCY_LEVELS = [1, 2, 4, 8, 16, 32];
const EXPERIMENT_SEED = 20260719;

function gitValue(args) {
  return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
}

function nowMs() {
  return Number(process.hrtime.bigint()) / 1e6;
}

function hex(value) {
  return Buffer.isBuffer(value)
    ? `0x${value.toString("hex")}`
    : ethers.zeroPadValue(ethers.toBeHex(BigInt(value)), 32);
}

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function writeCsv(filePath, rows) {
  if (!rows.length) throw new Error(`refusing to write empty CSV: ${filePath}`);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const headers = Object.keys(rows[0]);
  fs.writeFileSync(
    filePath,
    `${headers.join(",")}\n${rows
      .map((row) => headers.map((header) => csvEscape(row[header])).join(","))
      .join("\n")}\n`
  );
}

async function transaction(metric, stage, promise) {
  const started = nowMs();
  const tx = await promise;
  const receipt = await tx.wait();
  metric.latency_ms += nowMs() - started;
  metric.gas += receipt.gasUsed;
  metric.stage_latency[stage] =
    (metric.stage_latency[stage] || 0) + (nowMs() - started);
  metric.stage_gas[stage] = (metric.stage_gas[stage] || 0n) + receipt.gasUsed;
  return receipt;
}

async function deployContract(name, ...args) {
  const factory = await ethers.getContractFactory(name);
  const contract = await factory.deploy(...args);
  await contract.waitForDeployment();
  return contract;
}

async function deploySystem() {
  const registry = await deployContract("DataRegistry");
  const access = await deployContract("AccessController");
  const budget = await deployContract("BudgetLedger");
  const audit = await deployContract("AuditLedger");
  const native = await deployContract("Phase7Groth16Verifier");
  const adapter = await deployContract("ComplianceVerifier", await native.getAddress());
  const settlement = await deployContract(
    "TrustCircuitSettlement",
    await registry.getAddress(),
    await access.getAddress(),
    await budget.getAddress(),
    await adapter.getAddress(),
    await audit.getAddress()
  );
  return { registry, access, budget, audit, native, adapter, settlement };
}

function preparedContext(prepared) {
  const { bundle, proofInput } = prepared;
  const values = proofInput.values;
  return {
    values,
    requestKey: hex(values.requestKey),
    assetKey: hex(values.assetKey),
    policyHash: hex(values.policyHash),
    dataHash: `0x${bundle.request.data_hash}`,
    evidence: {
      dataHash: `0x${bundle.request.data_hash}`,
      resultHash: hex(values.resultHash),
      transcriptHash: hex(values.transcriptHash),
      attestationDigest: hex(values.attestationDigest),
    },
    expected: {
      requestId: values.request_id,
      assetId: values.asset_id,
      consumerId: values.consumer_id,
      policyHash: values.policy_hash,
      policyVersion: values.policy_version,
      functionId: values.function_id,
      resultHash: values.result_hash,
      maxEpsilon: values.actual_privacy_cost_fixed,
      transcriptHash: values.transcript_hash,
      attestationDigest: values.attestation_digest,
      attestationExpiresAtUnixMs:
        bundle.execution.attestation_evidence.expires_at_unix_ms,
    },
  };
}

async function prepareProofs() {
  const paths = fs
    .readdirSync(BUNDLES)
    .filter((name) => /^bundle_\d+\.json$/.test(name))
    .sort()
    .map((name) => path.join(BUNDLES, name));
  if (paths.length < 32) throw new Error("32 fresh VBS concurrency bundles are required");
  const poseidon = await buildPoseidon();
  const verificationKey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  const warmupBundle = JSON.parse(fs.readFileSync(paths[0], "utf8"));
  const warmupInput = buildProofInput(
    warmupBundle.request,
    warmupBundle.execution,
    poseidon,
    202607189999n
  );
  const warmup = await snarkjs.groth16.fullProve(warmupInput.input, WASM, ZKEY);
  if (!(await snarkjs.groth16.verify(
    verificationKey,
    warmup.publicSignals,
    warmup.proof
  ))) {
    throw new Error("Phase 7 proof warm-up verification failed");
  }
  const prepared = [];
  const proofRows = [];
  for (let index = 0; index < paths.length; index += 1) {
    const bundle = JSON.parse(fs.readFileSync(paths[index], "utf8"));
    const proofInput = buildProofInput(
      bundle.request,
      bundle.execution,
      poseidon,
      202607190000n + BigInt(index)
    );
    const proveStarted = nowMs();
    const { proof, publicSignals } = await snarkjs.groth16.fullProve(
      proofInput.input,
      WASM,
      ZKEY
    );
    const proveMs = nowMs() - proveStarted;
    const verifyStarted = nowMs();
    const verified = await snarkjs.groth16.verify(
      verificationKey,
      publicSignals,
      proof
    );
    const verifyMs = nowMs() - verifyStarted;
    if (!verified) throw new Error(`off-chain proof verification failed at ${index}`);
    const calldata = JSON.parse(
      `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
    );
    prepared.push({
      index,
      bundle,
      proofInput,
      proof,
      publicSignals,
      a: calldata[0],
      b: calldata[1],
      c: calldata[2],
      signals: calldata[3],
      proveMs,
      verifyMs,
    });
    proofRows.push({
      measurement_type: "measured",
      index,
      request_id: bundle.request.request_id,
      prove_time_ms: proveMs,
      verify_time_ms: verifyMs,
      proof_bundle_bytes: Buffer.byteLength(JSON.stringify({ proof, publicSignals })),
      verified: 1,
    });
    process.stdout.write(`[phase8-chain] proof ${index + 1}/${paths.length}\n`);
  }
  writeCsv(path.join(RAW, "phase7_proof_runs.csv"), proofRows);
  return prepared;
}

async function createFreshPrepared(label, index) {
  // Hardhat advances block timestamps monotonically. Long benchmark runs can
  // move its clock ahead of the Windows clock used by fresh VBS statements;
  // reset before each evidence-dependent isolated trial so both start from the
  // same local wall-clock epoch. This does not bypass the expiry check.
  await network.provider.send("hardhat_reset");
  const directory = path.join(RAW, "fresh_bundles");
  fs.mkdirSync(directory, { recursive: true });
  const bundlePath = path.join(directory, `${label}_${index}.json`);
  execFileSync(
    "python",
    [
      path.join(ROOT, "scripts", "prepare_phase7_bundle.py"),
      "--output",
      bundlePath,
      "--configuration",
      "Debug",
      "--function",
      "MEAN",
      "--rows",
      "64",
      "--seed",
      "20260719",
      "--asset-id",
      `asset-phase8-${label}-${index}`,
      "--consumer-id",
      "consumer-phase8-local",
    ],
    { cwd: ROOT, stdio: ["ignore", "ignore", "inherit"] }
  );
  const bundle = JSON.parse(fs.readFileSync(bundlePath, "utf8"));
  const poseidon = await buildPoseidon();
  const proofInput = buildProofInput(
    bundle.request,
    bundle.execution,
    poseidon,
    202607199000n + BigInt(index)
  );
  const proveStarted = nowMs();
  const { proof, publicSignals } = await snarkjs.groth16.fullProve(
    proofInput.input,
    WASM,
    ZKEY
  );
  const proveMs = nowMs() - proveStarted;
  const verificationKey = JSON.parse(fs.readFileSync(VKEY, "utf8"));
  const verifyStarted = nowMs();
  if (!(await snarkjs.groth16.verify(verificationKey, publicSignals, proof))) {
    throw new Error(`fresh ${label} proof did not verify`);
  }
  const verifyMs = nowMs() - verifyStarted;
  const calldata = JSON.parse(
    `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
  );
  return {
    index,
    bundle,
    proofInput,
    proof,
    publicSignals,
    a: calldata[0],
    b: calldata[1],
    c: calldata[2],
    signals: calldata[3],
    proveMs,
    verifyMs,
  };
}

async function setupFullRequest(system, prepared, metric, options = {}) {
  const [provider, consumer] = await ethers.getSigners();
  const context = preparedContext(prepared);
  const assetKey = options.assetKey || context.assetKey;
  const policyHash = options.policyHash || context.policyHash;
  const consumerId = options.consumerId ?? context.values.consumer_id;
  const functionId = options.functionId ?? context.values.function_id;
  const epsilonRequested =
    options.epsilonRequested ?? context.values.actual_privacy_cost_fixed;
  if (options.registerAsset !== false) {
    await transaction(
      metric,
      "access",
      system.registry.registerAssetV2(
        assetKey,
        hex(123n),
        context.dataHash,
        policyHash,
        context.values.policy_version
      )
    );
  }
  if (options.registerBudget !== false) {
    await transaction(
      metric,
      "budget",
      system.budget.registerBudget(
        assetKey,
        options.totalBudget ?? context.values.actual_privacy_cost_fixed * 10n
      )
    );
  }
  await transaction(
    metric,
    "access",
    system.access.connect(consumer).requestAccessV2(
      context.requestKey,
      assetKey,
      consumerId,
      hex(321n),
      policyHash,
      context.values.policy_version,
      functionId,
      epsilonRequested
    )
  );
  await transaction(metric, "access", system.access.approveRequest(context.requestKey));
  if (options.reserve !== false) {
    await transaction(
      metric,
      "budget",
      system.settlement.reserveBudgetForRequest(context.requestKey)
    );
  }
  const expected = {
    ...context.expected,
    attestationExpiresAtUnixMs:
      options.expiry ?? context.expected.attestationExpiresAtUnixMs,
  };
  await transaction(
    metric,
    "proof",
    system.adapter.registerExpectation(context.requestKey, expected)
  );
  return { provider, consumer, context: { ...context, assetKey, policyHash }, expected };
}

function newMetric() {
  return { latency_ms: 0, gas: 0n, stage_latency: {}, stage_gas: {} };
}

async function runFullAblation(prepared, substituteTee) {
  const system = await deploySystem();
  const metric = newMetric();
  const setup = await setupFullRequest(system, prepared, metric);
  const teeMs = substituteTee
    ? prepared.bundle.client_timings_us.reference_aggregate / 1000
    : prepared.bundle.client_timings_us.host_subprocess_wall / 1000 +
      prepared.bundle.client_timings_us.attestation_validation_wall / 1000;
  metric.latency_ms += teeMs + prepared.proveMs;
  metric.stage_latency.tee = teeMs;
  metric.stage_latency.proof = (metric.stage_latency.proof || 0) + prepared.proveMs;
  await transaction(
    metric,
    "settlement",
    system.settlement.connect(setup.consumer).settle(
      setup.context.requestKey,
      setup.context.evidence,
      prepared.a,
      prepared.b,
      prepared.c,
      prepared.signals
    )
  );
  return metric;
}

async function runAblations(referencePrepared) {
  const warmupItem = await createFreshPrepared("ablation_warmup", 0);
  await runFullAblation(warmupItem, false);
  const rows = [];
  const variants = [
    "baseline_minimal",
    "access_only",
    "no_budget",
    "no_zk",
    "no_tee",
    "full_trustcircuit",
  ];
  for (let run = 0; run < 5; run += 1) {
    for (let variantIndex = 0; variantIndex < variants.length; variantIndex += 1) {
      const variant = variants[variantIndex];
      const item = ["no_budget", "no_zk", "no_tee", "full_trustcircuit"].includes(variant)
        ? await createFreshPrepared(`ablation_${variant}`, run * 10 + variantIndex)
        : referencePrepared;
      const metric = newMetric();
      let measurementType = "measured";
      if (variant === "baseline_minimal") {
        metric.latency_ms = item.bundle.client_timings_us.reference_aggregate / 1000;
        metric.stage_latency.compute = metric.latency_ms;
      } else if (variant === "access_only") {
        const [provider, consumer] = await ethers.getSigners();
        const registry = await deployContract("DataRegistry");
        const access = await deployContract("AccessController");
        const audit = await deployContract("AuditLedger");
        const context = preparedContext(item);
        await transaction(metric, "access", registry.registerAssetV2(
          context.assetKey, hex(123n), context.dataHash, context.policyHash,
          context.values.policy_version
        ));
        await transaction(metric, "access", access.connect(consumer).requestAccessV2(
          context.requestKey, context.assetKey, context.values.consumer_id, hex(321n),
          context.policyHash, context.values.policy_version, context.values.function_id,
          context.values.actual_privacy_cost_fixed
        ));
        await transaction(metric, "access", access.connect(provider).approveRequest(context.requestKey));
        await transaction(metric, "access", access.completeRequest(context.requestKey));
        await transaction(metric, "audit", audit.recordAudit(
          context.requestKey, context.assetKey, 6, context.evidence.attestationDigest
        ));
      } else if (variant === "no_zk") {
        const [provider, consumer] = await ethers.getSigners();
        const registry = await deployContract("DataRegistry");
        const access = await deployContract("AccessController");
        const budget = await deployContract("BudgetLedger");
        const audit = await deployContract("AuditLedger");
        const context = preparedContext(item);
        await transaction(metric, "access", registry.registerAssetV2(
          context.assetKey, hex(123n), context.dataHash, context.policyHash,
          context.values.policy_version
        ));
        await transaction(metric, "budget", budget.registerBudget(
          context.assetKey, context.values.actual_privacy_cost_fixed * 10n
        ));
        await transaction(metric, "access", access.connect(consumer).requestAccessV2(
          context.requestKey, context.assetKey, context.values.consumer_id, hex(321n),
          context.policyHash, context.values.policy_version, context.values.function_id,
          context.values.actual_privacy_cost_fixed
        ));
        await transaction(metric, "access", access.connect(provider).approveRequest(context.requestKey));
        await transaction(metric, "budget", budget.reserveBudget(
          context.assetKey, context.requestKey, context.values.actual_privacy_cost_fixed
        ));
        const teeMs = item.bundle.client_timings_us.host_subprocess_wall / 1000 +
          item.bundle.client_timings_us.attestation_validation_wall / 1000;
        metric.latency_ms += teeMs;
        metric.stage_latency.tee = teeMs;
        await transaction(metric, "budget", budget.consumeBudget(
          context.assetKey, context.requestKey, context.values.actual_privacy_cost_fixed
        ));
        await transaction(metric, "access", access.completeRequest(context.requestKey));
        await transaction(metric, "audit", audit.recordAudit(
          context.requestKey, context.assetKey, 6, context.evidence.attestationDigest
        ));
      } else if (variant === "no_budget") {
        const system = await deploySystem();
        const setup = await setupFullRequest(system, item, metric, {
          registerBudget: false,
          reserve: false,
        });
        const teeMs = item.bundle.client_timings_us.host_subprocess_wall / 1000 +
          item.bundle.client_timings_us.attestation_validation_wall / 1000;
        metric.latency_ms += teeMs + item.proveMs;
        metric.stage_latency.tee = teeMs;
        metric.stage_latency.proof = (metric.stage_latency.proof || 0) + item.proveMs;
        await transaction(metric, "proof", system.adapter.submitCompliance(
          setup.context.requestKey, item.a, item.b, item.c, item.signals
        ));
        await transaction(metric, "access", system.access.completeRequest(setup.context.requestKey));
        await transaction(metric, "audit", system.audit.recordAudit(
          setup.context.requestKey, setup.context.assetKey, 6,
          setup.context.evidence.attestationDigest
        ));
      } else if (variant === "no_tee") {
        measurementType = "model_calibrated_from_measured_components";
        Object.assign(metric, await runFullAblation(item, true));
      } else {
        Object.assign(metric, await runFullAblation(item, false));
      }
      rows.push({
        measurement_type: measurementType,
        variant,
        run,
        total_latency_ms: metric.latency_ms,
        throughput_req_s: 1000 / Math.max(metric.latency_ms, 0.001),
        total_gas: metric.gas.toString(),
        access_latency_ms: metric.stage_latency.access || 0,
        budget_latency_ms: metric.stage_latency.budget || 0,
        tee_latency_ms: metric.stage_latency.tee || 0,
        proof_latency_ms: metric.stage_latency.proof || 0,
        settlement_latency_ms: metric.stage_latency.settlement || 0,
        audit_latency_ms: metric.stage_latency.audit || 0,
        access_gas: String(metric.stage_gas.access || 0n),
        budget_gas: String(metric.stage_gas.budget || 0n),
        proof_gas: String(metric.stage_gas.proof || 0n),
        settlement_gas: String(metric.stage_gas.settlement || 0n),
        audit_gas: String(metric.stage_gas.audit || 0n),
        success: 1,
      });
      process.stdout.write(`[phase8-chain] ablation ${variant} run=${run}\n`);
    }
  }
  writeCsv(path.join(RAW, "e2e_ablation.csv"), rows);
}

function errorReason(error) {
  return error?.revert?.name || error?.shortMessage || error?.message || "unknown";
}

async function runProtocolAttacks() {
  const rows = [];
  const cases = [
    { name: "wrong_request", category: "context", mutateCall: (item) => ({ requestKey: hex(item.proofInput.values.request_id + 1n) }) },
    { name: "wrong_asset", category: "context", setup: (item) => ({ assetKey: hex(item.proofInput.values.asset_id + 1n) }) },
    { name: "wrong_consumer_id", category: "context", setup: (item) => ({ consumerId: item.proofInput.values.consumer_id + 1n }) },
    { name: "wrong_consumer_address", category: "context", caller: "stranger" },
    { name: "wrong_policy", category: "context", setup: (item) => ({ policyHash: hex(item.proofInput.values.policy_hash + 1n) }) },
    { name: "wrong_function", category: "context", setup: { functionId: 1n } },
    { name: "wrong_result", category: "context", evidence: (item) => ({ resultHash: hex(item.proofInput.values.result_hash + 1n) }) },
    { name: "altered_transcript", category: "tampering", evidence: (item) => ({ transcriptHash: hex(item.proofInput.values.transcript_hash + 1n) }) },
    { name: "altered_attestation", category: "tampering", evidence: (item) => ({ attestationDigest: hex(item.proofInput.values.attestation_digest + 1n) }) },
    { name: "stale_attestation", category: "tampering", setup: { expiry: 1n } },
    { name: "tampered_proof", category: "tampering", tamperProof: true },
    { name: "nullifier_replay", category: "replay", replay: true },
  ];
  for (let caseIndex = 0; caseIndex < cases.length; caseIndex += 1) {
    const testCase = cases[caseIndex];
    const item = await createFreshPrepared("attack", caseIndex);
    const system = await deploySystem();
    const metric = newMetric();
    let setup;
    try {
      const setupOptions = typeof testCase.setup === "function"
        ? testCase.setup(item)
        : (testCase.setup || {});
      setup = await setupFullRequest(system, item, metric, setupOptions);
    } catch (error) {
      rows.push({
        measurement_type: "measured",
        category: testCase.category,
        attack_case: testCase.name,
        accepted: 0,
        rejected: 1,
        rejection_stage: "setup",
        reason: errorReason(error),
        latency_ms: metric.latency_ms,
        budget_invariant_violation: 0,
      });
      continue;
    }
    const [, consumer, stranger] = await ethers.getSigners();
    const callMutation = typeof testCase.mutateCall === "function"
      ? testCase.mutateCall(item)
      : (testCase.mutateCall || {});
    const evidenceMutation = typeof testCase.evidence === "function"
      ? testCase.evidence(item)
      : (testCase.evidence || {});
    const requestKey = callMutation.requestKey || setup.context.requestKey;
    const evidence = { ...setup.context.evidence, ...evidenceMutation };
    const a = testCase.tamperProof
      ? [(BigInt(item.a[0]) ^ 1n).toString(), item.a[1]]
      : item.a;
    let accepted = false;
    let reason = "";
    const started = nowMs();
    try {
      const tx = await system.settlement
        .connect(testCase.caller === "stranger" ? stranger : consumer)
        .settle(requestKey, evidence, a, item.b, item.c, item.signals);
      await tx.wait();
      if (testCase.replay) {
        const replayTx = await system.settlement
          .connect(consumer)
          .settle(requestKey, evidence, a, item.b, item.c, item.signals);
        await replayTx.wait();
      }
      accepted = true;
    } catch (error) {
      reason = errorReason(error);
    }
    const budgetState = await system.budget.getBudget(setup.context.assetKey);
    const invariantViolation =
      budgetState.reserved + budgetState.used > budgetState.total ? 1 : 0;
    rows.push({
      measurement_type: "measured",
      category: testCase.category,
      attack_case: testCase.name,
      accepted: accepted ? 1 : 0,
      rejected: accepted ? 0 : 1,
      rejection_stage: accepted ? "none" : "settlement",
      reason,
      latency_ms: nowMs() - started,
      budget_invariant_violation: invariantViolation,
    });
    process.stdout.write(`[phase8-chain] attack ${testCase.name} accepted=${accepted ? 1 : 0}\n`);
  }
  writeCsv(path.join(RAW, "protocol_attacks.csv"), rows);
}

async function runConcurrency() {
  const warmupBudget = await deployContract("BudgetLedger");
  const warmupAsset = ethers.id("phase8-concurrency-warmup");
  const warmupRequest = ethers.id("phase8-concurrency-warmup-request");
  await (await warmupBudget.registerBudget(warmupAsset, 1_000_000n)).wait();
  await (await warmupBudget.reserveBudget(warmupAsset, warmupRequest, 1_000_000n)).wait();
  await (await warmupBudget.consumeBudget(warmupAsset, warmupRequest, 1_000_000n)).wait();
  const rows = [];
  for (const concurrency of CONCURRENCY_LEVELS) {
    const budget = await deployContract("BudgetLedger");
    const [provider] = await ethers.getSigners();
    const cost = 1_000_000n;
    const capacity = concurrency === 1 ? 1 : Math.ceil(concurrency / 2);
    const assetKey = ethers.id(`phase8-concurrency-budget-${concurrency}`);
    await budget.registerBudget(assetKey, cost * BigInt(capacity));
    const requestKeys = Array.from({ length: concurrency }, (_, index) =>
      ethers.id(`phase8-concurrency-${concurrency}-${index}`)
    );
    const batchStarted = nowMs();
    const startingNonce = await provider.getNonce();
    await network.provider.send("evm_setAutomine", [false]);
    let submitted;
    try {
      submitted = await Promise.all(
        requestKeys.map((requestKey, index) =>
          budget.connect(provider).reserveBudget(assetKey, requestKey, cost, {
            nonce: startingNonce + index,
            gasLimit: 300_000,
          })
        )
      );
      await network.provider.send("evm_mine");
    } finally {
      await network.provider.send("evm_setAutomine", [true]);
    }
    const reservations = [];
    for (let index = 0; index < submitted.length; index += 1) {
      try {
        const receipt = await submitted[index].wait();
        reservations.push({ accepted: 1, gas: receipt.gasUsed, requestKey: requestKeys[index], error: "" });
      } catch (error) {
        reservations.push({ accepted: 0, gas: 0n, requestKey: requestKeys[index], error: errorReason(error) });
      }
    }
    const acceptedReservations = reservations.filter((outcome) => outcome.accepted);
    const consumptions = [];
    for (const outcome of acceptedReservations) {
      const tx = await budget.connect(provider).consumeBudget(assetKey, outcome.requestKey, cost);
      const receipt = await tx.wait();
      consumptions.push(receipt.gasUsed);
    }
    const batchLatency = nowMs() - batchStarted;
    const accepted = acceptedReservations.length;
    const reverted = concurrency - accepted;
    const budgetState = await budget.getBudget(assetKey);
    const invariantViolations =
      budgetState.reserved + budgetState.used > budgetState.total ||
      budgetState.budgetRemaining !== budgetState.total - budgetState.reserved - budgetState.used
        ? 1
        : 0;
    rows.push({
      measurement_type: "measured_local_hardhat",
      concurrency,
      capacity,
      accepted,
      reverted,
      settlement_batch_latency_ms: batchLatency,
      settlement_mean_latency_ms: batchLatency / Math.max(accepted, 1),
      throughput_req_s: accepted * 1000 / Math.max(batchLatency, 0.001),
      total_gas: (
        reservations.reduce((sum, outcome) => sum + outcome.gas, 0n) +
        consumptions.reduce((sum, gas) => sum + gas, 0n)
      ).toString(),
      budget_total_fixed: budgetState.total.toString(),
      budget_used_fixed: budgetState.used.toString(),
      budget_reserved_fixed: budgetState.reserved.toString(),
      budget_remaining_fixed: budgetState.budgetRemaining.toString(),
      budget_invariant_violations: invariantViolations,
    });
    process.stdout.write(`[phase8-chain] concurrency=${concurrency} accepted=${accepted} reverted=${reverted}\n`);
  }
  writeCsv(path.join(RAW, "settlement_concurrency.csv"), rows);
}

function parseSimpleCsv(filePath) {
  const lines = fs.readFileSync(filePath, "utf8").trim().split(/\r?\n/);
  const headers = lines.shift().split(",");
  return lines.map((line) => Object.fromEntries(
    line.split(",").map((value, index) => [headers[index], value])
  ));
}

async function runBudgetExhaustion() {
  const dpRows = parseSimpleCsv(path.join(RAW, "dp_vbs.csv"));
  const costs = new Map();
  for (const row of dpRows) {
    if (row.is_warmup === "0") {
      const epsilon = row.epsilon_requested;
      const cost = BigInt(row.actual_privacy_cost_fixed);
      costs.set(epsilon, costs.has(epsilon) ? (costs.get(epsilon) > cost ? costs.get(epsilon) : cost) : cost);
    }
  }
  const rows = [];
  for (const [epsilon, cost] of costs.entries()) {
    const budget = await deployContract("BudgetLedger");
    const assetKey = ethers.id(`phase8-budget-${epsilon}`);
    const total = 5_000_000n;
    await budget.registerBudget(assetKey, total);
    for (let requestIndex = 1; requestIndex <= 32; requestIndex += 1) {
      const requestKey = ethers.id(`phase8-budget-${epsilon}-${requestIndex}`);
      let accepted = 0;
      let reason = "";
      const started = nowMs();
      try {
        await (await budget.reserveBudget(assetKey, requestKey, cost)).wait();
        await (await budget.consumeBudget(assetKey, requestKey, cost)).wait();
        accepted = 1;
      } catch (error) {
        reason = errorReason(error);
      }
      const state = await budget.getBudget(assetKey);
      rows.push({
        measurement_type: "measured_local_hardhat",
        epsilon_requested: epsilon,
        privacy_cost_fixed: cost.toString(),
        request_index: requestIndex,
        accepted,
        reverted: accepted ? 0 : 1,
        reason,
        latency_ms: nowMs() - started,
        budget_total_fixed: state.total.toString(),
        budget_used_fixed: state.used.toString(),
        budget_reserved_fixed: state.reserved.toString(),
        budget_remaining_fixed: state.budgetRemaining.toString(),
        budget_invariant_violations:
          state.used + state.reserved > state.total ? 1 : 0,
      });
    }
  }
  writeCsv(path.join(RAW, "budget_exhaustion.csv"), rows);
}

async function main() {
  for (const required of [BUNDLES, WASM, ZKEY, VKEY]) {
    if (!fs.existsSync(required)) throw new Error(`missing required artifact: ${required}`);
  }
  const started = nowMs();
  const prepared = await prepareProofs();
  await runConcurrency();
  await runProtocolAttacks();
  await runAblations(prepared[0]);
  await runBudgetExhaustion();
  const config = {
    schema: "TrustCircuit.Phase8ChainExperimentConfig.v1",
    measurement_type: "measured_local_hardhat",
    timestamp: new Date().toISOString(),
    git_commit: gitValue(["rev-parse", "HEAD"]),
    git_dirty: gitValue(["status", "--porcelain"]).length > 0,
    seed: EXPERIMENT_SEED,
    warmups: {
      groth16_proof: 1,
      full_ablation: 1,
      budget_concurrency: 1,
    },
    concurrency_levels: CONCURRENCY_LEVELS,
    ablation_runs: Math.min(5, prepared.length),
    proof_runs: prepared.length,
    node: process.version,
    platform: `${os.platform()} ${os.release()}`,
    cpu: os.cpus()[0]?.model || "unknown",
    logical_cpus: os.cpus().length,
    duration_seconds: (nowMs() - started) / 1000,
    public_testnet: {
      executed: false,
      reason: "hardhat.config.js defines only the local hardhat network; no repository testnet RPC/account configuration exists",
    },
  };
  fs.writeFileSync(path.join(RAW, "chain_experiment_config.json"), `${JSON.stringify(config, null, 2)}\n`);
  fs.mkdirSync(path.join(RAW, "testnet"), { recursive: true });
  fs.writeFileSync(
    path.join(RAW, "testnet", "public_testnet_status.json"),
    `${JSON.stringify({
      measurement_type: "not_executed",
      executed: false,
      reason: config.public_testnet.reason,
      fallback: "local Hardhat chain used for all settlement measurements",
    }, null, 2)}\n`
  );
  console.log(JSON.stringify({ ok: true, raw: RAW, duration_seconds: config.duration_seconds }));
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    console.error(error.stack || error.message);
    process.exit(1);
  });
