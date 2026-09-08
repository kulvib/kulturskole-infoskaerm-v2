/**
 * Fresh-install UX deliberately exposes only the short enrollment code.
 * Exact release metadata and signed authorization are machine-to-machine
 * bootstrap material and must never be rendered as operator handoff text.
 */
export function freshInstallOperatorCode(created) {
  return String(created?.code || "").trim();
}
