import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const DEFAULT_ENTRY_LIMIT_BYTES = 100 * 1024;
const DEFAULT_CHUNK_LIMIT_BYTES = 600 * 1024;
const DEFAULT_MIN_JS_CHUNKS = 5;
const DEFAULT_REQUIRED_DYNAMIC_ENTRIES = Object.freeze([
  "node_modules/hls.js/dist/hls.mjs",
  "src/pages/ClientInfoPage.jsx",
  "src/pages/adminpages/AdminPage.jsx",
  "src/pages/calendarpage/CalendarPage.jsx",
  "src/pages/clientdetailspage/ClientDetailsPageWrapper.jsx",
  "src/pages/clientdetailspage/ClientDetailsActionsSection.jsx",
  "src/pages/clientdetailspage/ClientDetailsInfoSection.jsx",
  "src/pages/clientdetailspage/ClientDetailsLivestreamSection.jsx",
  "src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx",
  "src/pages/clientdetailspage/terminal/ClientTerminalPage.jsx",
]);

function positiveInteger(value, fallback, name) {
  if (value === undefined || value === null || value === "") return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} skal være et positivt heltal`);
  }
  return parsed;
}

export function inspectBundle({
  distDir,
  entryLimitBytes = DEFAULT_ENTRY_LIMIT_BYTES,
  chunkLimitBytes = DEFAULT_CHUNK_LIMIT_BYTES,
  minJsChunks = DEFAULT_MIN_JS_CHUNKS,
  requiredDynamicEntries = DEFAULT_REQUIRED_DYNAMIC_ENTRIES,
}) {
  const manifestPath = path.join(distDir, ".vite", "manifest.json");
  if (!fs.existsSync(manifestPath)) {
    throw new Error(`Vite-manifest mangler: ${manifestPath}`);
  }

  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const entryRecords = Object.values(manifest).filter((record) => record?.isEntry && record?.file);
  if (entryRecords.length !== 1) {
    throw new Error(`Forventede præcis én frontend-entry, fandt ${entryRecords.length}`);
  }

  const missingDynamicEntries = requiredDynamicEntries.filter(
    (source) => !manifest[source]?.isDynamicEntry || !manifest[source]?.file,
  );
  if (missingDynamicEntries.length) {
    throw new Error(`Manglende lazy chunks: ${missingDynamicEntries.join(", ")}`);
  }

  const assetDir = path.join(distDir, "assets");
  const jsFiles = fs
    .readdirSync(assetDir)
    .filter((name) => name.endsWith(".js"))
    .map((name) => {
      const bytes = fs.statSync(path.join(assetDir, name)).size;
      return { name, bytes };
    })
    .sort((a, b) => b.bytes - a.bytes);

  if (jsFiles.length < minJsChunks) {
    throw new Error(
      `Code splitting mangler: fandt ${jsFiles.length} JS-chunks, kræver mindst ${minJsChunks}`,
    );
  }

  const oversized = jsFiles.filter((file) => file.bytes > chunkLimitBytes);
  if (oversized.length) {
    throw new Error(
      `JS-chunk overskrider budgettet på ${chunkLimitBytes} bytes: ${oversized
        .map((file) => `${file.name} (${file.bytes})`)
        .join(", ")}`,
    );
  }

  const entryFile = entryRecords[0].file;
  const entryPath = path.join(distDir, entryFile);
  const entryBytes = fs.statSync(entryPath).size;
  if (entryBytes > entryLimitBytes) {
    throw new Error(
      `Frontend-entry overskrider budgettet på ${entryLimitBytes} bytes: ${entryFile} (${entryBytes})`,
    );
  }

  return {
    entryFile,
    entryBytes,
    jsChunkCount: jsFiles.length,
    largestChunk: jsFiles[0],
  };
}

function parseArguments(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) {
      throw new Error("Brug --dist <mappe> [--entry-limit <bytes>] [--chunk-limit <bytes>] [--min-chunks <antal>]");
    }
    result[key.slice(2)] = value;
  }
  return result;
}

const isDirectExecution = process.argv[1]
  && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);

if (isDirectExecution) {
  try {
    const args = parseArguments(process.argv.slice(2));
    const result = inspectBundle({
      distDir: path.resolve(args.dist || "dist"),
      entryLimitBytes: positiveInteger(args["entry-limit"], DEFAULT_ENTRY_LIMIT_BYTES, "entry-limit"),
      chunkLimitBytes: positiveInteger(args["chunk-limit"], DEFAULT_CHUNK_LIMIT_BYTES, "chunk-limit"),
      minJsChunks: positiveInteger(args["min-chunks"], DEFAULT_MIN_JS_CHUNKS, "min-chunks"),
    });
    console.log(
      `Bundle-budget bestået: ${result.jsChunkCount} chunks, entry ${result.entryBytes} bytes, største chunk ${result.largestChunk.name} (${result.largestChunk.bytes} bytes)`,
    );
  } catch (error) {
    console.error(`Bundle-budget fejlede: ${error instanceof Error ? error.message : "ukendt fejl"}`);
    process.exitCode = 1;
  }
}
