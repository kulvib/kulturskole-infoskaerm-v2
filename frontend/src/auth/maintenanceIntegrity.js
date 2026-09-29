function fail() {
  const error = new Error("Serveren returnerede en ugyldig vedligeholdelsesstatus");
  error.code = "MAINTENANCE_CONTRACT_ERROR";
  throw error;
}

function nullableDate(value) {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" || !value.trim()) fail();
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) fail();
  return value;
}

export function requireMaintenanceStatus(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail();
  if (typeof value.enabled !== "boolean") fail();
  if (value.message !== null && value.message !== undefined && typeof value.message !== "string") fail();
  if (typeof value.message === "string" && value.message.length > 500) fail();
  nullableDate(value.expected_end_at);
  nullableDate(value.enabled_at);
  return value;
}
