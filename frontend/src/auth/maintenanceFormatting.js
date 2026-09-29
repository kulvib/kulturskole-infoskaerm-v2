const TIME_ZONE = "Europe/Copenhagen";

export function formatMaintenanceExpectedAt(value) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  const datePart = new Intl.DateTimeFormat("da-DK", {
    timeZone: TIME_ZONE,
    day: "numeric",
    month: "numeric",
    year: "numeric",
  }).format(date);
  const timePart = new Intl.DateTimeFormat("da-DK", {
    timeZone: TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
  return `${datePart}, kl. ${timePart}`;
}
