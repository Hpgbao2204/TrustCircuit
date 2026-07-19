/*
 * Phase 8 local-chain experiments over real Phase 6 VBS evidence and the real
 * Phase 7 Groth16 verifier. Outputs machine-readable CSV/JSON only; plotting is
 * performed later from these files.
 */
"use strict";

const fs = require("fs");
const crypto = require("crypto");
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
const {
  ProcessResourceSampler,
  monotonicMs,
} = require("./process_metrics");

const ROOT = path.resolve(__dirname, "..");
const RAW = path.join(ROOT, "results", "raw", "phase8");
const BUNDLES = path.join(RAW, "concurrency_bundles");
const WASM = path.join(ROOT, "zk", "build", "phase7_js", "phase7.wasm");
const ZKEY = path.join(ROOT, "zk", "build", "phase7_final.zkey");
const VKEY = path.join(ROOT, "zk", "build", "phase7_vkey.json");
const CONCURRENCY_LEVELS = [1, 2, 4, 8, 16, 32];
const EXPERIMENT_SEED = 20260719;
const WARMUP_REPS = 1;
const ABLATION_REPS = 30;
const ATTACK_LATENCY_REPS = 30;
const CONCURRENCY_REPS = 30;
const COMPARISON_REPS = 30;

const CONFIG_IDENTITY = {
  schema: "TrustCircuit.Phase8ChainExperimentConfig.v2",
  seed: EXPERIMENT_SEED,
  warmups: WARMUP_REPS,
  ablation_repetitions: ABLATION_REPS,
  attack_repetitions: ATTACK_LATENCY_REPS,
  concurrency_repetitions: CONCURRENCY_REPS,
  comparison_repetitions: COMPARISON_REPS,
  concurrency_levels: CONCURRENCY_LEVELS,
};
const CONFIG_HASH = crypto
  .createHash("sha256")
  .update(JSON.stringify(CONFIG_IDENTITY))
  .digest("hex");

function gitValue(args) {
  return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
}

function nowMs() {
  return monotonicMs();
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
    const proofSampler = new ProcessResourceSampler().start();
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
    const proofResources = proofSampler.stop();
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
      timestamp_utc: new Date().toISOString(),
      config_hash: CONFIG_HASH,
      index,
      request_id: bundle.request.request_id,
      prove_time_ms: proveMs,
      verify_time_ms: verifyMs,
      proof_bundle_bytes: Buffer.byteLength(JSON.stringify({ proof, publicSignals })),
      process_cpu_time_ms: proofResources.process_cpu_time_ms,
      normalized_peak_cpu_percent: proofResources.normalized_peak_cpu_percent,
      peak_working_set_bytes: proofResources.peak_working_set_bytes,
      peak_private_bytes: proofResources.peak_private_bytes ?? "",
      resource_sample_count: proofResources.resource_sample_count,
      failure_status: "",
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
  return {
    latency_ms: 0,
    gas: 0n,
    stage_latency: {},
    stage_gas: {},
    process_resources: null,
  };
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
  for (let iteration = 0; iteration < WARMUP_REPS + ABLATION_REPS; iteration += 1) {
    const isWarmup = iteration < WARMUP_REPS;
    const run = isWarmup ? iteration : iteration - WARMUP_REPS;
    for (let variantIndex = 0; variantIndex < variants.length; variantIndex += 1) {
      const variant = variants[variantIndex];
      const item = ["no_budget", "no_zk", "no_tee", "full_trustcircuit"].includes(variant)
        ? await createFreshPrepared(`ablation_${variant}`, iteration * 10 + variantIndex)
        : referencePrepared;
      const metric = newMetric();
      let measurementType = "measured";
      const resourceSampler = new ProcessResourceSampler().start();
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
      metric.process_resources = resourceSampler.stop();
      rows.push({
        measurement_type: measurementType,
        timestamp_utc: new Date().toISOString(),
        config_hash: CONFIG_HASH,
        variant,
        run,
        is_warmup: isWarmup ? 1 : 0,
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
        process_cpu_time_ms: metric.process_resources.process_cpu_time_ms,
        normalized_peak_cpu_percent:
          metric.process_resources.normalized_peak_cpu_percent,
        peak_working_set_bytes: metric.process_resources.peak_working_set_bytes,
        peak_private_bytes: metric.process_resources.peak_private_bytes ?? "",
        resource_sample_count: metric.process_resources.resource_sample_count,
        failure_status: "",
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
    for (let run = 0; run < ATTACK_LATENCY_REPS; run += 1) {
      // Each isolated trial deploys a fresh system. Resetting also prevents the
      // one-second-per-block Hardhat clock from accumulating hundreds of
      // synthetic seconds across 30 setup-heavy trials. Evidence expiry is
      // still checked against the current wall-clock epoch in every trial.
      await network.provider.send("hardhat_reset");
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
          timestamp_utc: new Date().toISOString(),
          config_hash: CONFIG_HASH,
          category: testCase.category,
          attack_case: testCase.name,
          run,
          is_warmup: 0,
          accepted: 0,
          rejected: 1,
          rejection_stage: "setup",
          reason: errorReason(error),
          latency_ms: metric.latency_ms,
          process_cpu_time_ms: "",
          normalized_peak_cpu_percent: "",
          peak_working_set_bytes: "",
          peak_private_bytes: "",
          resource_sample_count: 0,
          failure_status: errorReason(error),
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
      if (testCase.replay) {
        const primeTx = await system.settlement
          .connect(consumer)
          .settle(requestKey, evidence, a, item.b, item.c, item.signals);
        await primeTx.wait();
      }
      const resourceSampler = new ProcessResourceSampler().start();
      const started = nowMs();
      try {
        const tx = await system.settlement
          .connect(testCase.caller === "stranger" ? stranger : consumer)
          .settle(requestKey, evidence, a, item.b, item.c, item.signals);
        await tx.wait();
        accepted = true;
      } catch (error) {
        reason = errorReason(error);
      }
      const processResources = resourceSampler.stop();
      const budgetState = await system.budget.getBudget(setup.context.assetKey);
      const invariantViolation =
        budgetState.reserved + budgetState.used > budgetState.total ? 1 : 0;
      rows.push({
        measurement_type: "measured",
        timestamp_utc: new Date().toISOString(),
        config_hash: CONFIG_HASH,
        category: testCase.category,
        attack_case: testCase.name,
        run,
        is_warmup: 0,
        accepted: accepted ? 1 : 0,
        rejected: accepted ? 0 : 1,
        rejection_stage: accepted ? "none" : "settlement",
        reason,
        latency_ms: nowMs() - started,
        process_cpu_time_ms: processResources.process_cpu_time_ms,
        normalized_peak_cpu_percent:
          processResources.normalized_peak_cpu_percent,
        peak_working_set_bytes: processResources.peak_working_set_bytes,
        peak_private_bytes: processResources.peak_private_bytes ?? "",
        resource_sample_count: processResources.resource_sample_count,
        failure_status: accepted ? "" : reason,
        budget_invariant_violation: invariantViolation,
      });
    }
    process.stdout.write(`[phase8-chain] attack ${testCase.name} reps=${ATTACK_LATENCY_REPS}\n`);
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
    for (let run = 0; run < CONCURRENCY_REPS; run += 1) {
      const budget = await deployContract("BudgetLedger");
      const [provider] = await ethers.getSigners();
      const cost = 1_000_000n;
      const capacity = concurrency === 1 ? 1 : Math.ceil(concurrency / 2);
      const assetKey = ethers.id(`phase8-concurrency-budget-${concurrency}-${run}`);
      await budget.registerBudget(assetKey, cost * BigInt(capacity));
      const requestKeys = Array.from({ length: concurrency }, (_, index) =>
        ethers.id(`phase8-concurrency-${concurrency}-${run}-${index}`)
      );
    const resourceSampler = new ProcessResourceSampler().start();
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
      const processResources = resourceSampler.stop();
      rows.push({
        measurement_type: "measured_local_hardhat",
        timestamp_utc: new Date().toISOString(),
        config_hash: CONFIG_HASH,
        concurrency,
        run,
        is_warmup: 0,
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
        process_cpu_time_ms: processResources.process_cpu_time_ms,
        normalized_peak_cpu_percent:
          processResources.normalized_peak_cpu_percent,
        peak_working_set_bytes: processResources.peak_working_set_bytes,
        peak_private_bytes: processResources.peak_private_bytes ?? "",
        resource_sample_count: processResources.resource_sample_count,
        failure_status: "",
      });
    }
    process.stdout.write(`[phase8-chain] concurrency=${concurrency} reps=${CONCURRENCY_REPS}\n`);
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
      const resourceSampler = new ProcessResourceSampler().start();
      const started = nowMs();
      try {
        await (await budget.reserveBudget(assetKey, requestKey, cost)).wait();
        await (await budget.consumeBudget(assetKey, requestKey, cost)).wait();
        accepted = 1;
      } catch (error) {
        reason = errorReason(error);
      }
      const state = await budget.getBudget(assetKey);
      const processResources = resourceSampler.stop();
      rows.push({
        measurement_type: "measured_local_hardhat",
        timestamp_utc: new Date().toISOString(),
        config_hash: CONFIG_HASH,
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
        process_cpu_time_ms: processResources.process_cpu_time_ms,
        normalized_peak_cpu_percent:
          processResources.normalized_peak_cpu_percent,
        peak_working_set_bytes: processResources.peak_working_set_bytes,
        peak_private_bytes: processResources.peak_private_bytes ?? "",
        resource_sample_count: processResources.resource_sample_count,
        failure_status: accepted ? "" : reason,
      });
    }
  }
  writeCsv(path.join(RAW, "budget_exhaustion.csv"), rows);
}

const COMPARISON_CONFIGURATIONS = [
  "TEE-only",
  "Access Ledger",
  "ZK Release",
  "Local DP Ledger",
  "TrustCircuit",
];

const COMPARISON_CAPABILITIES = {
  "Access Ledger": {
    access_authorization: 1,
    encrypted_confidential_execution: 0,
    native_attestation_validation: 0,
    differential_privacy_release: 0,
    cumulative_privacy_budget: 0,
    zero_knowledge_binding: 0,
    replay_protection: 0,
    atomic_audit_settlement: 0,
  },
  "TEE-only": {
    access_authorization: 0,
    encrypted_confidential_execution: 1,
    native_attestation_validation: 1,
    differential_privacy_release: 1,
    cumulative_privacy_budget: 0,
    zero_knowledge_binding: 0,
    replay_protection: 0,
    atomic_audit_settlement: 0,
  },
  "ZK Release": {
    access_authorization: 0,
    encrypted_confidential_execution: 0,
    native_attestation_validation: 0,
    differential_privacy_release: 0,
    cumulative_privacy_budget: 0,
    zero_knowledge_binding: 1,
    replay_protection: 1,
    atomic_audit_settlement: 0,
  },
  "Local DP Ledger": {
    access_authorization: 0,
    encrypted_confidential_execution: 0,
    native_attestation_validation: 0,
    differential_privacy_release: 1,
    cumulative_privacy_budget: 1,
    zero_knowledge_binding: 0,
    replay_protection: 0,
    atomic_audit_settlement: 0,
  },
  TrustCircuit: {
    access_authorization: 1,
    encrypted_confidential_execution: 1,
    native_attestation_validation: 1,
    differential_privacy_release: 1,
    cumulative_privacy_budget: 1,
    zero_knowledge_binding: 1,
    replay_protection: 1,
    atomic_audit_settlement: 1,
  },
};

function securityCoverage(configuration) {
  const capabilities = COMPARISON_CAPABILITIES[configuration];
  return Object.values(capabilities).reduce((sum, value) => sum + value, 0);
}

function comparisonBundlePath(variant, iteration) {
  return path.join(
    RAW,
    "comparison_bundles",
    `${variant}_${String(iteration).padStart(2, "0")}.json`
  );
}

function createComparisonProcessorSample(variant, iteration) {
  const output = comparisonBundlePath(variant, iteration);
  fs.mkdirSync(path.dirname(output), { recursive: true });
  execFileSync(
    "python",
    [
      path.join(ROOT, "scripts", "prepare_phase8_comparison_sample.py"),
      "--variant",
      variant,
      "--output",
      output,
      "--configuration",
      "Debug",
      "--rows",
      "1000",
      "--run",
      String(iteration),
      "--seed",
      String(EXPERIMENT_SEED),
      "--epsilon",
      "0.5",
      "--delta",
      "0.00001",
    ],
    { cwd: ROOT, stdio: ["ignore", "ignore", "inherit"] }
  );
  return JSON.parse(fs.readFileSync(output, "utf8"));
}

async function proveComparisonBundle(bundle, secret) {
  const poseidon = await buildPoseidon();
  const proofInput = buildProofInput(
    bundle.request,
    bundle.execution,
    poseidon,
    secret
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
  const verified = await snarkjs.groth16.verify(
    verificationKey,
    publicSignals,
    proof
  );
  const verifyMs = nowMs() - verifyStarted;
  if (!verified) throw new Error("comparison proof did not verify");
  const calldata = JSON.parse(
    `[${await snarkjs.groth16.exportSolidityCallData(proof, publicSignals)}]`
  );
  return {
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

function processorResources(bundle) {
  const reference = bundle.reference || {};
  return {
    process_cpu_time_ms: Number(reference.host_process_cpu_time_ms || 0),
    normalized_peak_cpu_percent: Number(
      reference.host_normalized_peak_cpu_percent || 0
    ),
    peak_working_set_bytes: Number(reference.host_peak_rss_bytes || 0),
    peak_private_bytes: Number(reference.host_peak_private_bytes || 0),
  };
}

function maxResource(parent, child, field) {
  const values = [parent?.[field], child?.[field]]
    .map(Number)
    .filter(Number.isFinite);
  return values.length ? Math.max(...values) : "";
}

async function runComparisons() {
  const rows = [];
  for (let iteration = 0; iteration < WARMUP_REPS + COMPARISON_REPS; iteration += 1) {
    const isWarmup = iteration < WARMUP_REPS;
    const run = isWarmup ? iteration : iteration - WARMUP_REPS;
    let sharedPrepared = null;
    for (let configurationIndex = 0; configurationIndex < COMPARISON_CONFIGURATIONS.length; configurationIndex += 1) {
      const configuration = COMPARISON_CONFIGURATIONS[configurationIndex];
      await network.provider.send("hardhat_reset");
      const metric = newMetric();
      let processorBundle = null;
      let directLatencyMs = 0;
      let proofOverheadMs = 0;
      let attestationOverheadMs = 0;
      let budgetOverheadMs = 0;
      let failureStatus = "";

      let accessSystem = null;
      let proofSystem = null;
      let fullSystem = null;
      if (configuration === "Access Ledger") {
        accessSystem = {
          registry: await deployContract("DataRegistry"),
          access: await deployContract("AccessController"),
          audit: await deployContract("AuditLedger"),
        };
      } else if (configuration === "ZK Release") {
        const native = await deployContract("Phase7Groth16Verifier");
        proofSystem = {
          adapter: await deployContract("ComplianceVerifier", await native.getAddress()),
        };
      } else if (configuration === "TrustCircuit") {
        fullSystem = await deploySystem();
      }

      const resourceSampler = new ProcessResourceSampler().start();
      const directStarted = nowMs();
      try {
        if (configuration === "Access Ledger") {
          const [, consumer] = await ethers.getSigners();
          if (!sharedPrepared) throw new Error("TEE-only shared comparison sample was not prepared");
          const context = preparedContext(sharedPrepared);
          await transaction(metric, "access", accessSystem.registry.registerAssetV2(
            context.assetKey,
            hex(123n),
            context.dataHash,
            context.policyHash,
            context.values.policy_version
          ));
          await transaction(metric, "access", accessSystem.access.connect(consumer).requestAccessV2(
            context.requestKey,
            context.assetKey,
            context.values.consumer_id,
            hex(321n),
            context.policyHash,
            context.values.policy_version,
            context.values.function_id,
            context.values.actual_privacy_cost_fixed
          ));
          await transaction(metric, "access", accessSystem.access.approveRequest(context.requestKey));
          await transaction(metric, "access", accessSystem.access.completeRequest(context.requestKey));
          await transaction(metric, "audit", accessSystem.audit.recordAudit(
            context.requestKey,
            context.assetKey,
            6,
            context.evidence.attestationDigest
          ));
        } else if (configuration === "TEE-only") {
          processorBundle = createComparisonProcessorSample("tee_only", iteration);
          const poseidon = await buildPoseidon();
          sharedPrepared = {
            bundle: processorBundle,
            proofInput: buildProofInput(
              processorBundle.request,
              processorBundle.execution,
              poseidon,
              202607196000n + BigInt(iteration)
            ),
          };
          attestationOverheadMs = (
            Number(processorBundle.execution.timings_us.attestation || 0) +
            Number(processorBundle.client_timings_us.attestation_validation_wall || 0)
          ) / 1000;
        } else if (configuration === "Local DP Ledger") {
          processorBundle = createComparisonProcessorSample(
            "local_dp_ledger",
            iteration
          );
          budgetOverheadMs = Number(
            processorBundle.local_budget.accounting_latency_us || 0
          ) / 1000;
        } else if (configuration === "ZK Release") {
          if (!sharedPrepared) throw new Error("TEE-only shared comparison sample was not prepared");
          const item = await proveComparisonBundle(
            sharedPrepared.bundle,
            202607198000n + BigInt(iteration)
          );
          const context = preparedContext(item);
          const expected = {
            ...context.expected,
            attestationExpiresAtUnixMs: BigInt(Date.now() + 300_000),
          };
          await transaction(metric, "proof", proofSystem.adapter.registerExpectation(
            context.requestKey,
            expected
          ));
          await transaction(metric, "proof", proofSystem.adapter.submitCompliance(
            context.requestKey,
            item.a,
            item.b,
            item.c,
            item.signals
          ));
          proofOverheadMs = item.proveMs + item.verifyMs +
            Number(metric.stage_latency.proof || 0);
        } else {
          processorBundle = createComparisonProcessorSample("trustcircuit", iteration);
          const item = await proveComparisonBundle(
            processorBundle,
            202607197000n + BigInt(iteration)
          );
          const setup = await setupFullRequest(fullSystem, item, metric);
          await transaction(
            metric,
            "settlement",
            fullSystem.settlement.connect(setup.consumer).settle(
              setup.context.requestKey,
              setup.context.evidence,
              item.a,
              item.b,
              item.c,
              item.signals
            )
          );
          proofOverheadMs = item.proveMs + item.verifyMs +
            Number(metric.stage_latency.proof || 0);
          attestationOverheadMs = (
            Number(processorBundle.execution.timings_us.attestation || 0) +
            Number(processorBundle.client_timings_us.attestation_validation_wall || 0)
          ) / 1000;
          budgetOverheadMs = Number(metric.stage_latency.budget || 0);
        }
      } catch (error) {
        failureStatus = errorReason(error);
      }
      directLatencyMs = nowMs() - directStarted;
      const parentResources = resourceSampler.stop();
      const childResources = processorBundle
        ? processorResources(processorBundle)
        : null;
      const capabilities = COMPARISON_CAPABILITIES[configuration];
      const otherLifecycleMs = Math.max(
        directLatencyMs - proofOverheadMs - attestationOverheadMs - budgetOverheadMs,
        0
      );
      rows.push({
        measurement_type: "locally_measured",
        timestamp_utc: new Date().toISOString(),
        config_hash: CONFIG_HASH,
        configuration,
        run,
        is_warmup: isWarmup ? 1 : 0,
        rows: 1000,
        function_id: 2,
        epsilon_requested: 0.5,
        delta_requested: 0.00001,
        total_latency_ms: directLatencyMs,
        throughput_req_s: 1000 / Math.max(directLatencyMs, 0.001),
        total_gas: metric.gas.toString(),
        proof_overhead_ms: proofOverheadMs,
        attestation_overhead_ms: attestationOverheadMs,
        budget_overhead_ms: budgetOverheadMs,
        other_lifecycle_ms: otherLifecycleMs,
        process_startup_ms: processorBundle
          ? Number(processorBundle.client_timings_us.host_subprocess_wall || 0) / 1000 -
            Number(processorBundle.execution.timings_us.host_total || 0) / 1000
          : 0,
        process_cpu_time_ms:
          Number(parentResources.process_cpu_time_ms || 0) +
          Number(childResources?.process_cpu_time_ms || 0),
        normalized_peak_cpu_percent: maxResource(
          parentResources,
          childResources,
          "normalized_peak_cpu_percent"
        ),
        peak_working_set_bytes: maxResource(
          parentResources,
          childResources,
          "peak_working_set_bytes"
        ),
        peak_private_bytes: maxResource(
          parentResources,
          childResources,
          "peak_private_bytes"
        ),
        security_coverage_score: securityCoverage(configuration),
        security_coverage_total: Object.keys(capabilities).length,
        success: failureStatus ? 0 : 1,
        failure_status: failureStatus,
      });
      process.stdout.write(
        `[phase8-chain] comparison ${configuration} iteration=${iteration}\n`
      );
    }
  }
  writeCsv(path.join(RAW, "comparison_performance.csv"), rows);
  writeCsv(
    path.join(RAW, "comparison_capabilities.csv"),
    COMPARISON_CONFIGURATIONS.map((configuration) => ({
      measurement_type: "functional_definition",
      configuration,
      ...COMPARISON_CAPABILITIES[configuration],
      security_coverage_score: securityCoverage(configuration),
    }))
  );
}

async function main() {
  const comparisonOnly =
    process.argv.includes("--comparison-only") ||
    process.env.TRUSTCIRCUIT_COMPARISON_ONLY === "1";
  for (const required of [BUNDLES, WASM, ZKEY, VKEY]) {
    if (!fs.existsSync(required)) throw new Error(`missing required artifact: ${required}`);
  }
  const started = nowMs();
  let prepared = [];
  if (!comparisonOnly) {
    prepared = await prepareProofs();
  }
  await runComparisons();
  if (!comparisonOnly) {
    await runConcurrency();
    await runProtocolAttacks();
    await runAblations(prepared[0]);
    await runBudgetExhaustion();
  }
  const config = {
    schema: "TrustCircuit.Phase8ChainExperimentConfig.v2",
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
    concurrency_repetitions: CONCURRENCY_REPS,
    attack_latency_repetitions: ATTACK_LATENCY_REPS,
    config_hash: CONFIG_HASH,
    ablation_runs: ABLATION_REPS,
    comparison_runs: COMPARISON_REPS,
    comparison_only: comparisonOnly,
    proof_runs: prepared.length,
    node: process.version,
    platform: `${os.platform()} ${os.release()}`,
    cpu: os.cpus()[0]?.model || "unknown",
    logical_cpus: os.cpus().length,
    resource_counters: {
      process_cpu_time_ms: "Node.js process user+system CPU-time delta",
      normalized_peak_cpu_percent: "5 ms sampled CPU-time delta normalized by logical CPU count; blocking operations use the normalized run average as a lower-resolution fallback",
      peak_working_set_bytes: "Windows PeakWorkingSet64 for the benchmark process",
      peak_private_bytes: "maximum observed Windows PrivateMemorySize64 endpoint for the benchmark process",
      scope: "benchmark/host process; never enclave-only memory",
    },
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
