const TERMINAL_UPDATE_STATUSES = new Set(["success", "up_to_date", "error"]);

const UPDATE_STATUS_LABELS = Object.freeze({
  ready: "Klar",
  requested: "Afventer klient",
  starting: "Starter opdatering",
  preparing: "Klargør",
  fetching_manifest: "Henter versionsinfo",
  downloading: "Downloader",
  verifying: "Verificerer",
  installing: "Installerer",
  stopping_services: "Genstarter services",
  success: "Opdateret",
  up_to_date: "Allerede opdateret",
  error: "Fejl",
});

export function normalizeRuntimeStatus(value, fallback = "") {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized || fallback;
}

export function normalizeClientUpdateStatus(value) {
  return normalizeRuntimeStatus(value, "ready");
}

export function isTerminalUpdateStatus(value) {
  return TERMINAL_UPDATE_STATUSES.has(normalizeRuntimeStatus(value));
}

export function getUpdateStatusLabel(value, fallback = "Ukendt") {
  const normalized = normalizeClientUpdateStatus(value);
  return UPDATE_STATUS_LABELS[normalized] || fallback;
}
