import AppSnackbar from "../../components/AppSnackbar";
import React, { useState, useCallback, useEffect, useRef } from "react";
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  Tooltip,
  Grid,
  useMediaQuery,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  DialogContentText,
  Alert,
  Stack,
} from "@mui/material";
import PowerSettingsNewIcon from "@mui/icons-material/PowerSettingsNew";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import NightlightIcon from "@mui/icons-material/Nightlight";
import WbSunnyIcon from "@mui/icons-material/WbSunny";
import ChromeReaderModeIcon from "@mui/icons-material/ChromeReaderMode";
import StopIcon from "@mui/icons-material/Stop";
import TerminalIcon from "@mui/icons-material/Terminal";
import DesktopWindowsIcon from "@mui/icons-material/DesktopWindows";
import { useTheme } from "@mui/material/styles";
import { useAuth } from "../../auth/AuthProvider";
import { getActiveClientflowDeployment } from "../../api";

/*
  DetailsActionsSection.jsx

  FIX:
  - MUI crash "Cannot read properties of undefined (reading 'main')" skyldtes
    ugyldige color-props som "default" på Button i MUI v5.
  - Alle button colors er nu ændret til gyldige MUI-farver:
      primary, secondary, success, error, warning, info, inherit
  - Det forhindrer render-crash og gør at sektionen kan opdatere korrekt.

  KNAP-LOGIK:
  - Kiosk/system-knapper låses under igangværende actions.
  - Loader/spinner og kort status-/procesbar fjernet fra knapområdet.
  - Terminal og Fjernskrivebord låses aldrig af frontend-logik.
    De er supportværktøjer og skal kunne åbnes, også mens klienten
    opdaterer, genstarter, sover, er offline eller har pending actions.
    Hvis forbindelsen ikke virker, skal terminal-/remote-flowet selv vise fejlen.
*/

const BUSY_CHROME_STEPS = new Set([
  "clear_cookies",
  "terminate_chrome",
  "kill_chrome",
  "starting_chrome",
  "countdown",
  "display_sleep_countdown",
]);

const SYSTEM_LOCK_STEPS = new Set([
  "system_reboot_countdown",
  "system_rebooting",
  "system_shutting_down",
]);

const SYSTEM_SLEEP_STEPS = new Set([
  "system_sleep",
  "system_sleep_complete",
  "display_sleep",
  "display_sleep_complete",
]);

const UPDATE_PANEL_FINISHED_FEEDBACK_MS = 5_000;

const OS_UPDATE_STEP_LABELS = {
  os_update_requested: "Ubuntu-opdatering afventer klient",
  os_update_started: "Ubuntu-opdatering startet",
  os_updating: "Ubuntu-opdatering kører",
  os_update_fetching: "Ubuntu henter pakkeliste…",
  os_upgrading: "Ubuntu installerer pakker…",
  os_update_installing: "Ubuntu installerer pakker…",
  os_cleanup: "Ubuntu rydder op…",
  os_update_cleanup: "Ubuntu rydder op…",
  os_update_complete: "Ubuntu-opdatering gennemført",
  os_update_none: "Ubuntu er allerede opdateret",
  os_update_failed: "Ubuntu-opdatering fejlede",
  os_update_reset: "Ubuntu-opdateringsstatus nulstillet",
};

const OS_UPDATE_BUSY_STEPS = new Set([
  "os_update_requested",
  "os_update_started",
  "os_updating",
  "os_update_fetching",
  "os_upgrading",
  "os_update_installing",
  "os_cleanup",
  "os_update_cleanup",
]);

const OS_UPDATE_TERMINAL_STEPS = new Set([
  "os_update_complete",
  "os_update_none",
  "os_update_failed",
  "os_update_reset",
]);

const OS_UPDATE_BUSY_STATUSES = new Set([
  "requested",
  "starting",
  "checking",
  "installing",
  "cleanup",
  "rebooting",
]);

const OS_UPDATE_TERMINAL_STATUSES = new Set([
  "success",
  "up_to_date",
  "error",
]);

function getUbuntuUpdateLabel(step, pendingAction, clientState) {
  const s = String(step || "").trim().toLowerCase();
  if (s && OS_UPDATE_STEP_LABELS[s]) return OS_UPDATE_STEP_LABELS[s];

  const action = String(pendingAction || "").trim().toLowerCase();
  if (action === "os_update") return "Ubuntu-opdatering afventer klient";

  const state = String(clientState || "").trim().toLowerCase();
  if (state === "updating") return "Ubuntu-opdatering kører";

  return "Ubuntu-opdatering kører";
}

const CHROME_RUNNING_STEPS = new Set([
  "start_chrome",
  "chrome_opened_manual",
]);

const CHROME_STOPPED_STEPS = new Set([
  "chrome_closed_programmatically",
  "chrome_closed_manual",
  "shutdown_chrome",
  "kill_chrome",
  "system_sleep",
  "system_sleep_complete",
  "display_sleep",
  "display_sleep_complete",
  "display_wake",
  "display_wake_complete",
  "system_wake",
  "system_wake_complete",
  "system_rebooting",
  "system_shutting_down",
]);

const WAKE_STEPS = new Set([
  "system_wake",
  "system_wake_complete",
  "display_wake",
  "display_wake_complete",
]);

const WAKE_IN_PROGRESS_STEPS = new Set([
  "system_wake",
  "display_wake",
]);

const WAKE_COMPLETE_STEPS = new Set([
  "system_wake_complete",
  "display_wake_complete",
]);

const SYSTEM_PENDING_ACTIONS = new Set([
  "reboot",
  "restart",
  "pending_reboot",
  "shutdown",
  "pending_shutdown",
]);

const SLEEP_PENDING_ACTIONS = new Set([
  "sleep",
  "display_sleep",
  "system_sleep",
]);

const WAKE_PENDING_ACTIONS = new Set([
  "wakeup",
  "wake",
  "display_wake",
  "system_wake",
]);

const LIVESTREAM_RUNNING_STATUSES = new Set([
  "starting",
  "running",
]);

const PENDING_ACTION_LABELS = {
  start: "Starter kiosk browser…",
  stop: "Stopper kiosk browser…",
  sleep: "Sætter klient i dvale…",
  display_sleep: "Sætter klient i dvale…",
  system_sleep: "Sætter klient i dvale…",
  wakeup: "Vækker klient fra dvale…",
  wake: "Vækker klient fra dvale…",
  display_wake: "Vækker klient fra dvale…",
  system_wake: "Vækker klient fra dvale…",
  reboot: "Genstarter klient…",
  restart: "Genstarter klient…",
  pending_reboot: "Genstarter klient…",
  shutdown: "Slukker klient…",
  pending_shutdown: "Slukker klient…",
  reset_browser: "Nulstiller kiosk browser…",
  os_update: "Ubuntu-opdatering afventer klient",
};

const STALE_BROWSER_STEPS_IGNORED_DURING_WAKE = new Set([
  "clear_cookies",
  "terminate_chrome",
  "kill_chrome",
  "shutdown_chrome",
  "start_chrome",
]);

function getStepLabel(step) {
  if (!step) return null;
  const s = String(step).toLowerCase();
  if (s === "clear_cookies") return "Rydder cookies…";
  if (s === "terminate_chrome") return "Lukker browser…";
  if (s === "kill_chrome") return "Tvangslukker browser…";
  if (s === "starting_chrome") return "Starter browser…";
  if (s === "shutdown_chrome") return "Browser lukket";
  if (s === "countdown") return null;
  if (s === "display_sleep_countdown") return "Skærm slukkes om lidt…";
  if (s === "system_reboot_countdown") return "Genstarter om lidt…";
  if (s === "system_rebooting") return "Genstarter maskinen…";
  if (s === "system_shutting_down") return "Lukker maskinen ned…";
  if (s === "start_chrome") return "Browser startet";
  if (s === "chrome_closed_programmatically") return "Browser lukket";
  if (s === "chrome_closed_manual") return "Browser lukket manuelt";
  if (s === "system_sleep" || s === "display_sleep") return "Skærm slukkes…";
  if (s === "system_sleep_complete" || s === "display_sleep_complete") return "Skærm slukket";
  if (s === "system_wake" || s === "display_wake") return "Skærm tændes…";
  if (s === "system_wake_complete" || s === "display_wake_complete") return "Skærm tændt";
  if (OS_UPDATE_STEP_LABELS[s]) return OS_UPDATE_STEP_LABELS[s];
  if (s === "error") return "Der opstod en fejl";
  return null;
}

const CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES = new Set([
  "authorized", "downloading", "verified", "staged", "activating", "health_check", "rolling_back",
]);

const SERVICE_BUSY_VALUES = new Set([
  "opdaterer",
  "starter",
  "kører",
  "koerer",
  "running",
  "active",
  "activating",
]);

function serviceLooksBusy(value) {
  const st = String(value || "").trim().toLowerCase();
  return SERVICE_BUSY_VALUES.has(st);
}

function isUbuntuTerminalStep(step, status) {
  const s = String(step || "").trim().toLowerCase();
  const st = String(status || "").trim().toLowerCase();
  return OS_UPDATE_TERMINAL_STEPS.has(s) || OS_UPDATE_TERMINAL_STATUSES.has(st);
}

function getUbuntuUpdateStepMeta(step, pendingAction, clientState, serviceStatus, status) {
  const s = String(step || "").trim().toLowerCase();
  const st = String(status || "").trim().toLowerCase();
  const label = st === "success"
    ? "Ubuntu-opdatering gennemført"
    : st === "up_to_date"
    ? "Ubuntu er allerede opdateret"
    : st === "error"
    ? "Ubuntu-opdatering fejlede"
    : getUbuntuUpdateLabel(step, pendingAction, clientState);

  if (st === "success") {
    return { label, description: "Ubuntu-opdateringen er gennemført." };
  }
  if (st === "up_to_date") {
    return { label, description: "Klienten fandt ingen Ubuntu-pakker der skulle installeres." };
  }
  if (st === "error") {
    return { label, description: "Ubuntu-opdateringen fejlede. Tjek fejlbeskeden og klientloggen." };
  }

  if (s === "os_update_complete") {
    return { label, description: "Ubuntu-opdateringen er gennemført." };
  }
  if (s === "os_update_none") {
    return { label, description: "Klienten fandt ingen Ubuntu-pakker der skulle installeres." };
  }
  if (s === "os_update_failed") {
    return { label, description: "Ubuntu-opdateringen fejlede. Tjek status/log på klienten." };
  }
  if (s === "os_update_reset") {
    return { label, description: "Ubuntu-opdateringsstatus er nulstillet." };
  }
  if (s && OS_UPDATE_STEP_LABELS[s]) {
    return { label, description: OS_UPDATE_STEP_LABELS[s] };
  }

  const service = String(serviceStatus || "").trim();
  if (service) {
    return { label, description: `Service-status: ${service}` };
  }

  return { label, description: "Ubuntu-opdateringen er sendt til klienten." };
}

function formatUpdateDateTime(value) {
  if (!value) return null;
  const raw = String(value);
  const d = new Date(raw.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw}Z`);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat("da-DK", {
    timeZone: "Europe/Copenhagen",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
}

const actionBtnStyle = {
  minWidth: 0,
  width: "100%",
  minHeight: 48,
  height: "auto",
  fontSize: { xs: "0.84rem", sm: "0.9rem", lg: "0.92rem" },
  textTransform: "none",
  fontWeight: 850,
  lineHeight: 1.18,
  py: 1,
  px: { xs: 1, sm: 1.2 },
  m: 0,
  whiteSpace: "normal",
  overflowWrap: "anywhere",
  textAlign: "center",
  display: "inline-flex",
  justifyContent: "center",
  alignItems: "center",
  borderRadius: 2,
  boxShadow: 1,
  "& .MuiButton-startIcon": {
    mr: 0.7,
    flex: "0 0 auto",
  },
};

function ActionButton({ btn, isMobile, busy }) {
  const isSupportTool = btn?.key === "terminal" || btn?.key === "remote";
  const lockDuringBusy = btn.lockDuringBusy !== false;

  // Terminal og Fjernskrivebord er supportværktøjer og må aldrig låses af
  // frontend-state. Hvis forbindelsen fejler, skal terminal-/remote-dialogen
  // selv vise fejlen. Almindelige handlinger låses stadig defensivt.
  const isDisabled = isSupportTool
    ? false
    : !!btn.disabled || (lockDuringBusy && !!busy) || !!btn.loading;

  const tooltipText = isDisabled
    ? btn.disabledTooltip || btn.tooltip || "Ikke tilgængelig"
    : btn.tooltip || "";

  const button = (
    <span style={{ width: "100%" }}>
      <Button
        variant={btn.variant}
        color={btn.color}
        startIcon={btn.icon}
        disabled={isDisabled}
        onClick={btn.onClick}
        sx={actionBtnStyle}
        fullWidth
      >
        {btn.label}
      </Button>
    </span>
  );

  if (isMobile) return button;

  return (
    <Tooltip title={tooltipText} arrow>
      {button}
    </Tooltip>
  );
}

export default function ClientDetailsActionsSection({
  clientId,
  clientState,
  pendingChromeAction,
  handleClientAction,
  handleOpenTerminal,
  handleOpenRemoteDesktop,
  refreshing,
  showSnackbar: showSnackbarProp,
  clientOnline = false,
  clientActionPending = false,
  liveStep = null,
  liveChromeStatus = null,
  chromeRunning = null,
  clientStatus = null,
  pendingOsUpdate = false,
  serviceUbuntuUpdateStatus = null,
  ubuntuUpdatesAvailable = null,
  ubuntuUpdateStatus = null,
  ubuntuUpdateStep = null,
  ubuntuUpdateMessage = null,
  ubuntuUpdateError = null,
  ubuntuUpdateStartedAt = null,
  ubuntuUpdateUpdatedAt = null,
  ubuntuUpdateFinishedAt = null,
  ubuntuUpdateProgress = null,
  ubuntuUpdatePackageCount = null,
  ubuntuUpdateRebootRequired = null,
  livestreamStatus = null,
  livestreamProcessStatus = null,
  compact = false,
  controlRoom = false,
  hideHeader = false,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const { user } = useAuth();

  const role = user?.role || "";
  const isAdmin = role === "admin" || role === "superadmin";
  const isAdministrator = role === "admin";
  const isSuperadmin = role === "superadmin";
  const isViewer = role === "viewer";
  const canControlClient = ["superadmin", "admin", "bruger"].includes(role);

  const [clientflowDeployment, setClientflowDeployment] = useState(null);

  useEffect(() => {
    if (!clientId || !isSuperadmin) {
      setClientflowDeployment(null);
      return undefined;
    }
    let active = true;
    const refreshDeployment = async () => {
      try {
        const current = await getActiveClientflowDeployment(clientId);
        if (active) setClientflowDeployment(current || null);
      } catch {
        if (active) setClientflowDeployment(null);
      }
    };
    refreshDeployment();
    const timer = window.setInterval(refreshDeployment, 2500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [clientId, isSuperadmin]);

  const [actionLoading, setActionLoading] = useState({});
  const [shutdownDialogOpen, setShutdownDialogOpen] = useState(false);
  const [localSnackbar, setLocalSnackbar] = useState({
    open: false,
    message: "",
    severity: "success",
  });
  const [ubuntuUpdateFeedbackVisible, setUbuntuUpdateFeedbackVisible] = useState(false);
  const ubuntuWasBusyRef = useRef(false);

  const normalizedClientState = String(clientState || "").trim().toLowerCase();
  const normalizedPendingAction = String(pendingChromeAction || "").trim().toLowerCase();
  const hasPendingAction = !!normalizedPendingAction && normalizedPendingAction !== "none";
  const clientUnavailable = clientOnline !== true;
  const clientUnavailableMessage = "Klienten er ikke online via canonical Status-domain";
  const normalizedClientStatus = String(clientStatus || "").trim().toLowerCase();
  const clientIsApproved = normalizedClientStatus === "approved";
  const normalizedLivestreamStatus = String(livestreamStatus || "").trim().toLowerCase();
  const normalizedLivestreamProcessStatus = String(livestreamProcessStatus || "").trim().toLowerCase();
  const livestreamIsRunning =
    LIVESTREAM_RUNNING_STATUSES.has(normalizedLivestreamStatus) ||
    LIVESTREAM_RUNNING_STATUSES.has(normalizedLivestreamProcessStatus);

  const liveStepNorm = String(liveStep ?? "").trim().toLowerCase();

  const clientflowDeploymentState = String(clientflowDeployment?.state || "").trim().toLowerCase();
  const clientflowUpdateBusy = CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES.has(clientflowDeploymentState);
  const clientflowBusyTooltip =
    "ClientFlow opdateres via canonical deployment — vent til deploymenten er afsluttet";

  const normalizedUbuntuUpdateStatus = String(ubuntuUpdateStatus || "").trim().toLowerCase();
  const effectiveUbuntuStepNorm = String(ubuntuUpdateStep || liveStep || "").trim().toLowerCase();
  const ubuntuUpdateInProgress =
    pendingOsUpdate === true ||
    normalizedPendingAction === "os_update" ||
    OS_UPDATE_BUSY_STATUSES.has(normalizedUbuntuUpdateStatus) ||
    OS_UPDATE_BUSY_STEPS.has(effectiveUbuntuStepNorm) ||
    serviceLooksBusy(serviceUbuntuUpdateStatus);
  const ubuntuUpdateFinished = isUbuntuTerminalStep(
    effectiveUbuntuStepNorm,
    normalizedUbuntuUpdateStatus
  );
  const ubuntuUpdateStepMeta = getUbuntuUpdateStepMeta(
    effectiveUbuntuStepNorm,
    normalizedPendingAction,
    normalizedClientState,
    serviceUbuntuUpdateStatus,
    normalizedUbuntuUpdateStatus
  );
  const ubuntuUpdateSeverity =
    normalizedUbuntuUpdateStatus === "error" || effectiveUbuntuStepNorm === "os_update_failed"
      ? "error"
      : ubuntuUpdateFinished
      ? "success"
      : "info";
  const showUbuntuUpdatePanel =
    ubuntuUpdateInProgress ||
    (ubuntuUpdateFeedbackVisible && ubuntuUpdateFinished);

  const ubuntuUpdateBusy = ubuntuUpdateInProgress;

  const ubuntuUpdateBusyTooltip =
    "Ubuntu opdateres — vent til opdateringen er færdig";

  const systemActionPending = SYSTEM_PENDING_ACTIONS.has(normalizedPendingAction);
  const sleepActionPending = SLEEP_PENDING_ACTIONS.has(normalizedPendingAction);
  const wakeActionPending = WAKE_PENDING_ACTIONS.has(normalizedPendingAction);

  // System-level handlinger må låse kiosk/skærm/strøm.
  // Det er vigtigt at medtage lokal pendingAction="reboot"/"shutdown", fordi
  // reboot/sluk ikke er en chrome-command og derfor ofte når UI'et før liveStep.
  const isSystemLocked =
    SYSTEM_LOCK_STEPS.has(liveStepNorm) ||
    systemActionPending ||
    normalizedClientState.startsWith("reboot") ||
    normalizedClientState.startsWith("shut");

  const wakeCompleted = WAKE_COMPLETE_STEPS.has(liveStepNorm);
  const wakeInProgress =
    wakeActionPending ||
    !!actionLoading["wakeup"] ||
    WAKE_IN_PROGRESS_STEPS.has(liveStepNorm);

  // Dvale skal ikke låse hele panelet; den skal kun efterlade "Væk fra dvale" aktiv.
  // Når wake er i gang eller gennemført, må stale state="sleeping" ikke holde UI'et
  // fast i dvale og aktivere Væk-knappen igen.
  const isSleeping =
    !wakeInProgress &&
    !wakeCompleted &&
    (normalizedClientState.startsWith("sleep") ||
      SYSTEM_SLEEP_STEPS.has(liveStepNorm) ||
      sleepActionPending);

  // Wake er display-only. Hvis der ligger en gammel chrome_status som
  // "Rydder cookies…" fra en tidligere browserhandling, må den ikke vises
  // oven på Væk-fra-dvale-flowet.
  const isWakeDisplayOnly = wakeInProgress || (wakeCompleted && (clientActionPending || hasPendingAction));

  const isLiveStepBusy = BUSY_CHROME_STEPS.has(liveStepNorm) || OS_UPDATE_BUSY_STEPS.has(liveStepNorm) || isSystemLocked;

  const explicitChromeRunning = typeof chromeRunning === "boolean" ? chromeRunning : null;
  const liveChromeStatusNorm = String(liveChromeStatus || "").trim().toLowerCase();
  const chromeStatusLooksRunning =
    liveChromeStatusNorm.includes("browser kører") ||
    liveChromeStatusNorm.includes("kiosk browser kører") ||
    liveChromeStatusNorm.includes("browser startet");
  const chromeStatusLooksStopped =
    liveChromeStatusNorm.includes("browser lukket") ||
    liveChromeStatusNorm.includes("browser stoppet") ||
    liveChromeStatusNorm.includes("lukket ved systemstart");

  const chromeIsRunning = explicitChromeRunning !== null
    ? explicitChromeRunning
    : CHROME_RUNNING_STEPS.has(liveStepNorm)
    ? true
    : CHROME_STOPPED_STEPS.has(liveStepNorm)
    ? false
    : chromeStatusLooksRunning
    ? true
    : chromeStatusLooksStopped
    ? false
    : null;

  const anyLoading = Object.values(actionLoading).some(Boolean);

  // v7.1.34: display_wake_complete er terminalt og display-only.
  // Hvis backend allerede har pending_chrome_action=none, må et stale
  // clientActionPending ikke låse Start/Stop kiosk efter wake.
  const clientActionPendingForLock =
    clientActionPending && !(wakeCompleted && !hasPendingAction && !wakeActionPending);

  // Almindelige kiosk/system-handlinger må låse hinanden for at undgå
  // kolliderende handlinger som start+stop, sleep+reboot osv.
  // v7.1.36: almindelig side-refresh må ikke låse kioskknapperne.
  // Chrome-sandheden kommer fra hurtig /chrome-status polling, og efter
  // display_wake_complete kan parent-refresh kort være true, selv om backend
  // allerede siger state=normal, pending_chrome_action=none og chrome_running=false.
  // Reelle låse er stadig pending actions, busy steps og update/system-state.
  const actionPanelBusy =
    anyLoading ||
    clientActionPendingForLock ||
    hasPendingAction ||
    isLiveStepBusy ||
    clientflowUpdateBusy ||
    ubuntuUpdateBusy;

  // Supportværktøjer må aldrig låses af frontend-logik.
  // Terminal og Fjernskrivebord skal være tilgængelige ved fejlfinding,
  // også under update, reboot/shutdown, dvale, offline-status og pending actions.
  // Hvis forbindelsen ikke kan etableres, håndteres fejlen i terminal-/remote-flowet.
  const notify = useCallback(
    (opts) => {
      if (typeof showSnackbarProp === "function") {
        showSnackbarProp(opts);
      } else {
        setLocalSnackbar({
          open: true,
          message: opts?.message ?? "",
          severity: opts?.severity ?? "success",
        });
      }
    },
    [showSnackbarProp]
  );

  const doAction = useCallback(
    async (action) => {
      if (clientUnavailable) {
        notify({
          message: `${clientUnavailableMessage} — handling afvist`,
          severity: "warning",
        });
        return;
      }

      if (isSystemLocked) {
        notify({
          message: "Klienten genstarter eller lukker ned — handling afvist",
          severity: "warning",
        });
        return;
      }

      if (clientflowUpdateBusy) {
        notify({
          message: clientflowBusyTooltip,
          severity: "warning",
        });
        return;
      }

      if (ubuntuUpdateBusy) {
        notify({
          message: ubuntuUpdateBusyTooltip,
          severity: "warning",
        });
        return;
      }

      if ((action === "start" || action === "stop") && normalizedClientStatus && !clientIsApproved) {
        notify({
          message: "Kiosk browser kan først styres, når klienten er godkendt",
          severity: "warning",
        });
        return;
      }


      if (isSleeping && action !== "wakeup") {
        notify({
          message: "Klienten er i dvale — brug Væk fra dvale først",
          severity: "warning",
        });
        return;
      }

      if (action === "wakeup" && (wakeInProgress || !isSleeping)) {
        notify({
          message: wakeInProgress ? "Væk fra dvale er allerede sendt" : "Klienten er allerede vågen",
          severity: "info",
        });
        return;
      }

      setActionLoading((prev) => ({ ...prev, [action]: true }));
      try {
        await handleClientAction(action);
      } catch (err) {
        notify({
          message: "Fejl: " + (err?.message || "Kunne ikke udføre handling"),
          severity: "error",
        });
      } finally {
        setActionLoading((prev) => ({ ...prev, [action]: false }));
      }
    },
    [
      clientUnavailable,
      clientUnavailableMessage,
      isSystemLocked,
      clientflowUpdateBusy,
      clientflowBusyTooltip,
      ubuntuUpdateBusy,
      ubuntuUpdateBusyTooltip,
      normalizedClientStatus,
      clientIsApproved,
      isSleeping,
      wakeInProgress,
      handleClientAction,
      notify,
    ]
  );

  const getActionDisabledInfo = useCallback(
    (key) => {
      if (clientUnavailable) return { disabled: true, reason: clientUnavailableMessage };
      if (isSystemLocked) return { disabled: true, reason: "Klienten genstarter eller lukker ned" };
      if (clientflowUpdateBusy) return { disabled: true, reason: clientflowBusyTooltip };
      if (ubuntuUpdateBusy) return { disabled: true, reason: ubuntuUpdateBusyTooltip };

      if ((key === "start" || key === "stop") && normalizedClientStatus && !clientIsApproved) {
        return { disabled: true, reason: "Kiosk browser kan først styres, når klienten er godkendt" };
      }


      if (wakeInProgress && key === "wakeup") {
        return { disabled: true, reason: "Væk fra dvale er allerede sendt" };
      }

      if (isSleeping) {
        if (key === "wakeup") return { disabled: false, reason: "Væk klient fra dvale" };
        return {
          disabled: true,
          reason: "Klienten er i dvale — brug Væk fra dvale først",
        };
      }

      if (key === "wakeup") return { disabled: true, reason: "Klienten er allerede vågen" };
      if (key === "sleep" && sleepActionPending) return { disabled: true, reason: "Dvale er allerede sendt" };
      if (key === "start" && chromeIsRunning === true) return { disabled: true, reason: "Kiosk browser kører allerede" };
      if (key === "stop" && chromeIsRunning === false) return { disabled: true, reason: "Kiosk browser er allerede stoppet" };

      return { disabled: false, reason: null };
    },
    [
      clientUnavailable,
      clientUnavailableMessage,
      isSystemLocked,
      clientflowUpdateBusy,
      clientflowBusyTooltip,
      ubuntuUpdateBusy,
      ubuntuUpdateBusyTooltip,
      normalizedClientStatus,
      clientIsApproved,
      wakeInProgress,
      isSleeping,
      sleepActionPending,
      chromeIsRunning,
    ]
  );

  const isDisabledByState = useCallback(
    (key) => getActionDisabledInfo(key).disabled,
    [getActionDisabledInfo]
  );

  const getDisabledTooltip = useCallback(
    (key, fallback = "Ikke tilgængelig") => getActionDisabledInfo(key).reason || fallback,
    [getActionDisabledInfo]
  );

  useEffect(() => {
    if (ubuntuUpdateInProgress) {
      ubuntuWasBusyRef.current = true;
      setUbuntuUpdateFeedbackVisible(true);
      return;
    }

    if (ubuntuWasBusyRef.current && ubuntuUpdateFinished) {
      ubuntuWasBusyRef.current = false;
      setUbuntuUpdateFeedbackVisible(true);
    }
  }, [ubuntuUpdateInProgress, ubuntuUpdateFinished, effectiveUbuntuStepNorm, normalizedUbuntuUpdateStatus]);

  useEffect(() => {
    if (!ubuntuUpdateFeedbackVisible || ubuntuUpdateInProgress || !ubuntuUpdateFinished) {
      return undefined;
    }

    const timer = window.setTimeout(() => {
      setUbuntuUpdateFeedbackVisible(false);
    }, UPDATE_PANEL_FINISHED_FEEDBACK_MS);

    return () => window.clearTimeout(timer);
  }, [ubuntuUpdateFeedbackVisible, ubuntuUpdateInProgress, ubuntuUpdateFinished, effectiveUbuntuStepNorm, normalizedUbuntuUpdateStatus]);

  const ubuntuPackageCount = Number.parseInt(
    String(ubuntuUpdatePackageCount ?? ubuntuUpdatesAvailable ?? ""),
    10
  );
  const ubuntuPackageText = Number.isFinite(ubuntuPackageCount)
    ? ubuntuPackageCount === 1
      ? "1 pakke"
      : `${ubuntuPackageCount} pakker`
    : null;
  const ubuntuProgressValue = Number.parseInt(String(ubuntuUpdateProgress ?? ""), 10);
  const ubuntuProgressText = Number.isFinite(ubuntuProgressValue)
    ? `${Math.max(0, Math.min(100, ubuntuProgressValue))}%`
    : null;
  const ubuntuUpdateStartedText = formatUpdateDateTime(ubuntuUpdateStartedAt);
  const ubuntuUpdateUpdatedText = formatUpdateDateTime(ubuntuUpdateUpdatedAt);
  const ubuntuUpdateFinishedText = formatUpdateDateTime(ubuntuUpdateFinishedAt);

  const renderUpdatePanel = ({ type, severity, title, meta, message, details }) => (
    <Alert
      severity={severity}
      sx={{
        mb: 1.25,
        borderRadius: 2,
        border: severity === "error" ? "1px solid rgba(248,113,113,0.30)" : "1px solid rgba(56,189,248,0.24)",
        background: severity === "error" ? "rgba(127,29,29,0.16)" : "rgba(14,165,233,0.10)",
        color: controlRoom ? "#e2e8f0" : undefined,
        "& .MuiAlert-message": { width: "100%" },
      }}
    >
      <Stack spacing={0.45}>
        <Typography variant="body2" sx={{ fontWeight: 950 }}>
          {title}: {meta.label}
        </Typography>
        <Typography variant="caption" sx={{ opacity: 0.88 }}>
          {message || meta.description}
        </Typography>
        {details?.length > 0 && (
          <Stack direction="row" spacing={1} useFlexGap sx={{
            flexWrap: "wrap"
          }}>
            {details.map((item) => (
              <Typography key={`${type}-${item.label}`} variant="caption" sx={{ opacity: 0.72 }}>
                {item.label}: {item.value}
              </Typography>
            ))}
          </Stack>
        )}
      </Stack>
    </Alert>
  );

  const row1 = [
    {
      key: "start",
      label: "Start kiosk browser",
      icon: <ChromeReaderModeIcon />,
      color: "primary",
      variant: "outlined",
      onClick: () => doAction("start"),
      loading: !!actionLoading["start"],
      disabled: isDisabledByState("start"),
      disabledTooltip: getDisabledTooltip("start", "Start kiosk browser"),
      lockDuringBusy: true,
      tooltip:
        chromeIsRunning === true
          ? "Kiosk browser kører allerede"
          : "Start kiosk browser",
    },
    {
      key: "stop",
      label: "Stop kiosk browser",
      icon: <StopIcon />,
      color: "secondary",
      variant: "outlined",
      onClick: () => doAction("stop"),
      loading: !!actionLoading["stop"],
      disabled: isDisabledByState("stop"),
      disabledTooltip: getDisabledTooltip("stop", "Stop kiosk browser"),
      lockDuringBusy: true,
      tooltip:
        chromeIsRunning === false
          ? "Kiosk browser er allerede stoppet"
          : "Stop kiosk browser",
    },
    {
      key: "sleep",
      label: "Sæt i dvale",
      icon: <NightlightIcon />,
      color: "info",
      variant: "outlined",
      onClick: () => doAction("sleep"),
      loading: !!actionLoading["sleep"],
      disabled: isDisabledByState("sleep"),
      disabledTooltip: getDisabledTooltip("sleep", "Sæt klient i dvale"),
      lockDuringBusy: true,
      tooltip: "Sæt klient i dvale",
    },
    {
      key: "wakeup",
      label: "Væk fra dvale",
      icon: <WbSunnyIcon />,
      color: "success",
      variant: "outlined",
      onClick: () => doAction("wakeup"),
      loading: !!actionLoading["wakeup"],
      disabled: isDisabledByState("wakeup"),
      disabledTooltip: getDisabledTooltip("wakeup", "Væk klient fra dvale"),
      lockDuringBusy: false,
      tooltip: "Væk klient fra dvale",
    },
  ];

  const openShutdownDialog = () => {
    if (typeof document !== "undefined" && document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
    setShutdownDialogOpen(true);
  };

  const row2Admin = [
    {
      key: "reboot",
      label: "Genstart klient",
      icon: <RestartAltIcon />,
      color: "warning",
      variant: "contained",
      onClick: () => doAction("reboot"),
      loading: !!actionLoading["reboot"],
      disabled: isDisabledByState("reboot"),
      disabledTooltip: getDisabledTooltip("reboot", "Genstart klient"),
      lockDuringBusy: true,
      tooltip: "Genstart klient",
    },
    {
      key: "shutdown",
      label: "Sluk klient",
      icon: <PowerSettingsNewIcon />,
      color: "error",
      variant: "contained",
      onClick: openShutdownDialog,
      loading: !!actionLoading["shutdown"],
      disabled: isDisabledByState("shutdown"),
      disabledTooltip: getDisabledTooltip("shutdown", "Sluk klient"),
      lockDuringBusy: true,
      tooltip: "Sluk klient — kræver fysisk tænding bagefter",
    },
  ];

  const row2Superadmin = [
    {
      key: "terminal",
      label: "Terminal",
      icon: <TerminalIcon />,
      color: "inherit",
      variant: "outlined",
      onClick: handleOpenTerminal,
      loading: false,
      disabled: false,
      lockDuringBusy: false,
      disabledTooltip: "",
      tooltip: "Åbn terminal",
    },
    {
      key: "remote",
      label: "Fjernskrivebord",
      icon: <DesktopWindowsIcon />,
      color: "inherit",
      variant: "outlined",
      onClick: handleOpenRemoteDesktop,
      loading: false,
      disabled: false,
      lockDuringBusy: false,
      disabledTooltip: "",
      tooltip: "Åbn fjernskrivebord",
    },
  ];
  const kioskButtons = canControlClient ? row1.filter((btn) => btn.key === "start" || btn.key === "stop") : [];
  const displayButtons = canControlClient ? row1.filter((btn) => btn.key === "sleep" || btn.key === "wakeup") : [];
  const systemButtons = isSuperadmin
    ? row2Admin
    : isAdministrator
      ? row2Admin.filter((btn) => btn.key === "reboot")
      : [];
  const supportButtons = isSuperadmin ? row2Superadmin : [];

  const renderActionGroup = (title, buttons, tone = "default") => {
    if (!buttons.length) return null;

    const toneBorder = tone === "danger"
      ? "rgba(248,113,113,0.24)"
      : tone === "support"
      ? "rgba(125,211,252,0.22)"
      : "rgba(148,163,184,0.15)";

    const toneBg = tone === "danger"
      ? "rgba(127,29,29,0.16)"
      : tone === "support"
      ? "rgba(14,165,233,0.08)"
      : "rgba(15,23,42,0.26)";

    return (
      <Box
        sx={{
          height: "100%",
          p: { xs: 1.8, sm: 2.15 },
          borderRadius: 2,
          border: `1px solid ${toneBorder}`,
          background: toneBg,
        }}
      >
        <Typography
          variant="caption"
          sx={{
            display: "block",
            mb: 1.2,
            color: tone === "danger" ? "#fecaca" : "rgba(203,213,225,0.78)",
            fontWeight: 950,
            letterSpacing: 0.55,
            textTransform: "uppercase",
          }}
        >
          {title}
        </Typography>
        <Grid container spacing={1}>
          {buttons.map((btn) => (
            <Grid key={btn.key} size={12}>
              <ActionButton btn={btn} isMobile={isMobile} busy={actionPanelBusy} />
            </Grid>
          ))}
        </Grid>
      </Box>
    );
  };

  const cardStyle = clientUnavailable ? { opacity: 0.85 } : {};

  const controlRoomCardSx = controlRoom
    ? {
        borderRadius: 2,
        mb: 0,
        height: "100%",
        background: "rgba(15,23,42,0.16)",
        border: "1px solid rgba(148,163,184,0.10)",
        boxShadow: "none",
        color: "#f8fafc",
        "& .MuiTypography-root": { color: "inherit" },
        "& .MuiTypography-colorTextSecondary": { color: "rgba(203,213,225,0.66)" },
        "& .MuiAlert-root": {
          borderRadius: 2,
          border: "1px solid rgba(148,163,184,0.18)",
        },
        "& .MuiButton-root": {
          minHeight: 42,
          borderRadius: 2,
          fontWeight: 850,
          boxShadow: "none",
        },
        "& .MuiButton-outlined": {
          color: "rgba(248,250,252,0.94)",
          borderColor: "rgba(148,163,184,0.26)",
          background: "rgba(15,23,42,0.24)",
        },
        "& .MuiButton-outlined:hover": {
          borderColor: "rgba(125,211,252,0.54)",
          background: "rgba(14,165,233,0.12)",
        },
        "& .MuiButton-contained": {
          boxShadow: "0 14px 28px rgba(0,0,0,0.24)",
        },
        "& .Mui-disabled": {
          WebkitTextFillColor: "rgba(203,213,225,0.35)",
          color: "rgba(203,213,225,0.35) !important",
          borderColor: "rgba(148,163,184,0.10) !important",
        },
      }
    : {};

  const primaryButtonGridProps = compact
    ? { xs: 12, sm: 6, md: 3 }
    : { xs: 12, sm: 6, md: 3 };

  const adminButtonGridProps = compact
    ? { xs: 12, sm: 6, md: 3 }
    : { xs: 12, sm: 6, md: isSuperadmin ? 3 : 6 };

  return (
    <Card elevation={controlRoom ? 0 : 2} sx={{ borderRadius: 2, mb: compact ? 0 : 2, height: compact ? "100%" : "auto", ...cardStyle, ...controlRoomCardSx }}>
      <CardContent sx={{ px: isMobile ? 1.5 : 2.4, py: compact ? 1.9 : 2.4 }}>
        {!hideHeader && (
          <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 1, mb: 1.25 }}>
            <Box>
              <Typography variant="overline" sx={{ fontWeight: 950, letterSpacing: 0.9, color: controlRoom ? "rgba(125,211,252,0.76)" : "text.secondary" }}>
                Kontrolpanel
              </Typography>
              <Typography variant="h6" sx={{ fontWeight: 950, lineHeight: 1.1 }}>
                Kontrolpanel
              </Typography>
              <Typography variant="body2" sx={{
                color: "text.secondary"
              }}>
                Handlinger låses automatisk ved aktive processer.
              </Typography>
            </Box>
          </Box>
        )}

        {showUbuntuUpdatePanel && renderUpdatePanel({
          type: "ubuntu",
          severity: ubuntuUpdateSeverity,
          title: "Ubuntu-opdatering",
          meta: ubuntuUpdateStepMeta,
          message:
            ubuntuUpdateError ||
            ubuntuUpdateMessage ||
            OS_UPDATE_STEP_LABELS[effectiveUbuntuStepNorm] ||
            (effectiveUbuntuStepNorm.startsWith("os_") ? liveChromeStatus : null),
          details: [
            ubuntuProgressText ? { label: "Fremdrift", value: ubuntuProgressText } : null,
            ubuntuPackageText ? { label: "Pakker", value: ubuntuPackageText } : null,
            ubuntuUpdateRebootRequired === true ? { label: "Genstart", value: "Påkrævet" } : null,
            ubuntuUpdateStartedText ? { label: "Startet", value: ubuntuUpdateStartedText } : null,
            ubuntuUpdateUpdatedText ? { label: "Opdateret", value: ubuntuUpdateUpdatedText } : null,
            ubuntuUpdateFinishedText ? { label: "Afsluttet", value: ubuntuUpdateFinishedText } : null,
            serviceUbuntuUpdateStatus ? { label: "Service", value: serviceUbuntuUpdateStatus } : null,
          ].filter(Boolean),
        })}

        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              md: "repeat(2, minmax(0, 1fr))",
              lg: isSuperadmin
                ? "repeat(4, minmax(190px, 1fr))"
                : "repeat(2, minmax(220px, 1fr))",
            },
            gap: { xs: 1.15, sm: 1.35 },
            alignItems: "stretch",
          }}
        >
          {isViewer && (
            <Alert severity="info" sx={{ borderRadius: 2 }}>
              Se adgang har kun læseadgang. Knapper til styring, strøm, terminal og fjernskrivebord er skjult.
            </Alert>
          )}
          {renderActionGroup("Kiosk browser", kioskButtons)}
          {renderActionGroup("Skærm", displayButtons)}
          {isSuperadmin && renderActionGroup("Support", supportButtons, "support")}
          {systemButtons.length > 0 && renderActionGroup("Strøm", systemButtons, "danger")}
        </Box>

        {clientUnavailable && (
          <Typography
            variant="body2"
            sx={{ color: "text.secondary", mt: 1.5, fontSize: isMobile ? 11 : 13 }}
          >
            {clientUnavailableMessage} — live-handlinger er ikke tilgængelige.
          </Typography>
        )}

        {isSleeping && !clientUnavailable && !ubuntuUpdateBusy && (
          <Typography
            variant="body2"
            color="primary"
            sx={{ mt: 1.5, fontSize: isMobile ? 11 : 13 }}
          >
            Klienten er i dvale — brug "Væk fra dvale" for at aktivere den.
          </Typography>
        )}
      </CardContent>
      <Dialog
        open={shutdownDialogOpen}
        onClose={() => setShutdownDialogOpen(false)}
        maxWidth="xs"
        fullWidth
        disableRestoreFocus
      >
        <DialogTitle>Bekræft slukning af klient</DialogTitle>
        <DialogContent>
          <DialogContentText>
            <strong>Ved dette valg skal klienten startes manuelt lokalt.</strong>
            <br />
            Er du sikker på, at du vil slukke klienten?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShutdownDialogOpen(false)} color="primary">
            Annuller
          </Button>
          <Button
            onClick={async () => {
              setShutdownDialogOpen(false);
              await doAction("shutdown");
            }}
            color="error"
            variant="contained"
            disabled={isDisabledByState("shutdown") || actionPanelBusy}
          >
            Ja, sluk klienten
          </Button>
        </DialogActions>
      </Dialog>
      <AppSnackbar
        open={localSnackbar.open}
        message={localSnackbar.message}
        severity={localSnackbar.severity}
        onClose={() => setLocalSnackbar((s) => ({ ...s, open: false }))}
      />
    </Card>
  );
}
