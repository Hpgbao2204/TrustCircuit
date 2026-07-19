"use strict";

const os = require("os");
const { execFileSync } = require("child_process");


function monotonicMs() {
  return Number(process.hrtime.bigint()) / 1e6;
}

function windowsMemorySnapshot() {
  if (process.platform !== "win32") {
    return {
      working_set_bytes: process.memoryUsage().rss,
      peak_working_set_bytes: process.memoryUsage().rss,
      private_bytes: null,
    };
  }
  try {
    const script = [
      `$p=Get-Process -Id ${process.pid}`,
      "[Console]::Out.Write(($p.WorkingSet64.ToString() + ',' + $p.PeakWorkingSet64.ToString() + ',' + $p.PrivateMemorySize64.ToString()))",
    ].join("; ");
    const values = execFileSync(
      "powershell.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      { encoding: "utf8", windowsHide: true }
    ).trim().split(",").map(Number);
    if (values.length === 3 && values.every(Number.isFinite)) {
      return {
        working_set_bytes: values[0],
        peak_working_set_bytes: values[1],
        private_bytes: values[2],
      };
    }
  } catch (_) {
    // A missing counter is represented as null; it is never replaced by zero.
  }
  return {
    working_set_bytes: process.memoryUsage().rss,
    peak_working_set_bytes: process.memoryUsage().rss,
    private_bytes: null,
  };
}

class ProcessResourceSampler {
  constructor(intervalMs = 5) {
    this.intervalMs = intervalMs;
    this.logicalCpus = Math.max(os.cpus().length, 1);
    this.startedMs = 0;
    this.startedCpu = null;
    this.previousCpu = null;
    this.previousMs = 0;
    this.timer = null;
    this.peakNormalizedCpuPercent = 0;
    this.peakWorkingSetBytes = 0;
    this.peakPrivateBytes = null;
    this.samples = 0;
  }

  sample() {
    const sampledMs = monotonicMs();
    const cpu = process.cpuUsage();
    const memory = process.memoryUsage();
    this.peakWorkingSetBytes = Math.max(this.peakWorkingSetBytes, memory.rss);
    if (this.previousCpu !== null) {
      const cpuDeltaUs =
        cpu.user - this.previousCpu.user + cpu.system - this.previousCpu.system;
      const wallDeltaMs = sampledMs - this.previousMs;
      if (wallDeltaMs > 0) {
        const normalized = cpuDeltaUs / 1000 / wallDeltaMs / this.logicalCpus * 100;
        this.peakNormalizedCpuPercent = Math.max(
          this.peakNormalizedCpuPercent,
          Math.min(Math.max(normalized, 0), 100)
        );
      }
    }
    this.previousCpu = cpu;
    this.previousMs = sampledMs;
    this.samples += 1;
  }

  start() {
    this.startedMs = monotonicMs();
    this.startedCpu = process.cpuUsage();
    this.previousCpu = this.startedCpu;
    this.previousMs = this.startedMs;
    const memory = windowsMemorySnapshot();
    this.peakWorkingSetBytes = Math.max(
      this.peakWorkingSetBytes,
      memory.peak_working_set_bytes
    );
    this.peakPrivateBytes = memory.private_bytes;
    this.timer = setInterval(() => this.sample(), this.intervalMs);
    this.timer.unref();
    return this;
  }

  stop() {
    if (this.timer !== null) clearInterval(this.timer);
    this.sample();
    const stoppedMs = monotonicMs();
    const cpuDelta = process.cpuUsage(this.startedCpu);
    const cpuTimeMs = (cpuDelta.user + cpuDelta.system) / 1000;
    const wallMs = stoppedMs - this.startedMs;
    const averageNormalized = wallMs > 0
      ? cpuTimeMs / wallMs / this.logicalCpus * 100
      : 0;
    const memory = windowsMemorySnapshot();
    this.peakWorkingSetBytes = Math.max(
      this.peakWorkingSetBytes,
      memory.peak_working_set_bytes,
      memory.working_set_bytes
    );
    if (memory.private_bytes !== null) {
      this.peakPrivateBytes = Math.max(
        this.peakPrivateBytes === null ? 0 : this.peakPrivateBytes,
        memory.private_bytes
      );
    }
    return {
      process_cpu_time_ms: cpuTimeMs,
      normalized_peak_cpu_percent: Math.max(
        this.peakNormalizedCpuPercent,
        Math.min(Math.max(averageNormalized, 0), 100)
      ),
      peak_working_set_bytes: this.peakWorkingSetBytes,
      peak_private_bytes: this.peakPrivateBytes,
      resource_sample_count: this.samples,
      resource_scope: "Node.js benchmark process; not enclave-only memory",
    };
  }
}

async function measureProcessResources(operation, intervalMs = 5) {
  const sampler = new ProcessResourceSampler(intervalMs).start();
  try {
    const value = await operation();
    return { value, resources: sampler.stop() };
  } catch (error) {
    error.processResources = sampler.stop();
    throw error;
  }
}

module.exports = {
  ProcessResourceSampler,
  measureProcessResources,
  monotonicMs,
  windowsMemorySnapshot,
};

