#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

function printUsage() {
  const usage = [
    "voltsnip-skill CLI",
    "",
    "Usage:",
    "  npx @vaddisrinivas/voltsnip-skill --print",
    "  npx @vaddisrinivas/voltsnip-skill --output ./SKILL.md",
    "",
    "Options:",
    "  --print            Print SKILL.md to stdout",
    "  --output <path>    Write SKILL.md to a file",
    "  --help             Show this help",
  ];
  console.log(usage.join("\n"));
}

function loadSkill() {
  const skillPath = path.join(__dirname, "..", "SKILL.md");
  return fs.readFileSync(skillPath, "utf8");
}

const args = process.argv.slice(2);
if (args.includes("--help") || args.length === 0) {
  printUsage();
  process.exit(0);
}

const outputIndex = args.indexOf("--output");
if (outputIndex !== -1) {
  const outPath = args[outputIndex + 1];
  if (!outPath) {
    console.error("Missing value for --output");
    printUsage();
    process.exit(1);
  }
  fs.writeFileSync(outPath, loadSkill(), "utf8");
  console.log(`Wrote SKILL.md to ${outPath}`);
}

if (args.includes("--print")) {
  process.stdout.write(loadSkill());
}
