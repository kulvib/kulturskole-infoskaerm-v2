import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(here, "..");
const allowlistPath = path.join(frontendRoot, "dependency-audit-allowlist.json");
const allowlist = JSON.parse(fs.readFileSync(allowlistPath, "utf8"));

const result = spawnSync("npm", ["audit", "--json"], {
  cwd: frontendRoot,
  encoding: "utf8",
  shell: process.platform === "win32",
});

if (!result.stdout?.trim()) {
  console.error(result.stderr || "npm audit returnerede intet JSON-svar.");
  process.exit(2);
}

let report;
try {
  report = JSON.parse(result.stdout);
} catch (error) {
  console.error("npm audit-svaret kunne ikke parses som JSON.", error);
  process.exit(2);
}

const today = new Date().toISOString().slice(0, 10);
const exceptions = new Map((allowlist.exceptions || []).map((entry) => [entry.package, entry]));
const vulnerabilities = new Map();

// npm audit kan returnere forskellige JSON-formater på tværs af npm-versioner. Bevar støtte for
// vulnerability-formatet, så quality gaten ikke bliver skrøbelig ved formatændringer.
for (const advisory of Object.values(report.advisories || {})) {
  const packageName = advisory.module_name;
  if (!packageName) continue;
  const advisoryId = advisory.github_advisory_id
    || String(advisory.url || "").split("/").pop()
    || String(advisory.id || "");
  const current = vulnerabilities.get(packageName) || {
    severity: advisory.severity || "unknown",
    advisoryIds: [],
  };
  if (advisoryId) current.advisoryIds.push(advisoryId);
  vulnerabilities.set(packageName, current);
}

for (const [packageName, vulnerability] of Object.entries(report.vulnerabilities || {})) {
  const advisoryIds = (vulnerability.via || [])
    .filter((item) => item && typeof item === "object")
    .map((item) => item.github_advisory_id || String(item.url || "").split("/").pop())
    .filter(Boolean);
  vulnerabilities.set(packageName, {
    severity: vulnerability.severity || "unknown",
    advisoryIds,
  });
}

const unexpected = [];
const accepted = [];
for (const [packageName, vulnerability] of vulnerabilities.entries()) {
  const exception = exceptions.get(packageName);
  const allowedIds = new Set(exception?.advisories || []);
  const idsCovered = vulnerability.advisoryIds.length > 0
    && vulnerability.advisoryIds.every((id) => allowedIds.has(id));
  const validUntil = exception?.expires && exception.expires >= today;

  if (exception && idsCovered && validUntil) {
    accepted.push(`${packageName}: ${vulnerability.advisoryIds.join(", ")} (udløber ${exception.expires})`);
  } else {
    unexpected.push({ packageName, vulnerability });
  }
}

if (accepted.length) {
  console.warn("Accepterede, tidsbegrænsede dependency-undtagelser:");
  for (const line of accepted) console.warn(`- ${line}`);
}

if (unexpected.length) {
  console.error("Uventede eller udløbne frontend-advisories:");
  for (const item of unexpected) {
    console.error(`- ${item.packageName} (${item.vulnerability.severity}): ${item.vulnerability.advisoryIds.join(", ") || "ukendt advisory"}`);
  }
  process.exit(1);
}

const totals = report.metadata?.vulnerabilities || {};
const total = totals.total ?? Object.values(totals).reduce(
  (sum, value) => sum + (Number.isFinite(value) ? value : 0),
  0,
);
console.log(`Frontend dependency-audit bestået (${total || 0} rapporterede, ${accepted.length} kontrolleret undtaget).`);
