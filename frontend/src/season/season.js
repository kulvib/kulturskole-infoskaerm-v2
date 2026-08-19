export const DISPLAY_TIME_ZONE = "Europe/Copenhagen";
export const SEASON_REFRESH_MAX_MS = 6 * 60 * 60 * 1000;
export const SEASON_REFRESH_MIN_MS = 60 * 1000;

const SEASON_PATTERN = /^(\d{4})\/(\d{4})$/;

export function parseSeason(season) {
  const match = SEASON_PATTERN.exec(String(season || "").trim());
  if (!match) return null;
  const startYear = Number(match[1]);
  const endYear = Number(match[2]);
  if (!Number.isInteger(startYear) || endYear !== startYear + 1) return null;
  return { startYear, endYear };
}

export function getSeasonValue(season) {
  return season?.value ?? season?.id ?? season?.season ?? season ?? "";
}

export function normalizeSeasonOptions(items = []) {
  if (!Array.isArray(items)) return [];
  const seen = new Set();
  return items
    .map((item) => {
      const value = String(getSeasonValue(item)).trim();
      if (!parseSeason(value) || seen.has(value)) return null;
      seen.add(value);
      return {
        ...item,
        id: value,
        value,
        season: value,
        label: item?.label || value,
        isCurrent: Boolean(item?.isCurrent),
      };
    })
    .filter(Boolean);
}

export function chooseSeason(availableSeasons, preferredSeason, currentSeason) {
  const values = (availableSeasons || [])
    .map((item) => String(getSeasonValue(item)))
    .filter(Boolean);
  if (preferredSeason && values.includes(String(preferredSeason))) return String(preferredSeason);
  if (currentSeason && values.includes(String(currentSeason))) return String(currentSeason);
  return values[0] || String(currentSeason || "");
}

export function getMonthInTimeZone(value, timeZone = DISPLAY_TIME_ZONE) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const monthPart = new Intl.DateTimeFormat("en-US", {
    timeZone,
    month: "numeric",
  }).formatToParts(date).find((part) => part.type === "month");
  return monthPart ? Number(monthPart.value) : null;
}

export function isSeasonPreparationWindow(value, timeZone = DISPLAY_TIME_ZONE) {
  const month = getMonthInTimeZone(value, timeZone);
  return month != null && month >= 5 && month <= 7;
}

export function millisecondsUntilAuthoritativeRefresh({
  serverTimeUtc,
  nextSwitchAt,
  maxDelayMs = SEASON_REFRESH_MAX_MS,
} = {}) {
  const serverNow = Date.parse(serverTimeUtc || "");
  const switchAt = Date.parse(nextSwitchAt || "");
  if (!Number.isFinite(serverNow) || !Number.isFinite(switchAt)) return maxDelayMs;
  const untilSwitch = switchAt - serverNow + 1000;
  return Math.max(SEASON_REFRESH_MIN_MS, Math.min(maxDelayMs, untilSwitch));
}
