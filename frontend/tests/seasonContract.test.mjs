import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";
import {
  chooseSeason,
  getMonthInTimeZone,
  isSeasonPreparationWindow,
  millisecondsUntilAuthoritativeRefresh,
  normalizeSeasonOptions,
  parseSeason,
} from "../src/season/season.js";

test("sæsonformat valideres centralt", () => {
  assert.deepEqual(parseSeason("2025/2026"), { startYear: 2025, endYear: 2026 });
  assert.equal(parseSeason("2025/2027"), null);
  assert.equal(parseSeason("2025-2026"), null);
});

test("backendens to sæsoner normaliseres uden lokale ekstra sæsoner", () => {
  assert.deepEqual(
    normalizeSeasonOptions([
      { id: "2025/2026", isCurrent: true },
      { season: "2026/2027" },
      { id: "2026/2027" },
    ]).map((item) => item.value),
    ["2025/2026", "2026/2027"],
  );
  assert.equal(
    chooseSeason([{ id: "2025/2026" }, { id: "2026/2027" }], "2024/2025", "2025/2026"),
    "2025/2026",
  );
});

test("forberedelsesvinduet bruger Europe/Copenhagen og ikke browserens tidszone", () => {
  assert.equal(getMonthInTimeZone("2026-04-30T22:30:00Z"), 5);
  assert.equal(isSeasonPreparationWindow("2026-04-30T22:30:00Z"), true);
  assert.equal(isSeasonPreparationWindow("2026-07-31T22:30:00Z"), false);
});

test("åben frontend genindlæser senest hver sjette time og præcist tæt på rollover", () => {
  assert.equal(
    millisecondsUntilAuthoritativeRefresh({
      serverTimeUtc: "2026-07-31T21:59:00Z",
      nextSwitchAt: "2026-08-01T00:00:00+02:00",
    }),
    61_000,
  );
  assert.equal(
    millisecondsUntilAuthoritativeRefresh({
      serverTimeUtc: "2026-06-01T00:00:00Z",
      nextSwitchAt: "2026-08-01T00:00:00+02:00",
    }),
    6 * 60 * 60 * 1000,
  );
});

test("sæsonkonteksten bruger backendens autoritative endpoints og genindlæser ved fokus", () => {
  const provider = fs.readFileSync(new URL("../src/season/SeasonProvider.jsx", import.meta.url), "utf8");
  assert.match(provider, /getCurrentSeason/);
  assert.match(provider, /getCalendarSeasons/);
  assert.match(provider, /serverTimeUtc/);
  assert.match(provider, /nextSwitchAt/);
  assert.match(provider, /window\.addEventListener\("focus"/);
  assert.match(provider, /document\.addEventListener\("visibilitychange"/);
});

test("kalender og organisationsadministration bruger den fælles sæsonkontekst", () => {
  for (const relative of [
    "../src/pages/calendarpage/CalendarPage.jsx",
    "../src/pages/adminpages/OrganizationAdministration.jsx",
  ]) {
    const source = fs.readFileSync(new URL(relative, import.meta.url), "utf8");
    assert.match(source, /useSeasonClock/);
    assert.doesNotMatch(source, /getMonth\(\)\s*>?=\s*7/);
    assert.doesNotMatch(source, /getCalendarSeasons\(\)/);
  }
});

test("readiness-advarslen er read-only og kun synlig ved konkrete afvigelser", () => {
  const source = fs.readFileSync(new URL("../src/season/SeasonPreparationAlert.jsx", import.meta.url), "utf8");
  assert.match(source, /getSeasonReadiness/);
  assert.match(source, /preparationWindow/);
  assert.match(source, /!current\.data\.is_ready/);
  assert.match(source, /!next\.data\.is_ready/);
});
