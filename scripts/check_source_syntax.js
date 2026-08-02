"use strict";

const fs = require("fs");
const { spawnSync } = require("child_process");

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: process.cwd(),
    encoding: "utf8",
    shell: false,
  });

  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    process.stderr.write(result.stdout || "");
    process.stderr.write(result.stderr || "");
    process.exit(result.status || 1);
  }

  return result.stdout;
}

const tracked = run("git", ["ls-files", "-z", "--"])
  .split("\0")
  .filter(Boolean);
const javascriptFiles = tracked.filter((file) => /\.(?:cjs|js|mjs)$/.test(file));
const pythonFiles = tracked.filter((file) => file.endsWith(".py"));
const jsonFiles = tracked.filter((file) => file.endsWith(".json"));

for (const file of javascriptFiles) {
  run(process.execPath, ["--check", file]);
}

if (pythonFiles.length > 0) {
  const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
  const checkPython = [
    "import pathlib, sys",
    "for name in sys.argv[1:]:",
    "    source = pathlib.Path(name).read_text(encoding='utf-8-sig')",
    "    compile(source, name, 'exec')",
  ].join("\n");
  run(python, ["-c", checkPython, ...pythonFiles]);
}

for (const file of jsonFiles) {
  JSON.parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/, ""));
}

console.log(
  `[source-check] OK: ${javascriptFiles.length} JavaScript, ` +
    `${pythonFiles.length} Python, ${jsonFiles.length} JSON files`,
);
