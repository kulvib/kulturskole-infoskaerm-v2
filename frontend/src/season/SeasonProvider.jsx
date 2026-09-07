import * as React from "react";
import { getCalendarSeasons, getCurrentSeason } from "../api";
import {
  chooseSeason,
  getSeasonValue,
  isSeasonPreparationWindow,
  millisecondsUntilAuthoritativeRefresh,
  normalizeSeasonOptions,
} from "./season";

const SeasonContext = React.createContext(null);

const INITIAL_STATE = {
  loading: true,
  error: "",
  currentSeason: "",
  nextSeason: "",
  seasonOptions: [],
  timezone: "Europe/Copenhagen",
  serverTimeUtc: "",
  nextSwitchAt: "",
  preparationWindow: false,
};

function normalizeSeasonState(currentPayload, optionsPayload) {
  const seasonOptions = normalizeSeasonOptions(optionsPayload);
  const currentSeason = String(
    getSeasonValue(currentPayload) ||
      getSeasonValue(seasonOptions.find((item) => item.isCurrent)) ||
      getSeasonValue(seasonOptions[0]) ||
      "",
  );
  const nextSeason = String(
    currentPayload?.next_season ||
      getSeasonValue(seasonOptions.find((item) => !item.isCurrent)) ||
      "",
  );
  const timezone = currentPayload?.timezone || "Europe/Copenhagen";
  const serverTimeUtc = currentPayload?.server_time_utc || "";

  return {
    loading: false,
    error: "",
    currentSeason,
    nextSeason,
    seasonOptions,
    timezone,
    serverTimeUtc,
    nextSwitchAt: currentPayload?.next_switch_at || "",
    preparationWindow: isSeasonPreparationWindow(serverTimeUtc, timezone),
  };
}

export function SeasonProvider({ children }) {
  const [state, setState] = React.useState(INITIAL_STATE);
  const requestSequence = React.useRef(0);

  const refreshSeasonClock = React.useCallback(async () => {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    try {
      const [currentPayload, optionsPayload] = await Promise.all([
        getCurrentSeason(),
        getCalendarSeasons(),
      ]);
      if (requestSequence.current !== sequence) return;
      setState(normalizeSeasonState(currentPayload, optionsPayload));
    } catch (error) {
      if (requestSequence.current !== sequence) return;
      setState((previous) => ({
        ...previous,
        loading: false,
        error: error?.message || "Kunne ikke hente sæsonoplysninger.",
      }));
    }
  }, []);

  React.useEffect(() => {
    refreshSeasonClock();
  }, [refreshSeasonClock]);

  React.useEffect(() => {
    const delay = millisecondsUntilAuthoritativeRefresh({
      serverTimeUtc: state.serverTimeUtc,
      nextSwitchAt: state.nextSwitchAt,
    });
    const timeoutId = window.setTimeout(refreshSeasonClock, delay);
    return () => window.clearTimeout(timeoutId);
  }, [refreshSeasonClock, state.nextSwitchAt, state.serverTimeUtc]);

  React.useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible") refreshSeasonClock();
    };
    window.addEventListener("focus", refreshSeasonClock);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("focus", refreshSeasonClock);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [refreshSeasonClock]);

  const value = React.useMemo(
    () => ({ ...state, refreshSeasonClock }),
    [state, refreshSeasonClock],
  );
  return <SeasonContext.Provider value={value}>{children}</SeasonContext.Provider>;
}

export function useSeasonClock() {
  const value = React.useContext(SeasonContext);
  if (!value) throw new Error("useSeasonClock skal bruges under SeasonProvider.");
  return value;
}

export function useSeasonSelection(availableSeasons, { preferredSeason = "", resetKey = null } = {}) {
  const { currentSeason } = useSeasonClock();
  const availableKey = (availableSeasons || []).map(getSeasonValue).join("|");
  const [selectedSeason, setSelectedSeasonState] = React.useState("");
  const followsCurrentRef = React.useRef(true);
  const previousCurrentRef = React.useRef(currentSeason);
  const previousResetKeyRef = React.useRef(resetKey);

  React.useEffect(() => {
    const resetChanged = previousResetKeyRef.current !== resetKey;
    const priorCurrent = previousCurrentRef.current;
    previousResetKeyRef.current = resetKey;
    previousCurrentRef.current = currentSeason;

    setSelectedSeasonState((previous) => {
      const preferred = preferredSeason || previous;
      if (resetChanged || followsCurrentRef.current || previous === priorCurrent || !previous) {
        const next = chooseSeason(availableSeasons, preferred, currentSeason);
        followsCurrentRef.current = next === currentSeason;
        return next;
      }
      if (previous === currentSeason) {
        followsCurrentRef.current = true;
        return previous;
      }
      const values = (availableSeasons || []).map((item) => String(getSeasonValue(item)));
      if (values.includes(previous)) return previous;
      const next = chooseSeason(availableSeasons, preferredSeason, currentSeason);
      followsCurrentRef.current = next === currentSeason;
      return next;
    });
  }, [availableKey, availableSeasons, currentSeason, preferredSeason, resetKey]);

  const setSelectedSeason = React.useCallback((value) => {
    setSelectedSeasonState((previous) => {
      const next = typeof value === "function" ? value(previous) : value;
      followsCurrentRef.current = next === currentSeason;
      return next;
    });
  }, [currentSeason]);

  return { selectedSeason, setSelectedSeason, followsCurrentSeason: followsCurrentRef.current };
}
