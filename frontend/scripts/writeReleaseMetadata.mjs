import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FULL_GIT_SHA = /^[0-9a-f]{40}$/;

export function normaliseCommit(value) {
  const candidate = String(value ?? "").trim().toLowerCase();
  if (!FULL_GIT_SHA.test(candidate)) {
    throw new Error("Release commit skal være et fuldt 40-tegns Git SHA");
  }
  return candidate;
}

function defaultGitResolver() {
  return execFileSync("git", ["rev-parse", "HEAD"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
  });
}

export function resolveReleaseCommit({ env = process.env, gitResolver = defaultGitResolver } = {}) {
  for (const name of ["RENDER_GIT_COMMIT", "GITHUB_SHA", "PLANIQ_RELEASE_COMMIT"]) {
    const value = String(env[name] ?? "").trim();
    if (value) return normaliseCommit(value);
  }

  try {
    return normaliseCommit(gitResolver());
  } catch {
    throw new Error("Release commit kunne ikke bestemmes");
  }
}

export function createReleaseMetadata({ product, commit }) {
  const name = String(product ?? "").trim();
  if (!name) throw new Error("Produktnavn må ikke være tomt");
  return {
    product: name,
    component: "frontend",
    commit: normaliseCommit(commit),
  };
}

export function writeReleaseMetadata({
  product,
  outputPath,
  env = process.env,
  gitResolver = defaultGitResolver,
}) {
  const destination = path.resolve(String(outputPath ?? ""));
  if (!outputPath) throw new Error("Outputsti må ikke være tom");
  const metadata = createReleaseMetadata({
    product,
    commit: resolveReleaseCommit({ env, gitResolver }),
  });
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, `${JSON.stringify(metadata, null, 2)}\n`, "utf8");
  return metadata;
}

function parseArguments(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error("Brug --product <navn> --output <sti>");
    }
    values[key.slice(2)] = value;
  }
  if (!values.product || !values.output) {
    throw new Error("Brug --product <navn> --output <sti>");
  }
  return values;
}

const isDirectExecution = process.argv[1]
  && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);

if (isDirectExecution) {
  try {
    const args = parseArguments(process.argv.slice(2));
    const metadata = writeReleaseMetadata({
      product: args.product,
      outputPath: args.output,
    });
    console.log(`Release metadata skrevet for ${metadata.product} (${metadata.commit.slice(0, 12)})`);
  } catch (error) {
    console.error(`Release metadata fejlede: ${error instanceof Error ? error.message : "ukendt fejl"}`);
    process.exitCode = 1;
  }
}
