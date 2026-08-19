import { useCallback, useEffect, useRef, useState } from "react";

export const SESSION_IDLE_WARNING_AFTER_MS = 25 * 60_000;
export const SESSION_IDLE_LOGOUT_AFTER_MS = 30 * 60_000;
export const SESSION_ABSOLUTE_WARNING_BEFORE_MS = 5 * 60_000;

const ACTIVITY_THROTTLE_MS = 5_000;
const ACTIVITY_BROADCAST_THROTTLE_MS = 15_000;
const SESSION_SYNC_STORAGE_KEY = "planiq.session.sync.v1";
const SESSION_END_REASON_KEY = "planiq.session.end-reason.v1";

const TAB_ID = (() => {
  try {
    return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  } catch {
    return `${Date.now()}-${Math.random()}`;
  }
})();

const SESSION_END_MESSAGES = {
  idle: "Du blev logget ud på grund af inaktivitet.",
  absolute: "Din session udløb efter 6 timer. Log ind igen.",
  expired: "Din session er udløbet. Log ind igen.",
};

function parseTimestamp(value) {
  if (!value) return null;
  const timestamp = new Date(value).getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

function writeSessionSyncEvent(payload) {
  try {
    localStorage.setItem(
      SESSION_SYNC_STORAGE_KEY,
      JSON.stringify({ ...payload, source: TAB_ID, writtenAt: Date.now() })
    );
  } catch {
    // Sessionen virker også uden cross-tab synkronisering.
  }
}

export function storeSessionEndReason(reason) {
  if (!SESSION_END_MESSAGES[reason]) return;
  try {
    sessionStorage.setItem(SESSION_END_REASON_KEY, reason);
  } catch {
    // Beskeden er kun en UX-forbedring.
  }
}

export function consumeSessionEndMessage() {
  try {
    const reason = sessionStorage.getItem(SESSION_END_REASON_KEY);
    sessionStorage.removeItem(SESSION_END_REASON_KEY);
    return SESSION_END_MESSAGES[reason] || "";
  } catch {
    return "";
  }
}

export function formatSessionCountdown(totalSeconds) {
  const safeSeconds = Math.max(0, Math.ceil(Number(totalSeconds) || 0));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function useSessionPolicy({
  active,
  sessionExpiresAt,
  validateSession,
  onSessionEnd,
}) {
  const [dialogType, setDialogTypeState] = useState(null);
  const [secondsRemaining, setSecondsRemaining] = useState(0);
  const [continuePending, setContinuePending] = useState(false);
  const [continueError, setContinueError] = useState("");

  const activeRef = useRef(Boolean(active));
  const dialogTypeRef = useRef(null);
  const lastActivityAtRef = useRef(Date.now());
  const lastHandledActivityAtRef = useRef(0);
  const lastBroadcastAtRef = useRef(0);
  const absoluteWarningDismissedRef = useRef(false);
  const endingRef = useRef(false);
  const validateSessionRef = useRef(validateSession);
  const onSessionEndRef = useRef(onSessionEnd);
  const evaluateRef = useRef(() => {});

  useEffect(() => {
    activeRef.current = Boolean(active);
  }, [active]);

  useEffect(() => {
    validateSessionRef.current = validateSession;
  }, [validateSession]);

  useEffect(() => {
    onSessionEndRef.current = onSessionEnd;
  }, [onSessionEnd]);

  const setDialogType = useCallback((nextType) => {
    dialogTypeRef.current = nextType;
    setDialogTypeState(nextType);
    if (!nextType) {
      setContinuePending(false);
      setContinueError("");
    }
  }, []);

  const endSession = useCallback(async (reason = "expired", { broadcast = true } = {}) => {
    if (endingRef.current) return;
    endingRef.current = true;
    setDialogType(null);
    setSecondsRemaining(0);

    if (reason !== "explicit") storeSessionEndReason(reason);
    if (broadcast) writeSessionSyncEvent({ type: "logout", reason });

    try {
      await onSessionEndRef.current?.(reason);
    } finally {
      // Provideren sætter active=false. Ref nulstilles i active-effectet, så et
      // efterfølgende login kan starte en ny, uafhængig sessionpolitik.
    }
  }, [setDialogType]);

  const evaluate = useCallback(() => {
    if (!activeRef.current || endingRef.current) return;

    const now = Date.now();
    const absoluteExpiresAt = parseTimestamp(sessionExpiresAt);
    const idleLogoutAt = lastActivityAtRef.current + SESSION_IDLE_LOGOUT_AFTER_MS;

    if (absoluteExpiresAt && now >= absoluteExpiresAt) {
      void endSession("absolute");
      return;
    }

    if (now >= idleLogoutAt) {
      void endSession("idle");
      return;
    }

    const absoluteWarningWindow = Boolean(
      absoluteExpiresAt &&
      absoluteExpiresAt - now <= SESSION_ABSOLUTE_WARNING_BEFORE_MS
    );

    if (absoluteWarningWindow) {
      if (absoluteWarningDismissedRef.current) {
        if (dialogTypeRef.current) setDialogType(null);
        return;
      }
      if (dialogTypeRef.current !== "absolute") setDialogType("absolute");
      setSecondsRemaining(Math.max(0, Math.ceil((absoluteExpiresAt - now) / 1000)));
      return;
    }

    const idleWarningAt = lastActivityAtRef.current + SESSION_IDLE_WARNING_AFTER_MS;
    if (now >= idleWarningAt) {
      if (dialogTypeRef.current !== "idle") setDialogType("idle");
      setSecondsRemaining(Math.max(0, Math.ceil((idleLogoutAt - now) / 1000)));
      return;
    }

    if (dialogTypeRef.current === "idle") setDialogType(null);
  }, [endSession, sessionExpiresAt, setDialogType]);

  useEffect(() => {
    evaluateRef.current = evaluate;
  }, [evaluate]);

  const applyActivity = useCallback((activityAt = Date.now(), { force = false, broadcast = true } = {}) => {
    if (!activeRef.current || endingRef.current) return;

    const timestamp = Number(activityAt);
    const safeTimestamp = Number.isFinite(timestamp) ? timestamp : Date.now();

    // Når advarslen er åben, kræves et eksplicit klik på "Fortsæt session".
    // Aktivitet i en anden PlanIQ-fane må dog fortsat holde den fælles session aktiv.
    if (dialogTypeRef.current && !force) return;

    if (!force && safeTimestamp - lastHandledActivityAtRef.current < ACTIVITY_THROTTLE_MS) {
      return;
    }

    lastHandledActivityAtRef.current = safeTimestamp;
    lastActivityAtRef.current = Math.max(lastActivityAtRef.current, safeTimestamp);

    if (dialogTypeRef.current === "idle") setDialogType(null);

    if (broadcast && safeTimestamp - lastBroadcastAtRef.current >= ACTIVITY_BROADCAST_THROTTLE_MS) {
      lastBroadcastAtRef.current = safeTimestamp;
      writeSessionSyncEvent({ type: "activity", at: safeTimestamp });
    }

    evaluateRef.current();
  }, [setDialogType]);

  const continueSession = useCallback(async () => {
    if (dialogTypeRef.current !== "idle" || continuePending) return;

    setContinuePending(true);
    setContinueError("");

    try {
      const result = await validateSessionRef.current?.();
      if (result === false) throw new Error("Sessionen kunne ikke bekræftes");
      applyActivity(Date.now(), { force: true, broadcast: true });
      setDialogType(null);
    } catch (error) {
      const status = error?.status ?? error?.response?.status;
      if (status === 401 || status === 403) {
        await endSession("expired");
        return;
      }
      setContinueError(
        "Sessionen kunne ikke fornyes. Kontroller forbindelsen og prøv igen, før tiden udløber."
      );
    } finally {
      setContinuePending(false);
    }
  }, [applyActivity, continuePending, endSession, setDialogType]);

  const logoutNow = useCallback(() => endSession("explicit"), [endSession]);
  const loginAgain = useCallback(() => endSession("explicit"), [endSession]);
  const endExpiredSession = useCallback(() => endSession("expired"), [endSession]);

  const dismissAbsoluteWarning = useCallback(() => {
    absoluteWarningDismissedRef.current = true;
    setDialogType(null);
  }, [setDialogType]);

  useEffect(() => {
    absoluteWarningDismissedRef.current = false;
    evaluateRef.current();
  }, [sessionExpiresAt]);

  useEffect(() => {
    if (!active) {
      endingRef.current = false;
      setDialogType(null);
      setSecondsRemaining(0);
      return undefined;
    }

    endingRef.current = false;
    absoluteWarningDismissedRef.current = false;
    const startedAt = Date.now();
    lastActivityAtRef.current = startedAt;
    lastHandledActivityAtRef.current = startedAt;
    lastBroadcastAtRef.current = 0;

    const handleActivity = () => applyActivity(Date.now());
    const handleVisibilityOrFocus = () => evaluateRef.current();
    const handleStorage = (event) => {
      if (event.key !== SESSION_SYNC_STORAGE_KEY || !event.newValue) return;
      try {
        const message = JSON.parse(event.newValue);
        if (!message || message.source === TAB_ID) return;
        if (message.type === "activity") {
          applyActivity(message.at, { force: true, broadcast: false });
        } else if (message.type === "logout") {
          void endSession(message.reason || "expired", { broadcast: false });
        }
      } catch {
        // Ignorer ugyldige/ældre storage-events.
      }
    };

    const activityEvents = ["pointerdown", "pointermove", "keydown", "scroll", "touchstart"];
    activityEvents.forEach((eventName) => {
      window.addEventListener(eventName, handleActivity, { passive: true });
    });
    window.addEventListener("focus", handleVisibilityOrFocus);
    document.addEventListener("visibilitychange", handleVisibilityOrFocus);
    window.addEventListener("storage", handleStorage);

    writeSessionSyncEvent({ type: "activity", at: startedAt });
    evaluateRef.current();
    const intervalId = window.setInterval(() => evaluateRef.current(), 1000);

    return () => {
      window.clearInterval(intervalId);
      activityEvents.forEach((eventName) => {
        window.removeEventListener(eventName, handleActivity);
      });
      window.removeEventListener("focus", handleVisibilityOrFocus);
      document.removeEventListener("visibilitychange", handleVisibilityOrFocus);
      window.removeEventListener("storage", handleStorage);
    };
  }, [active, applyActivity, endSession, setDialogType]);

  return {
    dialogType,
    secondsRemaining,
    continuePending,
    continueError,
    continueSession,
    logoutNow,
    loginAgain,
    dismissAbsoluteWarning,
    endExpiredSession,
  };
}
