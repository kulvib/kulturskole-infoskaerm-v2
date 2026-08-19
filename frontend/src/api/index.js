// Canonical API module facade for PlanIQ frontends.
// Re-eksporterer legacy api.js og den centrale client.js.
export * from "./api";
export { default as client } from "./client";
export { default } from "./client";
export * from "./apiError";
