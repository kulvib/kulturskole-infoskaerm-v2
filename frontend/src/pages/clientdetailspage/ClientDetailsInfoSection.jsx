import React from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  LinearProgress,
  IconButton,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
  useMediaQuery,
} from "@mui/material";
import { useTheme } from "@mui/material/styles";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import SaveIcon from "@mui/icons-material/Save";
import SystemUpdateAltIcon from "@mui/icons-material/SystemUpdateAlt";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";
import RefreshIcon from "@mui/icons-material/Refresh";
import { getOrganizations as apiGetOrganizations, updateClient as apiUpdateClient, changeClientOrganization as apiChangeClientOrganization, getClientflowDeployments, getClientflowReleases, requestClientflowDeployment, cancelClientflowDeployment, requestOsUpdate, requestCfadminPasswordChange as apiRequestCfadminPasswordChange, requestLocalHostnameChange as apiRequestLocalHostnameChange, getClientLocalManagement as apiGetClientLocalManagement } from "../../api";
import { useAuth } from "../../auth/AuthProvider";
import { compactDarkChipSx } from "../../utils/chipStyles";
import DateTimeEditDialog from "../calendarpage/DateTimeEditDialog";

const UKEDAGE = ["Søndag", "Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag"];

const FIELD_BG = "rgba(15, 23, 42, 0.48)";
const BORDER = "rgba(148, 163, 184, 0.16)";
const TEXT = "#f8fafc";
const MUTED = "rgba(203, 213, 225, 0.68)";


const CLIENTFLOW_DEPLOYMENT_STEPS = [
  { key: "authorized", label: "Autoriseret", description: "Backend har bundet deploymenten til en konkret godkendt release.", progress: 10 },
  { key: "downloading", label: "Downloader", description: "Den stabile updater downloader præcis den autoriserede bundle.", progress: 25 },
  { key: "verified", label: "Verificeret", description: "Bundle SHA-256, størrelse og provenance er verificeret.", progress: 42 },
  { key: "staged", label: "Staged", description: "Releasen er staged lokalt og backend har registreret det.", progress: 58 },
  { key: "activating", label: "Aktiverer", description: "Backendens activation-gate er passeret, og den lokale release aktiveres.", progress: 75 },
  { key: "health_check", label: "Health check", description: "Den nye release kontrolleres efter aktivering.", progress: 90 },
];

const CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES = new Set([
  "authorized", "downloading", "verified", "staged", "activating", "health_check", "rolling_back",
]);
const CLIENTFLOW_DEPLOYMENT_TERMINAL_STATES = new Set([
  "succeeded", "failed", "cancelled", "rolled_back", "recovery_failed",
]);
const CLIENTFLOW_DEPLOYMENT_CANCELLABLE_STATES = new Set([
  "authorized", "downloading", "verified", "staged",
]);
const UPDATE_DETAIL_FINISHED_FEEDBACK_MS = 5_000;
const CLIENTFLOW_FINISHED_FEEDBACK_MS = UPDATE_DETAIL_FINISHED_FEEDBACK_MS;

function compareClientflowVersions(left, right) {
  const parse = (value) => String(value || "").replace(/^v/i, "").split(".").map((part) => Number.parseInt(part, 10) || 0);
  const a = parse(left);
  const b = parse(right);
  const width = Math.max(a.length, b.length);
  for (let index = 0; index < width; index += 1) {
    const delta = (a[index] || 0) - (b[index] || 0);
    if (delta !== 0) return delta > 0 ? 1 : -1;
  }
  return 0;
}

const UBUNTU_UPDATE_STEPS = [
  { key: "requested", label: "Afventer klient", description: "Backend har registreret Ubuntu-opdateringen. Klienten henter den ved næste sync.", progress: 12 },
  { key: "starting", label: "Starter", description: "Klienten har modtaget Ubuntu-opdateringen og starter update-flowet.", progress: 24 },
  { key: "checking", label: "Henter pakkeliste", description: "Klienten opdaterer pakkelisten og tjekker Ubuntu-repositories.", progress: 42 },
  { key: "installing", label: "Installerer pakker", description: "Klienten installerer Ubuntu-opdateringer.", progress: 72 },
  { key: "cleanup", label: "Rydder op", description: "Klienten rydder op efter opdateringen.", progress: 88 },
  { key: "rebooting", label: "Genstarter", description: "Klienten genstarter, hvis Ubuntu kræver det.", progress: 96 },
];

const UBUNTU_UPDATE_BUSY_STEPS = new Set(UBUNTU_UPDATE_STEPS.map((step) => step.key));
const UBUNTU_FINISHED_FEEDBACK_MS = UPDATE_DETAIL_FINISHED_FEEDBACK_MS;
const UBUNTU_POLL_MS = 5_000;
const UBUNTU_REQUEST_WAIT_TIMEOUT_MS = 120_000;

function normalizeClientflowDeploymentState(value) {
  return String(value || "").trim().toLowerCase();
}

function getClientflowDeploymentStepMeta(state) {
  const normalized = normalizeClientflowDeploymentState(state);
  const index = CLIENTFLOW_DEPLOYMENT_STEPS.findIndex((step) => step.key === normalized);
  if (index >= 0) return { ...CLIENTFLOW_DEPLOYMENT_STEPS[index], index };
  if (normalized === "succeeded") {
    return { label: "Gennemført", description: "ClientFlow-deploymenten er aktiveret og health-checket.", index: CLIENTFLOW_DEPLOYMENT_STEPS.length, progress: 100 };
  }
  if (normalized === "rolling_back") {
    return { label: "Ruller tilbage", description: "Aktiveringen fejlede, og den tidligere release gendannes.", index: -1, progress: 100 };
  }
  if (normalized === "rolled_back") {
    return { label: "Rullet tilbage", description: "Den tidligere release er gendannet efter en fejlet aktivering.", index: -1, progress: 100 };
  }
  if (normalized === "cancelled") {
    return { label: "Annulleret", description: "Deploymenten blev annulleret før aktivering.", index: -1, progress: 0 };
  }
  if (normalized === "recovery_failed") {
    return { label: "Recovery fejlede", description: "Aktivering og recovery kunne ikke afsluttes sikkert.", index: -1, progress: 100 };
  }
  if (normalized === "failed") {
    return { label: "Fejl", description: "ClientFlow-deploymenten fejlede.", index: -1, progress: 100 };
  }
  return { label: "Klar", description: "Ingen aktiv ClientFlow-deployment.", index: -1, progress: 0 };
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

function UpdateStepTimeline({ steps, currentIndex = -1, terminal = false, error = false }) {
  if (!Array.isArray(steps) || steps.length === 0) return null;
  return (
    <Stack
      direction="row"
      spacing={0.75}
      useFlexGap
      sx={{
        flexWrap: "wrap",
        mt: 1
      }}>
      {steps.map((step, index) => {
        const done = !error && (terminal || (currentIndex >= 0 && index < currentIndex));
        const active = !terminal && !error && index === currentIndex;
        const chipTone = error && index === currentIndex
          ? "error"
          : active
          ? "info"
          : done
          ? "success"
          : "neutral";
        return (
          <Chip
            key={step.key}
            size="small"
            label={`${index + 1}. ${step.label}`}
            sx={compactDarkChipSx(chipTone, {
              height: 22,
              fontWeight: active ? 900 : 750,
              "& .MuiChip-label": { px: 0.9, fontSize: "0.68rem" },
            })}
          />
        );
      })}
    </Stack>
  );
}

function ClientFlowUpdateControl({ clientId, clientVersion, pendingOsUpdate, showSnackbar, onFinished }) {
  const [deployment, setDeployment] = React.useState(null);
  const [polling, setPolling] = React.useState(false);
  const [starting, setStarting] = React.useState(false);
  const [cancelling, setCancelling] = React.useState(false);
  const [feedbackVisible, setFeedbackVisible] = React.useState(false);
  const [releaseCatalog, setReleaseCatalog] = React.useState(null);
  const [selectedVersion, setSelectedVersion] = React.useState("latest");
  const [downgradeDialogOpen, setDowngradeDialogOpen] = React.useState(false);
  const [downgradeReason, setDowngradeReason] = React.useState("");

  const state = normalizeClientflowDeploymentState(deployment?.state);
  const meta = getClientflowDeploymentStepMeta(state);
  const inProgress = CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES.has(state);
  const finished = CLIENTFLOW_DEPLOYMENT_TERMINAL_STATES.has(state);
  const otherUpdateInProgress = !inProgress && pendingOsUpdate === true;
  const installedVersion = clientVersion;
  const latestVersion = releaseCatalog?.latest_stable || null;
  const selectableReleases = React.useMemo(
    () => (releaseCatalog?.releases || []).filter((release) =>
      ["stable", "supported"].includes(String(release?.status || "")) && release?.update_allowed === true
    ),
    [releaseCatalog],
  );
  const resolvedSelectedVersion = selectedVersion === "latest" ? latestVersion : selectedVersion;
  const selectedRelease = selectableReleases.find((release) => release.version === resolvedSelectedVersion) || null;
  const isDowngrade = Boolean(
    installedVersion && resolvedSelectedVersion && compareClientflowVersions(resolvedSelectedVersion, installedVersion) < 0
  );
  const sameVersionSelected = Boolean(
    installedVersion && resolvedSelectedVersion && compareClientflowVersions(resolvedSelectedVersion, installedVersion) === 0
  );
  const requestedAt = formatUpdateDateTime(deployment?.requested_at);
  const updatedAt = formatUpdateDateTime(deployment?.state_updated_at);
  const finishedAt = formatUpdateDateTime(deployment?.completed_at);
  const error = deployment?.failure_message || deployment?.failure_code || null;
  const showPanel = Boolean(deployment) && (inProgress || feedbackVisible);
  const canCancel = CLIENTFLOW_DEPLOYMENT_CANCELLABLE_STATES.has(state);

  const refreshStatus = React.useCallback(async () => {
    if (!clientId) return null;
    try {
      const rows = await getClientflowDeployments(clientId);
      const latest = Array.isArray(rows) && rows.length ? rows[0] : null;
      setDeployment(latest);
      const latestState = normalizeClientflowDeploymentState(latest?.state);
      if (CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES.has(latestState)) {
        setFeedbackVisible(true);
        setPolling(true);
      }
      return latest;
    } catch {
      return null;
    }
  }, [clientId]);

  React.useEffect(() => {
    let active = true;
    getClientflowReleases()
      .then((catalog) => {
        if (!active) return;
        setReleaseCatalog(catalog);
        setSelectedVersion("latest");
      })
      .catch((errorValue) => {
        if (active) showSnackbar?.({ message: errorValue?.message || "Kunne ikke hente ClientFlow-versioner", severity: "error" });
      });
    return () => { active = false; };
  }, [showSnackbar]);

  React.useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  React.useEffect(() => {
    if (!polling || !clientId) return undefined;
    const timer = window.setInterval(async () => {
      const latest = await refreshStatus();
      const latestState = normalizeClientflowDeploymentState(latest?.state);
      if (!CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES.has(latestState)) {
        setFeedbackVisible(true);
        setPolling(false);
        onFinished?.();
      }
    }, 2500);
    return () => window.clearInterval(timer);
  }, [polling, clientId, refreshStatus, onFinished]);

  React.useEffect(() => {
    if (!feedbackVisible || inProgress || starting || cancelling || !finished) return undefined;
    const timer = window.setTimeout(() => setFeedbackVisible(false), CLIENTFLOW_FINISHED_FEEDBACK_MS);
    return () => window.clearTimeout(timer);
  }, [feedbackVisible, inProgress, starting, cancelling, finished, state]);

  const executeClientFlowUpdate = async ({ confirmDowngrade = false, reason = null } = {}) => {
    if (!clientId || starting || inProgress || otherUpdateInProgress || sameVersionSelected) return;
    setFeedbackVisible(true);
    setStarting(true);
    try {
      const created = await requestClientflowDeployment(clientId, {
        targetVersion: resolvedSelectedVersion,
        confirmDowngrade,
        reason,
      });
      setDeployment(created);
      setPolling(CLIENTFLOW_DEPLOYMENT_ACTIVE_STATES.has(normalizeClientflowDeploymentState(created?.state)));
      showSnackbar?.({ message: `ClientFlow-deployment til v${created?.target_version || resolvedSelectedVersion} er autoriseret`, severity: "success" });
    } catch (err) {
      showSnackbar?.({ message: `Fejl: ${err?.message || "Kunne ikke oprette ClientFlow-deployment"}`, severity: "error" });
    } finally {
      setStarting(false);
    }
  };

  const cancelDeployment = async () => {
    if (!deployment?.id || !canCancel || cancelling) return;
    setCancelling(true);
    try {
      const cancelled = await cancelClientflowDeployment(deployment.id);
      setDeployment(cancelled);
      setPolling(false);
      setFeedbackVisible(true);
      showSnackbar?.({ message: "ClientFlow-deployment annulleret", severity: "info" });
      onFinished?.();
    } catch (err) {
      showSnackbar?.({ message: `Fejl: ${err?.message || "Kunne ikke annullere ClientFlow-deployment"}`, severity: "error" });
    } finally {
      setCancelling(false);
    }
  };

  const startClientFlowUpdate = (event) => {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    if (isDowngrade || (!installedVersion && selectedVersion !== "latest")) {
      setDowngradeDialogOpen(true);
      return;
    }
    executeClientFlowUpdate();
  };

  const confirmClientFlowDowngrade = async () => {
    const reason = downgradeReason.trim();
    if (!reason) return;
    setDowngradeDialogOpen(false);
    await executeClientFlowUpdate({ confirmDowngrade: true, reason });
    setDowngradeReason("");
  };

  const disabled = !clientId || starting || inProgress || otherUpdateInProgress || !releaseCatalog || !selectedRelease || sameVersionSelected;
  const stateIsError = state === "failed" || state === "recovery_failed";
  const stateIsWarning = state === "cancelled" || state === "rolled_back" || state === "rolling_back";
  const stateIsSuccess = state === "succeeded";
  const statusColor = stateIsError ? "#f87171" : stateIsSuccess ? "#22c55e" : stateIsWarning ? "#fbbf24" : inProgress ? "#38bdf8" : MUTED;
  const statusText = starting ? "Autoriserer deployment" : deployment ? meta.label : otherUpdateInProgress ? "Afventer anden opdatering" : "Klar";

  return (
    <Box sx={{ p: 1.15, borderRadius: 2, background: FIELD_BG, border: `1px solid ${BORDER}` }}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ alignItems: { xs: "stretch", sm: "center" }, justifyContent: "space-between" }}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle2" sx={{ color: TEXT, fontWeight: 950 }}>ClientFlow-opdatering</Typography>
          <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", mt: 0.45 }}>
            <Typography variant="caption" sx={{ color: MUTED }}>
              Installeret: {installedVersion ? `v${String(installedVersion).replace(/^v/i, "")}` : "ikke rapporteret"}
            </Typography>
            {latestVersion && <Typography variant="caption" sx={{ color: MUTED }}>Seneste: v{String(latestVersion).replace(/^v/i, "")}</Typography>}
            {deployment?.target_version && <Typography variant="caption" sx={{ color: MUTED }}>Deployment: v{String(deployment.target_version).replace(/^v/i, "")}</Typography>}
            <Typography variant="caption" sx={{ color: statusColor, fontWeight: 850 }}>{statusText}</Typography>
          </Stack>
        </Box>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={0.8} sx={{ alignItems: { xs: "stretch", sm: "center" } }}>
          <TextField select size="small" label="Målversion" value={selectedVersion} onChange={(event) => setSelectedVersion(event.target.value)} disabled={starting || inProgress || otherUpdateInProgress || !releaseCatalog} sx={{ minWidth: { xs: "100%", sm: 220 } }}>
            <MenuItem value="latest">Seneste stabile{latestVersion ? ` (v${latestVersion})` : ""}</MenuItem>
            {selectableReleases.filter((release) => release.version !== latestVersion).map((release) => (
              <MenuItem key={release.version} value={release.version}>v{release.version} · {release.status === "supported" ? "understøttet" : release.status}</MenuItem>
            ))}
          </TextField>
          {canCancel && (
            <Button size="small" variant="outlined" color="warning" disabled={cancelling} onClick={cancelDeployment} sx={{ borderRadius: 2, fontWeight: 850, whiteSpace: "nowrap" }}>
              {cancelling ? "Annullerer…" : "Annuller deployment"}
            </Button>
          )}
          <Button size="small" variant="outlined" color={isDowngrade ? "warning" : "info"} startIcon={starting || inProgress ? <CircularProgress size={16} color="inherit" /> : <SystemUpdateAltIcon />} disabled={disabled} type="button" onClick={startClientFlowUpdate} sx={{ borderRadius: 2, fontWeight: 850, whiteSpace: "nowrap" }}>
            {starting || inProgress ? "Opdaterer ClientFlow…" : sameVersionSelected ? "Versionen er installeret" : isDowngrade ? `Nedgrader til v${resolvedSelectedVersion}` : "Tjek/opdater ClientFlow"}
          </Button>
        </Stack>
      </Stack>
      {showPanel && (
        <Box sx={{ mt: 1, p: 1, borderRadius: 2, background: stateIsError ? "rgba(248,113,113,0.10)" : stateIsWarning ? "rgba(251,191,36,0.10)" : "rgba(56,189,248,0.10)", border: stateIsError ? "1px solid rgba(248,113,113,0.28)" : stateIsWarning ? "1px solid rgba(251,191,36,0.28)" : "1px solid rgba(56,189,248,0.24)" }}>
          <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap" }}>
            <Stack spacing={0.15} sx={{ minWidth: 0 }}>
              <Typography variant="caption" sx={{ color: MUTED, fontWeight: 850, textTransform: "uppercase", letterSpacing: 0.6 }}>Canonical deployment</Typography>
              <Stack direction="row" spacing={1} sx={{ alignItems: "center", minWidth: 0 }}>
                {(starting || inProgress) && <CircularProgress size={15} sx={{ color: "#7dd3fc" }} />}
                <Typography variant="body2" sx={{ color: TEXT, fontWeight: 900 }}>{meta.label}{deployment?.target_version ? ` · v${deployment.target_version}` : ""}</Typography>
              </Stack>
            </Stack>
            {meta.index >= 0 && inProgress && <Typography variant="caption" sx={{ color: MUTED }}>Trin {meta.index + 1} / {CLIENTFLOW_DEPLOYMENT_STEPS.length}</Typography>}
          </Stack>
          <Typography variant="body2" sx={{ mt: 0.5, color: stateIsError ? "#fca5a5" : MUTED }}>
            {error || meta.description}
          </Typography>
          {(inProgress || stateIsSuccess) && (
            <Box sx={{ mt: 1, height: 6, borderRadius: 999, background: "rgba(15,23,42,0.75)", overflow: "hidden" }}>
              <Box sx={{ height: "100%", width: `${Math.max(6, Math.min(100, meta.progress || 6))}%`, borderRadius: 999, background: stateIsSuccess ? "#22c55e" : "#38bdf8", transition: "width 250ms ease" }} />
            </Box>
          )}
          <UpdateStepTimeline steps={CLIENTFLOW_DEPLOYMENT_STEPS} currentIndex={meta.index} terminal={stateIsSuccess} error={stateIsError} />
          {(requestedAt || updatedAt || finishedAt) && (
            <Stack direction="row" spacing={1.25} useFlexGap sx={{ flexWrap: "wrap", mt: 0.75 }}>
              {requestedAt && <Typography variant="caption" sx={{ color: MUTED }}>Bestilt: {requestedAt}</Typography>}
              {updatedAt && <Typography variant="caption" sx={{ color: MUTED }}>State ændret: {updatedAt}</Typography>}
              {finishedAt && <Typography variant="caption" sx={{ color: MUTED }}>Afsluttet: {finishedAt}</Typography>}
            </Stack>
          )}
          {error && <Typography variant="body2" sx={{ mt: 0.75, color: "#f87171", fontWeight: 700 }}>Fejl: {error}</Typography>}
        </Box>
      )}
      <Dialog open={downgradeDialogOpen} onClose={() => setDowngradeDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Bekræft ClientFlow-nedgradering</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            Du er ved at ændre ClientFlow fra {installedVersion ? `v${installedVersion}` : "en ukendt version"} til v{resolvedSelectedVersion}. Nedgraderingen logges som en kritisk administratorhandling.
          </Alert>
          <TextField autoFocus fullWidth multiline minRows={3} label="Begrundelse" value={downgradeReason} onChange={(event) => setDowngradeReason(event.target.value)} helperText={`${downgradeReason.trim().length}/500 · obligatorisk`} slotProps={{ htmlInput: { maxLength: 500 } }} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDowngradeDialogOpen(false)}>Annuller</Button>
          <Button color="warning" variant="contained" disabled={!downgradeReason.trim()} onClick={confirmClientFlowDowngrade}>Bekræft nedgradering</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}


const UBUNTU_STEP_PHASE_MAP = {
  os_update_requested: "requested",
  os_update_started: "starting",
  os_update_fetching: "checking",
  os_upgrading: "installing",
  os_update_installing: "installing",
  os_cleanup: "cleanup",
  os_update_cleanup: "cleanup",
  os_rebooting: "rebooting",
  os_update_complete: "success",
  os_update_none: "up_to_date",
  os_update_failed: "error",
  os_update_reset: "ready",
};

const UBUNTU_REPORTED_STATUS_MAP = {
  ready: "ready",
  running: "installing",
  starting: "starting",
  checking: "checking",
  installing: "installing",
  cleanup: "cleanup",
  rebooting: "rebooting",
  success: "success",
  completed: "success",
  complete: "success",
  up_to_date: "up_to_date",
  error: "error",
};

const UBUNTU_PHASE_LABELS = {
  ready: "Klar",
  updates_available: "Pakker klar",
  requested: "Afventer klient",
  starting: "Starter",
  checking: "Henter pakkeliste",
  installing: "Installerer pakker",
  cleanup: "Rydder op",
  success: "Opdateret",
  up_to_date: "Allerede opdateret",
  error: "Fejl",
};

function getUbuntuStep(client) {
  return String(
    client?.ubuntu_update_step ||
    client?.os_update_step ||
    ""
  ).trim().toLowerCase();
}

function getUbuntuStepPhase(client) {
  return UBUNTU_STEP_PHASE_MAP[getUbuntuStep(client)] || null;
}

function getUbuntuHumanMessage(client, localStatus = {}) {
  if (localStatus.error) return localStatus.error;
  if (localStatus.message) return localStatus.message;

  const candidates = [
    client?.os_update_message,
    client?.ubuntu_update_message,
  ];

  for (const value of candidates) {
    const text = String(value ?? "").trim();
    if (!text) continue;
    // Undgå at vise rå step-navne som brugerbesked.
    if (/^os_update_|^os_upgrading$|^os_cleanup$/i.test(text)) continue;
    return text;
  }

  return "";
}

function getUbuntuSearchText(client) {
  return [
    client?.os_update_status,
    client?.ubuntu_update_status,
    client?.last_os_update_status,
  ]
    .map((value) => String(value ?? "").trim())
    .filter(Boolean)
    .join(" · ")
    .toLowerCase();
}

function normalizeUbuntuPhase(client, localStatus = {}) {
  if (localStatus.error) return "error";

  const reportedStatus = String(client?.ubuntu_update_status || client?.os_update_status || "").trim().toLowerCase();
  const reportedPhase = UBUNTU_REPORTED_STATUS_MAP[reportedStatus] || null;
  const step = getUbuntuStep(client);
  const stepPhase = UBUNTU_STEP_PHASE_MAP[step] || null;
  const text = getUbuntuSearchText(client);
  const pendingOsUpdate = client?.pending_os_update === true;
  const pendingReboot = client?.pending_reboot === true;
  const count = getUbuntuUpdateCount(client);

  // Canonical System command projection owns completion. Service-unit telemetry
  // remains diagnostics only and must never decide whether the action is busy.
  const completedWithoutPending = !pendingOsUpdate && !pendingReboot &&
    ["success", "up_to_date", "error", "ready"].includes(reportedStatus);
  if (completedWithoutPending && (stepPhase === "rebooting" || UBUNTU_UPDATE_BUSY_STEPS.has(stepPhase))) {
    if (text.includes("fejl") || text.includes("failed") || text.includes("error")) return "error";
    if (text.includes("ingen opdateringer") || text.includes("up to date") || text.includes("allerede opdateret")) return "up_to_date";
    return "success";
  }

  if (reportedPhase) {
    if (reportedPhase === "ready" && count === 0 && completedWithoutPending && sawUpdateCompletionText(text)) return "success";
    if (reportedPhase !== "ready") return reportedPhase;
  }

  if (stepPhase) return stepPhase;

  if (
    text.includes("fejl") ||
    text.includes("failed") ||
    text.includes("error") ||
    text.includes("exitkode") ||
    text.includes("exit code")
  ) {
    return "error";
  }

  if (sawUpdateCompletionText(text)) {
    return "success";
  }

  if (text.includes("ingen opdateringer") || text.includes("up to date") || text.includes("allerede opdateret")) {
    return "up_to_date";
  }

  if (text.includes("rydder op") || text.includes("cleanup") || text.includes("os_cleanup")) {
    return "cleanup";
  }

  if (
    text.includes("installerer") ||
    text.includes("installing") ||
    text.includes("opgraderer") ||
    text.includes("upgrading") ||
    text.includes("os_upgrading")
  ) {
    return "installing";
  }

  if (
    text.includes("henter pakkeliste") ||
    text.includes("pakkeliste") ||
    text.includes("apt update") ||
    text.includes("package list")
  ) {
    return "checking";
  }

  if (pendingOsUpdate) {
    if (UBUNTU_UPDATE_BUSY_STEPS.has(localStatus.phase)) return localStatus.phase;
    return "requested";
  }

  // Hvis frontend selv tidligere så et busy-step, men klienten nu er idle/Klar,
  // afsluttes visningen i stedet for at hænge på sidste lokale step.
  if (UBUNTU_UPDATE_BUSY_STEPS.has(localStatus.phase)) {
    if (completedWithoutPending) {
      if (count === 0) return "success";
      return "success";
    }
    return localStatus.phase;
  }

  if (["success", "up_to_date", "error"].includes(localStatus.phase)) return localStatus.phase;

  if (count === 0) return "up_to_date";
  if (count > 0) return "updates_available";
  return "ready";
}

function sawUpdateCompletionText(text) {
  const value = String(text || "").toLowerCase();
  return (
    value.includes("opdatering gennemført") ||
    value.includes("gennemført") ||
    value.includes("completed") ||
    value.includes("complete") ||
    value.includes("ingen genstart nødvendig")
  );
}

function getUbuntuUpdateStepMeta(phase, updateCount = null) {
  const st = String(phase || "ready").trim().toLowerCase();

  if (st === "ready") {
    return { label: "Klar", description: "Klienten er klar til Ubuntu-tjek.", index: -1, progress: 0 };
  }

  if (st === "updates_available") {
    return {
      label: "Pakker klar",
      description: updateCount > 0 ? `${updateCount} pakke(r) kan installeres.` : "Der er Ubuntu-pakker klar.",
      index: -1,
      progress: 0,
    };
  }

  if (st === "success") {
    return { label: "Opdateret", description: "Ubuntu-opdateringen er gennemført.", index: UBUNTU_UPDATE_STEPS.length, progress: 100 };
  }

  if (st === "up_to_date") {
    return { label: "Allerede opdateret", description: "Klienten har ingen Ubuntu-pakker klar.", index: UBUNTU_UPDATE_STEPS.length, progress: 100 };
  }

  if (st === "error") {
    return { label: "Fejl", description: "Ubuntu-opdateringen fejlede.", index: -1, progress: 100 };
  }

  const index = UBUNTU_UPDATE_STEPS.findIndex((step) => step.key === st);
  if (index >= 0) {
    const step = UBUNTU_UPDATE_STEPS[index];
    return { ...step, index };
  }

  return { label: UBUNTU_PHASE_LABELS[st] || st || "Ukendt", description: "Ukendt Ubuntu-opdateringsstatus.", index: -1, progress: 0 };
}

function getUbuntuPhaseTimestamp(client) {
  return (
    client?.os_update_updated_at ||
    client?.ubuntu_update_updated_at ||
    client?.chrome_last_updated ||
    client?.last_chrome_updated ||
    null
  );
}

function UbuntuUpdateControl({ client, clientOnline, showSnackbar, onStarted }) {
  const [starting, setStarting] = React.useState(false);
  const [localStatus, setLocalStatus] = React.useState({
    phase: null,
    message: "",
    error: "",
    requestedAt: null,
    startedAt: null,
    finishedAt: null,
  });
  const [feedbackVisible, setFeedbackVisible] = React.useState(false);
  const [polling, setPolling] = React.useState(false);
  const [sawBusyState, setSawBusyState] = React.useState(false);
  const requestStartedAtRef = React.useRef(null);

  const updateCount = getUbuntuUpdateCount(client);
  const phase = normalizeUbuntuPhase(client, localStatus);
  const meta = getUbuntuUpdateStepMeta(phase, updateCount);
  const inProgress = UBUNTU_UPDATE_BUSY_STEPS.has(phase) || !!client?.pending_os_update || starting;
  const otherUpdateInProgress =
    !inProgress &&
    String(client?.state || "").trim().toLowerCase() === "updating";
  const finished = phase === "success" || phase === "up_to_date" || phase === "error";
  const ubuntuVersion = client?.ubuntu_version || "ukendt";
  const message = getUbuntuHumanMessage(client, localStatus);
  const error = localStatus.error || (phase === "error" ? message : "");

  const requestedAt = formatUpdateDateTime(localStatus.requestedAt);
  const startedAt = formatUpdateDateTime(localStatus.startedAt);
  const finishedAt = formatUpdateDateTime(localStatus.finishedAt);

  const showPanel = inProgress || starting || polling || feedbackVisible;

  const statusText = starting
    ? "Sender forespørgsel"
    : phase === "up_to_date"
    ? "Opdateret til seneste pakker"
    : phase === "success"
    ? "Seneste opdatering gennemført"
    : phase === "error"
    ? "Seneste opdatering fejlede"
    : phase === "updates_available"
    ? `${updateCount} pakke(r) klar`
    : inProgress
    ? meta.label
    : otherUpdateInProgress
    ? "Afventer anden opdatering"
    : "Klar til tjek";

  const statusColor = phase === "error"
    ? "#f87171"
    : phase === "success" || phase === "up_to_date"
    ? "#22c55e"
    : phase === "updates_available"
    ? "#fbbf24"
    : inProgress
    ? "#38bdf8"
    : otherUpdateInProgress
    ? "#fbbf24"
    : MUTED;

  React.useEffect(() => {
    const stepPhase = getUbuntuStepPhase(client);
    const timestamp = getUbuntuPhaseTimestamp(client) || new Date().toISOString();

    if (stepPhase && UBUNTU_UPDATE_BUSY_STEPS.has(stepPhase)) {
      setSawBusyState(true);
      setFeedbackVisible(true);
      setPolling(true);
      setLocalStatus((prev) => ({
        ...prev,
        phase: stepPhase,
        error: "",
        requestedAt: prev.requestedAt || requestStartedAtRef.current || timestamp,
        startedAt: prev.startedAt || (stepPhase !== "requested" ? timestamp : null),
        message: getUbuntuHumanMessage(client, prev) || prev.message,
      }));
      return;
    }

    if (stepPhase && ["success", "up_to_date", "error"].includes(stepPhase)) {
      const shouldShowTerminalFeedback =
        polling ||
        sawBusyState ||
        Boolean(requestStartedAtRef.current) ||
        client?.pending_os_update === true;

      setLocalStatus((prev) => ({
        ...prev,
        phase: stepPhase,
        requestedAt: prev.requestedAt || requestStartedAtRef.current || (shouldShowTerminalFeedback ? timestamp : null),
        startedAt: prev.startedAt || (shouldShowTerminalFeedback ? timestamp : null),
        finishedAt: prev.finishedAt || (shouldShowTerminalFeedback ? timestamp : null),
        error: stepPhase === "error" ? (getUbuntuHumanMessage(client, prev) || "Ubuntu-opdateringen fejlede") : "",
        message: shouldShowTerminalFeedback ? (getUbuntuHumanMessage(client, prev) || prev.message) : prev.message,
      }));
      setFeedbackVisible(shouldShowTerminalFeedback);
      setPolling(false);
      setSawBusyState(false);
      return;
    }

    if (client?.pending_os_update) {
      setSawBusyState(true);
      setFeedbackVisible(true);
      setPolling(true);
      setLocalStatus((prev) => ({
        ...prev,
        phase: UBUNTU_UPDATE_BUSY_STEPS.has(prev.phase) ? prev.phase : "requested",
        requestedAt: prev.requestedAt || requestStartedAtRef.current || timestamp,
        error: "",
      }));
    }
  }, [client, polling, sawBusyState]);

  React.useEffect(() => {
    if (!polling || typeof onStarted !== "function") return undefined;

    const timer = window.setInterval(async () => {
      try {
        await onStarted({ optimistic: false });
      } catch {
        // Ignorer refresh-fejl mens vi venter på klientstatus.
      }

      const startedAtMs = requestStartedAtRef.current ? new Date(requestStartedAtRef.current).getTime() : Date.now();
      const waitedMs = Date.now() - startedAtMs;

      if (!inProgress && sawBusyState) {
        const terminalPhase = ["success", "up_to_date", "error"].includes(phase) ? phase : "success";
        setLocalStatus((prev) => ({
          ...prev,
          phase: terminalPhase,
          finishedAt: prev.finishedAt || new Date().toISOString(),
        }));
        setFeedbackVisible(true);
        setPolling(false);
        setSawBusyState(false);
        return;
      }

      if (!inProgress && !sawBusyState && waitedMs > UBUNTU_REQUEST_WAIT_TIMEOUT_MS) {
        setLocalStatus((prev) => ({
          ...prev,
          phase: "error",
          error: "Ubuntu-opdateringen svarede ikke inden for timeout. Brug remote terminal eller reset Ubuntu-update-status.",
          finishedAt: new Date().toISOString(),
        }));
        setFeedbackVisible(true);
        setPolling(false);
      }
    }, UBUNTU_POLL_MS);

    return () => window.clearInterval(timer);
  }, [polling, inProgress, sawBusyState, phase, onStarted]);

  React.useEffect(() => {
    if (!feedbackVisible || inProgress || starting || polling) return undefined;
    const timer = window.setTimeout(() => {
      setFeedbackVisible(false);
      if (phase !== "error") {
        requestStartedAtRef.current = null;
        setLocalStatus((prev) => ({
          ...prev,
          phase: null,
          message: "",
          error: "",
          requestedAt: null,
          startedAt: null,
          finishedAt: null,
        }));
      }
    }, UBUNTU_FINISHED_FEEDBACK_MS);
    return () => window.clearTimeout(timer);
  }, [feedbackVisible, inProgress, starting, polling, phase]);

  const startUbuntuUpdate = async (event) => {
    event?.preventDefault?.();
    event?.stopPropagation?.();
    if (!client?.id || clientOnline !== true || starting || inProgress || otherUpdateInProgress) return;

    const now = new Date().toISOString();
    setStarting(true);
    setLocalStatus({
      phase: "requested",
      message: "Ubuntu-opdatering er sendt til klienten",
      error: "",
      requestedAt: now,
      startedAt: null,
      finishedAt: null,
    });
    setFeedbackVisible(true);
    setPolling(true);
    setSawBusyState(false);
    requestStartedAtRef.current = now;

    try {
      const res = await requestOsUpdate(client.id);
      const responseMessage = res?.message || res?.detail || "Ubuntu-opdatering er sendt til klienten";
      setLocalStatus((prev) => ({
        ...prev,
        phase: "requested",
        message: responseMessage,
        requestedAt: prev.requestedAt || now,
      }));
      showSnackbar?.({ message: responseMessage, severity: "success" });
      await onStarted?.({ optimistic: true });
    } catch (err) {
      const errMessage = err?.message || "Kunne ikke starte Ubuntu-opdatering";
      setLocalStatus((prev) => ({
        ...prev,
        phase: "error",
        error: errMessage,
        message: errMessage,
        finishedAt: new Date().toISOString(),
      }));
      setFeedbackVisible(true);
      setPolling(false);
      showSnackbar?.({ message: `Fejl: ${errMessage}`, severity: "error" });
    } finally {
      setStarting(false);
    }
  };

  const disabled = !client?.id || clientOnline !== true || starting || inProgress || otherUpdateInProgress;

  return (
    <Box sx={{ p: 1.15, borderRadius: 2, background: FIELD_BG, border: `1px solid ${BORDER}` }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={1}
        sx={{
          alignItems: { xs: "stretch", sm: "center" },
          justifyContent: "space-between"
        }}>
        <Box sx={{
          minWidth: 0
        }}>
          <Typography variant="subtitle2" sx={{ color: TEXT, fontWeight: 950 }}>
            Ubuntu-opdatering
          </Typography>
          <Stack
            direction="row"
            spacing={1}
            useFlexGap
            sx={{
              flexWrap: "wrap",
              mt: 0.45
            }}>
            <Typography variant="caption" sx={{ color: MUTED }}>
              Version: {ubuntuVersion}
            </Typography>
            {updateCount !== null && (
              <Typography variant="caption" sx={{ color: MUTED }}>
                Pakker: {updateCount}
              </Typography>
            )}
            <Typography variant="caption" sx={{ color: statusColor, fontWeight: 850 }}>
              {statusText}
            </Typography>
          </Stack>
        </Box>
        <Button
          size="small"
          variant="outlined"
          color="warning"
          startIcon={starting || inProgress ? <CircularProgress size={16} color="inherit" /> : <SystemUpdateAltIcon />}
          disabled={disabled}
          type="button"
          onClick={startUbuntuUpdate}
          sx={{ borderRadius: 2, fontWeight: 850, whiteSpace: "nowrap" }}
        >
          {starting || inProgress ? "Opdaterer Ubuntu…" : "Installer Ubuntu-opdateringer"}
        </Button>
      </Stack>
      {showPanel && (
        <Box
          sx={{
            mt: 1,
            p: 1,
            borderRadius: 2,
            background: phase === "error" ? "rgba(248,113,113,0.10)" : "rgba(56,189,248,0.10)",
            border: phase === "error" ? "1px solid rgba(248,113,113,0.28)" : "1px solid rgba(56,189,248,0.24)",
          }}
        >
          <Stack
            direction="row"
            spacing={1}
            useFlexGap
            sx={{
              alignItems: "center",
              justifyContent: "space-between",
              flexWrap: "wrap"
            }}>
            <Stack spacing={0.15} sx={{
              minWidth: 0
            }}>
              <Typography variant="caption" sx={{ color: MUTED, fontWeight: 850, textTransform: "uppercase", letterSpacing: 0.6 }}>
                Detaljeret procesforløb
              </Typography>
              <Stack
                direction="row"
                spacing={1}
                sx={{
                  alignItems: "center",
                  minWidth: 0
                }}>
                {(starting || UBUNTU_UPDATE_BUSY_STEPS.has(phase)) && <CircularProgress size={15} sx={{ color: "#7dd3fc" }} />}
                <Typography variant="body2" sx={{ color: TEXT, fontWeight: 900 }}>
                  {meta.label}{ubuntuVersion ? ` · ${ubuntuVersion}` : ""}
                </Typography>
              </Stack>
            </Stack>
            {UBUNTU_UPDATE_BUSY_STEPS.has(phase) && (
              <Typography variant="caption" sx={{ color: MUTED }}>
                Trin {Math.max(meta.index + 1, 1)} / {UBUNTU_UPDATE_STEPS.length}
              </Typography>
            )}
          </Stack>

          <Typography variant="body2" sx={{ mt: 0.5, color: phase === "error" ? "#fca5a5" : MUTED }}>
            {error || message || (starting ? "Sender Ubuntu-kontrol til backend og afventer status…" : meta.description)}
          </Typography>

          {(UBUNTU_UPDATE_BUSY_STEPS.has(phase) || phase === "success" || phase === "up_to_date") && (
            <Box sx={{ mt: 1, height: 6, borderRadius: 999, background: "rgba(15,23,42,0.75)", overflow: "hidden" }}>
              <Box
                sx={{
                  height: "100%",
                  width: `${Math.max(6, Math.min(100, meta.progress || 6))}%`,
                  borderRadius: 999,
                  background: phase === "success" || phase === "up_to_date" ? "#22c55e" : "#38bdf8",
                  transition: "width 250ms ease",
                }}
              />
            </Box>
          )}

          <UpdateStepTimeline
            steps={UBUNTU_UPDATE_STEPS}
            currentIndex={meta.index}
            terminal={phase === "success" || phase === "up_to_date"}
            error={phase === "error"}
          />

          {(requestedAt || startedAt || finishedAt) && (
            <Stack
              direction="row"
              spacing={1.25}
              useFlexGap
              sx={{
                flexWrap: "wrap",
                mt: 0.75
              }}>
              {requestedAt && <Typography variant="caption" sx={{ color: MUTED }}>Bestilt: {requestedAt}</Typography>}
              {startedAt && <Typography variant="caption" sx={{ color: MUTED }}>Startet: {startedAt}</Typography>}
              {finishedAt && <Typography variant="caption" sx={{ color: MUTED }}>Færdig: {finishedAt}</Typography>}
            </Stack>
          )}

          {(error || phase === "error") && (
            <Typography variant="body2" sx={{ mt: 0.75, color: "#f87171", fontWeight: 700 }}>
              Fejl: {error || message || "Klienten rapporterede en fejl under Ubuntu-opdateringen."}
            </Typography>
          )}
        </Box>
      )}
    </Box>
  );
}

function normalize(value) {
  return String(value ?? "").trim();
}

function normalizeNetworkStatus(value) {
  return String(value || "").trim().toLowerCase();
}

function networkStatusLevel(client) {
  const status = normalizeNetworkStatus(client?.network_status);
  if (client?.network_has_connection === false || ["no_network", "disconnected", "missing"].includes(status)) return "error";
  if (status === "ok" || client?.network_has_connection === true) return "ok";
  return "warn";
}

function networkStatusMessage(client) {
  if (client?.network_status_message) return client.network_status_message;
  const type = normalize(client?.active_network_type);
  const ip = normalize(client?.active_network_ip || client?.wifi_ip_address || client?.lan_ip_address);
  if (type || ip) return `Seneste netværksdiagnostik${type ? `: ${type}` : ""}${ip ? ` · ${ip}` : ""}`;
  return "Netværksdiagnostik ukendt";
}

function isNetworkUnavailable(client) {
  const status = normalizeNetworkStatus(client?.network_status);
  return client?.network_has_connection === false || ["no_network", "disconnected", "missing"].includes(status);
}

function formatDateTime(value, withSeconds = false) {
  if (!value) return "ukendt";
  const raw = String(value);
  const date = new Date(raw.endsWith("Z") || /[+-]\d{2}:?\d{2}$/.test(raw) ? raw : `${raw}Z`);
  if (Number.isNaN(date.getTime())) return "ukendt";

  return new Intl.DateTimeFormat("da-DK", {
    timeZone: "Europe/Copenhagen",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: withSeconds ? "2-digit" : undefined,
    hour12: false,
  }).format(date);
}

function formatUptime(value) {
  if (value === null || value === undefined || value === "") return "ukendt";
  const raw = String(value).trim();

  let totalSeconds = Number.parseInt(raw, 10);
  if (raw.includes(":")) {
    const parts = raw.split(":").map((part) => Number.parseInt(part, 10) || 0);
    if (parts.length === 3) totalSeconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
    if (parts.length === 2) totalSeconds = parts[0] * 60 + parts[1];
  }
  if (raw.includes("-") && raw.includes(":")) {
    const [days, hms] = raw.split("-");
    const [h = "0", m = "0", s = "0"] = hms.split(":");
    totalSeconds = (Number.parseInt(days, 10) || 0) * 86400 +
      (Number.parseInt(h, 10) || 0) * 3600 +
      (Number.parseInt(m, 10) || 0) * 60 +
      (Number.parseInt(s, 10) || 0);
  }

  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return raw || "ukendt";

  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const mins = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;

  if (days > 0) return `${days} d. ${hours} t. ${mins} min.`;
  if (hours > 0) return `${hours} t. ${mins} min.`;
  return `${mins} min. ${secs} sek.`;
}

function isCanonicalKioskUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return true;
  if (raw.length > 2048) return false;
  try {
    const parsed = new URL(raw);
    if (parsed.username || parsed.password || !parsed.hostname) return false;
    if (parsed.protocol === "https:") return true;
    return parsed.protocol === "http:" && ["localhost", "127.0.0.1"].includes(parsed.hostname.toLowerCase());
  } catch {
    return false;
  }
}


function normalizeLockdownStatus(value) {
  return String(value || "unknown").trim().toLowerCase();
}

function getKioskLockdownMeta(status, desiredEnabled) {
  const st = normalizeLockdownStatus(status);
  if (st === "applied" || st === "active") {
    return { label: "Aktiv", color: "success", description: "Kiosk-brugeren er låst. cfadmin, root og ClientFlow-services påvirkes ikke." };
  }
  if (st === "disabled" || st === "off") {
    return { label: "Slået fra", color: "default", description: "Kiosk lockdown er slået fra på klienten." };
  }
  if (st === "pending") {
    return { label: "Afventer klient", color: "warning", description: desiredEnabled ? "Backend afventer at klienten anvender kiosk lockdown." : "Backend afventer at klienten ruller kiosk lockdown tilbage." };
  }
  if (st === "applying") {
    return { label: "Anvender", color: "info", description: "Klienten er ved at låse kiosk-brugeren." };
  }
  if (st === "rolling_back" || st === "rollback") {
    return { label: "Ruller tilbage", color: "warning", description: "Klienten er ved at fjerne kiosk lockdown." };
  }
  if (st === "error" || st === "failed") {
    return { label: "Fejl", color: "error", description: "Klienten kunne ikke gennemføre kiosk lockdown. Brug cfadmin/administrator-terminal til fejlsøgning." };
  }
  return { label: desiredEnabled ? "Ukendt / ønsket til" : "Ukendt", color: "default", description: "Klienten har endnu ikke rapporteret en tydelig kiosk lockdown-status." };
}

function normalizeLocalManagementStatus(value) {
  return String(value || "ready").trim().toLowerCase();
}

function getLocalManagementMeta(status) {
  const st = normalizeLocalManagementStatus(status);
  if (st === "pending") return { label: "Afventer klient", color: "warning" };
  if (st === "running") return { label: "Udføres", color: "info" };
  if (st === "success") return { label: "Gennemført", color: "success" };
  if (st === "error") return { label: "Fejl", color: "error" };
  return { label: "Klar", color: "default" };
}

function pickLocalManagementFields(source = {}) {
  return {
    action: source?.local_management_action ?? source?.action ?? null,
    request_id: source?.local_management_request_id ?? source?.request_id ?? null,
    desired_hostname: source?.local_management_desired_hostname ?? source?.desired_hostname ?? null,
    status: source?.local_management_status ?? source?.status ?? "ready",
    message: source?.local_management_message ?? source?.message ?? null,
    requested_at: source?.local_management_requested_at ?? source?.requested_at ?? null,
    started_at: source?.local_management_started_at ?? source?.started_at ?? null,
    finished_at: source?.local_management_finished_at ?? source?.finished_at ?? null,
    error: source?.local_management_error ?? source?.error ?? null,
  };
}

function getLocalManagementActionLabel(action) {
  const a = String(action || "").trim().toLowerCase();
  if (a === "cfadmin_password") return "Skift cfadmin-adgangskode";
  if (a === "hostname") return "Skift klientnavn/hostname";
  return "Lokal klientstyring";
}

function getLocalManagementProgress(status) {
  const st = normalizeLocalManagementStatus(status);
  if (st === "pending") return 25;
  if (st === "running") return 65;
  if (st === "success") return 100;
  if (st === "error") return 100;
  return 0;
}

function buildLocalManagementFlow(snapshot = {}) {
  const status = normalizeLocalManagementStatus(snapshot.status);
  const actionLabel = getLocalManagementActionLabel(snapshot.action);
  const terminalError = status === "error";
  const terminalSuccess = status === "success";
  const running = status === "running" || terminalSuccess || terminalError;
  const finished = terminalSuccess || terminalError;
  return [
    { key: "queued", label: "Sendt fra backend", active: status === "pending", done: status === "pending" || running || finished },
    { key: "running", label: actionLabel, active: status === "running", done: running || finished },
    {
      key: "finished",
      label: terminalError ? "Fejl" : terminalSuccess ? "Gennemført" : "Afventer resultat",
      active: finished,
      done: finished,
      error: terminalError,
      success: terminalSuccess,
    },
  ];
}

function formatDateShort(date) {
  const dayName = UKEDAGE[date.getDay()];
  const day = String(date.getDate()).padStart(2, "0");
  const month = String(date.getMonth() + 1).padStart(2, "0");
  return `${dayName} ${day}.${month}`;
}

function startOfLocalDay(value) {
  const d = new Date(value);
  d.setHours(0, 0, 0, 0);
  return d;
}

function getLocalDateKey(date) {
  const d = startOfLocalDay(date);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function parseTimeMinutes(value) {
  const raw = String(value || "").trim();
  const match = raw.match(/^(\d{1,2})[:.](\d{2})/);
  if (!match) return null;
  const hours = Number.parseInt(match[1], 10);
  const minutes = Number.parseInt(match[2], 10);
  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) return null;
  if (hours < 0 || hours > 23 || minutes < 0 || minutes > 59) return null;
  return hours * 60 + minutes;
}

function getMinutesSinceMidnight(date) {
  return date.getHours() * 60 + date.getMinutes();
}

function formatTimeRange(entry) {
  if (!entry || entry.status !== "on") return "Ingen drift";
  return `${entry.powerOn || "?"}–${entry.powerOff || "?"}`;
}

function calendarEntryIsActive(data) {
  if (!data || typeof data !== "object") return false;
  const status = String(data.status ?? "").trim().toLowerCase();
  if (["off", "closed", "lukket", "slukket", "false", "0", "nej", "no"].includes(status)) return false;
  if (["on", "open", "active", "tændt", "true", "1", "ja", "yes"].includes(status)) return true;
  return Boolean(data.onTime || data.offTime);
}

function getStatusAndTimesFromRaw(markedDays, date) {
  const shortKey = getLocalDateKey(date);
  const candidates = [
    markedDays?.[shortKey],
    markedDays?.[`${shortKey}T00:00:00`],
    markedDays?.[`${shortKey}T00:00:00.000Z`],
    Object.entries(markedDays || {}).find(([key]) => String(key).startsWith(shortKey))?.[1],
  ];

  const data = candidates.find(Boolean);
  const active = calendarEntryIsActive(data);

  if (!active) {
    return { status: "off", powerOn: "", powerOff: "", dateKey: shortKey };
  }

  return {
    status: "on",
    powerOn: data?.onTime || "",
    powerOff: data?.offTime || "",
    dateKey: shortKey,
  };
}

function getTodayRuntimeMeta(entry, now = new Date()) {
  if (!entry || entry.status !== "on") {
    return { label: "Slukket", tone: "muted", detail: "Ingen drift i dag" };
  }

  const on = parseTimeMinutes(entry.powerOn);
  const off = parseTimeMinutes(entry.powerOff);
  const current = getMinutesSinceMidnight(now);
  const range = formatTimeRange(entry);

  if (on !== null && current < on) {
    return { label: "Planlagt", tone: "info", detail: `Starter ${entry.powerOn} · ${range}` };
  }

  if (off !== null && current > off) {
    return { label: "Afsluttet", tone: "muted", detail: `Sluttede ${entry.powerOff} · ${range}` };
  }

  return { label: "Aktiv nu", tone: "success", detail: range };
}

function getNextActiveSchedule(days, now = new Date()) {
  const current = getMinutesSinceMidnight(now);

  return days.find((day, index) => {
    if (day.status !== "on") return false;
    if (index !== 0) return true;
    const off = parseTimeMinutes(day.powerOff);
    return off === null || current <= off;
  }) || null;
}

function getNextScheduleLabel(next, days) {
  if (!next) return "Ikke planlagt";
  const index = days.findIndex((day) => day.dateKey === next.dateKey);
  const prefix = index === 0 ? "I dag" : formatDateShort(next.date);
  return `${prefix} ${formatTimeRange(next)}`;
}

function getUbuntuUpdateCount(client) {
  const count = Number.parseInt(String(client?.ubuntu_updates_available ?? ""), 10);
  return Number.isFinite(count) && count >= 0 ? count : null;
}

function formatUbuntuUpdates(client) {
  const count = getUbuntuUpdateCount(client);
  if (client?.pending_os_update) {
    return count && count > 0 ? `Opdatering i gang · ${count} pakke(r)` : "Opdatering i gang";
  }
  if (count === null) return "ukendt";
  return count === 0 ? "Ingen opdateringer" : `${count} pakke(r) klar`;
}

function getServiceStatusColor(value) {
  const s = String(value || "").trim().toLowerCase();
  if (["kører", "aktiv", "klar", "running", "active", "success"].includes(s)) return "#22c55e";
  if (["stop", "stoppet", "inactive", "idle"].includes(s)) return MUTED;
  if (["opdaterer", "starting", "requested", "preparing", "downloading", "installing", "starter"].includes(s)) return "#38bdf8";
  if (["fejl", "failed", "error", "mangler", "not-found"].includes(s)) return "#f87171";
  return "#fbbf24";
}

function useOrganizationsList(enabled) {
  const [organizations, setOrganizations] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (!enabled) return;
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await apiGetOrganizations();
        if (cancelled) return;
        if (Array.isArray(data)) setOrganizations(data);
        else if (Array.isArray(data?.organizations)) setOrganizations(data.organizations);
      } catch (err) {
        if (!cancelled) setError(err?.message || "Kunne ikke hente organisationer");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [enabled]);

  return { organizations, loading, error };
}

function CopyButton({ value }) {
  const [copied, setCopied] = React.useState(false);
  const disabled = value === null || value === undefined || value === "" || value === "ukendt";

  const handleCopy = async () => {
    if (disabled) return;
    try {
      await navigator.clipboard.writeText(String(value));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // ignore
    }
  };

  return (
    <Tooltip title={copied ? "Kopieret" : "Kopiér"}>
      <span>
        <IconButton size="small" onClick={handleCopy} disabled={disabled} sx={{ color: copied ? "#22c55e" : MUTED }}>
          <ContentCopyIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </span>
    </Tooltip>
  );
}

function DataPanel({ title, description, action, children, compactHeader = false }) {
  return (
    <Card
      elevation={0}
      sx={{
        height: "100%",
        borderRadius: 2,
        background: "rgba(15,23,42,0.46)",
        border: `1px solid ${BORDER}`,
        color: TEXT,
        boxShadow: "none",
      }}
    >
      <CardContent sx={{ p: { xs: 2.25, sm: 3.1 } }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={compactHeader ? 1.1 : 1.6}
          sx={{
            alignItems: { xs: "flex-start", sm: "center" },
            justifyContent: compactHeader ? "flex-start" : "space-between",
            mb: 2.15
          }}>
          <Box sx={{
            minWidth: 0
          }}>
            <Typography sx={{ fontWeight: 950, lineHeight: 1.12 }}>{title}</Typography>
            {description && <Typography variant="body2" sx={{ color: MUTED, mt: 0.2 }}>{description}</Typography>}
          </Box>
          {action && (
            <Box sx={{ flex: compactHeader ? "0 0 auto" : "0 0 auto", ml: compactHeader ? { xs: 0, sm: 0.25 } : 0 }}>
              {action}
            </Box>
          )}
        </Stack>
        {children}
      </CardContent>
    </Card>
  );
}

function InfoRow({ label, value, copy = false, color }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: { xs: "1fr", sm: "minmax(130px, 180px) 1fr auto" },
        alignItems: "center",
        gap: { xs: 0.45, sm: 1.15 },
        py: 1.18,
        borderTop: `1px solid ${BORDER}`,
        minWidth: 0,
      }}
    >
      <Typography variant="caption" sx={{ color: MUTED, fontWeight: 850, textTransform: "uppercase", letterSpacing: 0.35 }}>
        {label}
      </Typography>
      <Typography sx={{ color: color || TEXT, fontWeight: 650, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
        {value || "ukendt"}
      </Typography>
      {copy && <CopyButton value={value} />}
    </Box>
  );
}

function ScheduleStrip({ markedDays, onOpenCalendar, calendarLoading, clientId, onCalendarDaySaved, organizationTimes }) {
  const [now, setNow] = React.useState(() => new Date());

  React.useEffect(() => {
    setNow(new Date());
    const timer = window.setInterval(() => setNow(new Date()), 60_000);
    return () => window.clearInterval(timer);
  }, [markedDays, calendarLoading]);
  const days = React.useMemo(() => {
    const result = [];
    const base = startOfLocalDay(new Date());

    // Dag 0 bruges kun til det store "i dag"-kort.
    // De små kort starter i morgen, så kalenderen ikke viser i dag to gange.
    for (let i = 0; i < 7; i += 1) {
      const d = new Date(base);
      d.setDate(base.getDate() + i);
      const entry = getStatusAndTimesFromRaw(markedDays, d);
      result.push({ date: d, ...entry });
    }

    return result;
  }, [markedDays]);

  const [editDate, setEditDate] = React.useState(null);
  const [editDialogOpen, setEditDialogOpen] = React.useState(false);

  const today = days[0] || null;
  const upcomingDays = days.slice(1, 7);
  const todayMeta = getTodayRuntimeMeta(today, now);
  const scheduleWindow = [today, ...upcomingDays].filter(Boolean);
  const nextActive = getNextActiveSchedule(scheduleWindow, now);
  const activeDays = scheduleWindow.filter((day) => day.status === "on").length;
  const nextLabel = getNextScheduleLabel(nextActive, scheduleWindow);

  const openDayDialog = React.useCallback((day) => {
    if (!day?.date || !clientId) return;
    setEditDate(getLocalDateKey(day.date));
    setEditDialogOpen(true);
  }, [clientId]);

  const closeDayDialog = React.useCallback(() => {
    setEditDialogOpen(false);
  }, []);

  const handleDaySaved = React.useCallback((payload) => {
    if (typeof onCalendarDaySaved === "function") {
      onCalendarDaySaved(payload);
    }
  }, [onCalendarDaySaved]);

  const todayTone = todayMeta.tone === "success"
    ? { border: "rgba(34,197,94,0.38)", bg: "linear-gradient(160deg, rgba(34,197,94,0.22), rgba(15,23,42,0.52))", text: "#bbf7d0" }
    : todayMeta.tone === "info"
    ? { border: "rgba(56,189,248,0.34)", bg: "linear-gradient(160deg, rgba(56,189,248,0.18), rgba(15,23,42,0.52))", text: "#bae6fd" }
    : { border: BORDER, bg: "linear-gradient(160deg, rgba(100,116,139,0.18), rgba(15,23,42,0.52))", text: "#cbd5e1" };

  return (
    <DataPanel
      title="Kalender"
      compactHeader
      action={
        <Button
          size="small"
          variant="outlined"
          onClick={onOpenCalendar}
          endIcon={<OpenInNewIcon sx={{ fontSize: 16 }} />}
          sx={{ borderRadius: 999, color: TEXT, borderColor: BORDER, px: 1.3, minHeight: 30 }}
        >
          Åbn kalender
        </Button>
      }
    >
      {calendarLoading && <Alert severity="info" sx={{ mb: 1.5 }}>Henter kalender…</Alert>}
      <Grid container spacing={1.8} sx={{
        alignItems: "stretch"
      }}>
        <Grid
          size={{
            xs: 12,
            md: 4
          }}>
          <Box
            role={clientId ? "button" : undefined}
            tabIndex={clientId ? 0 : undefined}
            onClick={() => openDayDialog(today)}
            onKeyDown={(event) => {
              if (!clientId) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openDayDialog(today);
              }
            }}
            sx={{
              height: "100%",
              minHeight: 210,
              p: { xs: 2.45, sm: 2.85 },
              borderRadius: 2,
              background: todayTone.bg,
              border: `1px solid ${todayTone.border}`,
              display: "flex",
              flexDirection: "column",
              justifyContent: "space-between",
              gap: 2,
              cursor: clientId ? "pointer" : "default",
              transition: "transform 0.16s ease, border-color 0.16s ease, background 0.16s ease",
              "&:hover": clientId ? {
                transform: "translateY(-1px)",
                borderColor: "rgba(56,189,248,0.38)",
              } : undefined,
              "&:focus-visible": {
                outline: "2px solid rgba(56,189,248,0.75)",
                outlineOffset: 3,
              },
            }}
          >
            <Box>
              <Typography variant="caption" sx={{ color: "#7dd3fc", fontWeight: 950, textTransform: "uppercase", letterSpacing: 0.6 }}>
                I dag · {today ? formatDateShort(today.date) : ""}
              </Typography>
              <Typography variant="h5" sx={{ mt: 0.5, fontWeight: 950, color: todayTone.text }}>
                {todayMeta.label}
              </Typography>
              <Typography sx={{ mt: 0.35, color: MUTED, fontWeight: 760 }}>
                {todayMeta.detail}
              </Typography>
            </Box>

            <Stack spacing={0.75}>
              <Typography variant="caption" sx={{ color: MUTED }}>
                Planlagte dage næste 7 dage: <b>{activeDays}</b> / {scheduleWindow.length}
              </Typography>
              <Typography variant="caption" sx={{ color: MUTED }}>
                Næste drift: <b>{nextLabel}</b>
              </Typography>
            </Stack>
          </Box>
        </Grid>

        <Grid
          size={{
            xs: 12,
            md: 8
          }}>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "repeat(1, minmax(0, 1fr))",
                sm: "repeat(2, minmax(0, 1fr))",
                md: "repeat(3, minmax(0, 1fr))",
                xl: "repeat(6, minmax(0, 1fr))",
              },
              gap: 1.15,
            }}
          >
            {upcomingDays.map((day) => {
              const active = day.status === "on";
              const label = formatDateShort(day.date);
              const stateLabel = active ? "Tændt" : "Slukket";
              const valueLabel = active ? formatTimeRange(day) : "Ingen drift";
              const dotColor = active ? "#22c55e" : "#64748b";

              return (
                <Box key={day.dateKey}>
                  <Box
                    role={clientId ? "button" : undefined}
                    tabIndex={clientId ? 0 : undefined}
                    onClick={() => openDayDialog(day)}
                    onKeyDown={(event) => {
                      if (!clientId) return;
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        openDayDialog(day);
                      }
                    }}
                    sx={{
                      p: { xs: 1.85, sm: 2.05 },
                      borderRadius: 2,
                      border: `1px solid ${active ? "rgba(34,197,94,0.30)" : BORDER}`,
                      background: active ? "rgba(34,197,94,0.09)" : "rgba(15,23,42,0.42)",
                      minHeight: 132,
                      height: "100%",
                      display: "flex",
                      flexDirection: "column",
                      justifyContent: "space-between",
                      gap: 1.2,
                      cursor: clientId ? "pointer" : "default",
                      transition: "transform 0.16s ease, border-color 0.16s ease, background 0.16s ease",
                      "&:hover": clientId ? {
                        transform: "translateY(-1px)",
                        borderColor: active ? "rgba(34,197,94,0.48)" : "rgba(56,189,248,0.32)",
                        background: active ? "rgba(34,197,94,0.12)" : "rgba(15,23,42,0.56)",
                      } : undefined,
                      "&:focus-visible": {
                        outline: "2px solid rgba(56,189,248,0.75)",
                        outlineOffset: 3,
                      },
                    }}
                  >
                    <Stack
                      direction="row"
                      spacing={0.75}
                      sx={{
                        alignItems: "center",
                        justifyContent: "space-between"
                      }}>
                      <Typography variant="caption" sx={{ color: MUTED, fontWeight: 900, lineHeight: 1.15 }}>
                        {label}
                      </Typography>
                      <Box sx={{ width: 8, height: 8, borderRadius: "50%", bgcolor: dotColor, flex: "0 0 auto" }} />
                    </Stack>
                    <Box>
                      <Typography sx={{ fontWeight: 950, color: active ? "#bbf7d0" : MUTED, lineHeight: 1.15 }}>
                        {stateLabel}
                      </Typography>
                      <Typography variant="body2" sx={{ color: MUTED, mt: 0.35, lineHeight: 1.25 }}>
                        {valueLabel}
                      </Typography>
                    </Box>
                  </Box>
                </Box>
              );
            })}
          </Box>
        </Grid>
      </Grid>
      <DateTimeEditDialog
        open={editDialogOpen}
        onClose={closeDayDialog}
        date={editDate}
        clientId={clientId}
        onSaved={handleDaySaved}
        organizationTimes={organizationTimes}
      />
    </DataPanel>
  );
}

function SystemPanel({ client, uptime, lastSeen, clientOnline, showSnackbar, onUbuntuUpdateStarted, onDiagnosticsRefresh }) {
  return (
    <Grid container spacing={1.75}>
      <Grid
        size={{
          xs: 12,
          md: 5
        }}>
        <DataPanel title="Drift">
          <InfoRow label="Online" value={clientOnline === true ? "Ja" : "Nej"} color={clientOnline === true ? "#22c55e" : "#f87171"} />
          <InfoRow label="State" value={client?.state || "ukendt"} />
          <InfoRow label="Oppetid" value={formatUptime(uptime ?? client?.uptime)} />
          <InfoRow label="Sidst set" value={formatDateTime(lastSeen || client?.presence?.status?.reported_at, true)} />
          <InfoRow label="Tilføjet" value={formatDateTime(client?.created_at, true)} />
        </DataPanel>
      </Grid>
      <Grid
        size={{
          xs: 12,
          md: 7
        }}>
        <DataPanel
          title="Software"
          action={
            onDiagnosticsRefresh ? (
              <Tooltip title="Opdater data">
                <IconButton size="small" onClick={onDiagnosticsRefresh} sx={{ color: MUTED }}>
                  <RefreshIcon sx={{ fontSize: 18 }} />
                </IconButton>
              </Tooltip>
            ) : null
          }
        >
          <Stack spacing={1.1}>
            <ClientFlowUpdateControl
              clientId={client?.id}
              clientVersion={client?.client_version}
              pendingOsUpdate={client?.pending_os_update}
              showSnackbar={showSnackbar}
              onFinished={onDiagnosticsRefresh}
            />
            <UbuntuUpdateControl
              client={client}
              clientOnline={clientOnline}
              showSnackbar={showSnackbar}
              onStarted={onUbuntuUpdateStarted}
            />
          </Stack>
        </DataPanel>
      </Grid>
    </Grid>
  );
}

function NetworkPanel({ client }) {
  const level = networkStatusLevel(client);
  const message = networkStatusMessage(client);

  const activeRows = [
    ["Netværksstatus", message],
    ["Statuskode", client?.network_status || "unknown"],
    ["Aktiv forbindelse", client?.active_network_type],
    ["Aktiv IP", client?.active_network_ip],
    ["Aktivt interface", client?.active_network_interface],
    ["Aktiv MAC", client?.active_network_mac],
    ["Diagnostik opdateret", formatDateTime(client?.diagnostics_updated_at, true)],
  ];

  const adapterRows = [
    ["WLAN IP", client?.wifi_ip_address],
    ["WLAN MAC", client?.wifi_mac_address],
    ["LAN IP", client?.lan_ip_address],
    ["LAN MAC", client?.lan_mac_address],
  ];

  return (
    <Grid container spacing={1.75}>
      <Grid
        size={{
          xs: 12,
          md: 6
        }}>
        <DataPanel title="Aktiv forbindelse">
          {activeRows.map(([label, value]) => (
            <InfoRow key={label} label={label} value={normalize(value) || "ukendt"} copy={label.includes("IP") || label.includes("MAC") || label === "Aktivt interface"} />
          ))}
        </DataPanel>
      </Grid>
      <Grid
        size={{
          xs: 12,
          md: 6
        }}>
        <DataPanel title="Adaptere">
          {adapterRows.map(([label, value]) => (
            <InfoRow key={label} label={label} value={normalize(value) || "ukendt"} copy />
          ))}
        </DataPanel>
      </Grid>
    </Grid>
  );
}

function getOrganizationId(entity) {
  return entity?.organization_id ?? entity?.organizationId ?? "";
}

function getConfigFormFromClient(client) {
  return {
    name: client?.name || "",
    locality: client?.locality || "",
    kiosk_url: client?.kiosk_url || "",
    desktop_lockdown_enabled: client?.desktop_lockdown_enabled ? "true" : "false",
    organization_id: getOrganizationId(client) ? String(getOrganizationId(client)) : "",
  };
}

function ConfigurationPanel({ client, showSnackbar, onSaved, onRefresh, handleClientAction, clientOnline }) {
  const { user } = useAuth();
  const role = user?.role || "";
  const isSuperadmin = role === "superadmin";
  const isAdministrator = role === "admin";
  const isBruger = role === "bruger";
  const isViewer = role === "viewer";
  const canEditKioskUrlAndLocality = ["superadmin", "admin", "bruger"].includes(role);
  const canEditBrowserMaintenance = canEditKioskUrlAndLocality;
  const canEditClientName = isSuperadmin;
  const canChangeOrganization = isSuperadmin;
  const canViewSecuritySection = isSuperadmin || isViewer;
  const canViewLocalManagementSection = isSuperadmin || isViewer;
  const { organizations, loading, error } = useOrganizationsList(canChangeOrganization);

  const initialForm = React.useMemo(
    () => getConfigFormFromClient(client),
    [client]
  );
  const [form, setForm] = React.useState(initialForm);
  const [saving, setSaving] = React.useState(false);
  const [resetConfirmOpen, setResetConfirmOpen] = React.useState(false);
  const [resettingBrowser, setResettingBrowser] = React.useState(false);
  const [cfadminPassword, setCfadminPassword] = React.useState("");
  const [cfadminPasswordRepeat, setCfadminPasswordRepeat] = React.useState("");
  const [savingCfadminPassword, setSavingCfadminPassword] = React.useState(false);
  const [localManagementSnapshot, setLocalManagementSnapshot] = React.useState(() => pickLocalManagementFields(client));

  React.useEffect(() => {
    setLocalManagementSnapshot((prev) => ({ ...prev, ...pickLocalManagementFields(client) }));
  }, [client]);

  const refreshLocalManagement = React.useCallback(async () => {
    if (!client?.id) return null;
    const data = await apiGetClientLocalManagement(client.id);
    const next = pickLocalManagementFields(data);
    setLocalManagementSnapshot(next);
    return next;
  }, [client?.id]);

  React.useEffect(() => {
    const status = normalizeLocalManagementStatus(localManagementSnapshot.status);
    if (!client?.id || (status !== "pending" && status !== "running")) return undefined;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const next = await apiGetClientLocalManagement(client.id);
        if (!cancelled) setLocalManagementSnapshot(pickLocalManagementFields(next));
      } catch {
        // Silent polling-fejl må ikke støje i UI. Manuel Opdater kan stadig bruges.
      }
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [client?.id, localManagementSnapshot.status]);


  const rawFormDirty = React.useMemo(() => (
    form.name !== initialForm.name ||
    form.locality !== initialForm.locality ||
    form.kiosk_url !== initialForm.kiosk_url ||
    String(form.desktop_lockdown_enabled || "false") !== String(initialForm.desktop_lockdown_enabled || "false") ||
    String(form.organization_id || "") !== String(initialForm.organization_id || "")
  ), [form, initialForm]);

  // Silent refresh må gerne opdatere statusfelter i Konfiguration, men må ikke
  // overskrive en bruger, som er i gang med at redigere formularen.
  React.useEffect(() => {
    if (!rawFormDirty && !saving) {
      setForm(initialForm);
    }
  }, [initialForm, rawFormDirty, saving]);

  const setField = (field) => (event) => {
    setForm((prev) => ({ ...prev, [field]: event.target.value }));
  };

  const getChangedPayload = React.useCallback(() => {
    const payload = {};

    const nextLocality = String(form.locality || "").trim();
    const nextKioskUrl = String(form.kiosk_url || "").trim();

    if (canEditClientName) {
      const nextName = String(form.name || "").trim();
      if (nextName !== initialForm.name) {
        if (!nextName) throw new Error("Klientnavn må ikke være tomt");
        payload.name = nextName;
      }
    }

    if (canEditKioskUrlAndLocality) {
      if (nextLocality !== initialForm.locality) payload.locality = nextLocality;
      if (nextKioskUrl !== initialForm.kiosk_url) {
        if (!isCanonicalKioskUrl(nextKioskUrl)) {
          throw new Error("Kiosk URL skal bruge HTTPS. HTTP er kun tilladt til localhost eller 127.0.0.1.");
        }
        payload.kiosk_url = nextKioskUrl;
      }
    }


    if (canChangeOrganization && String(form.organization_id || "") !== String(initialForm.organization_id || "")) {
      const nextOrganizationId = form.organization_id || null;
      payload.organization_id = nextOrganizationId && /^\d+$/.test(String(nextOrganizationId))
        ? Number(nextOrganizationId)
        : nextOrganizationId;
    }


    return payload;
  }, [form, initialForm, canEditClientName, canEditKioskUrlAndLocality, canChangeOrganization, isSuperadmin]);

  const hasChanges = React.useMemo(() => {
    try {
      return Object.keys(getChangedPayload()).length > 0;
    } catch {
      return true;
    }
  }, [getChangedPayload]);

  const saveConfigPayload = async (payload, { applyOrganizationStandardTimes = true } = {}) => {
    if (!client?.id || saving) return;

    const { organization_id: nextOrganizationId, name: nextName, ...regularPayload } = payload;
    const organizationChanged = Object.prototype.hasOwnProperty.call(payload, "organization_id");
    const nameChanged = Object.prototype.hasOwnProperty.call(payload, "name");

    setSaving(true);
    try {
      if (nameChanged) {
        const response = await apiRequestLocalHostnameChange(client.id, nextName);
        setLocalManagementSnapshot(pickLocalManagementFields(response));
      }

      if (Object.keys(regularPayload).length > 0) {
        await apiUpdateClient(client.id, regularPayload);
      }

      if (organizationChanged) {
        await apiChangeClientOrganization(client.id, {
          organization_id: nextOrganizationId,
          apply_organization_standard_times: applyOrganizationStandardTimes,
          preserve_manual_times: true,
        });
      }

      const message = organizationChanged && applyOrganizationStandardTimes
        ? "Konfiguration gemt. Organisationens standardtider er anvendt på eksisterende tændte dage."
        : nameChanged
          ? "Konfiguration gemt. Lokalt klientnavn sendes til klienten."
          : "Konfiguration gemt";

      showSnackbar?.({ message, severity: "success" });
      await onSaved?.(organizationChanged ? { ...payload, organization_id: nextOrganizationId } : payload);
    } catch (err) {
      showSnackbar?.({ message: `Fejl: ${err?.message || "Kunne ikke gemme konfiguration"}`, severity: "error" });
    } finally {
      setSaving(false);
    }
  };

  const save = async () => {
    if (!client?.id || saving) return;
    let payload = {};
    try {
      payload = getChangedPayload();
    } catch (err) {
      showSnackbar?.({ message: `Fejl: ${err?.message || "Ugyldigt interval"}`, severity: "error" });
      return;
    }
    if (Object.keys(payload).length === 0) {
      showSnackbar?.({ message: "Ingen ændringer at gemme", severity: "info" });
      return;
    }

    const organizationChanged = Object.prototype.hasOwnProperty.call(payload, "organization_id");
    await saveConfigPayload(payload, { applyOrganizationStandardTimes: organizationChanged });
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    await save();
  };

  const canResetBrowser = canEditBrowserMaintenance && !!handleClientAction && clientOnline === true && !resettingBrowser;

  const openResetBrowserDialog = () => {
    if (typeof document !== "undefined" && document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
    setResetConfirmOpen(true);
  };

  const resetBrowser = async () => {
    if (!canResetBrowser) return;
    setResettingBrowser(true);
    try {
      setResetConfirmOpen(false);
      await handleClientAction("reset_browser");
      showSnackbar?.({ message: "Nulstilling af browser er sendt til klienten", severity: "success" });
    } catch (err) {
      showSnackbar?.({ message: `Fejl: ${err?.message || "Kunne ikke nulstille browser"}`, severity: "error" });
    } finally {
      setResettingBrowser(false);
    }
  };

  const saveCfadminPassword = async () => {
    if (!client?.id || savingCfadminPassword) return;
    if (!cfadminPassword) {
      showSnackbar?.({ message: "Indtast en ny cfadmin-adgangskode", severity: "warning" });
      return;
    }
    if (cfadminPassword !== cfadminPasswordRepeat) {
      showSnackbar?.({ message: "Adgangskoderne matcher ikke", severity: "warning" });
      return;
    }

    setSavingCfadminPassword(true);
    try {
      const response = await apiRequestCfadminPasswordChange(client.id, cfadminPassword);
      setLocalManagementSnapshot(pickLocalManagementFields(response));
      setCfadminPassword("");
      setCfadminPasswordRepeat("");
      showSnackbar?.({ message: "Ændring af cfadmin-adgangskode er sendt til klienten", severity: "success" });
      await onRefresh?.();
      try { await refreshLocalManagement(); } catch {}
    } catch (err) {
      showSnackbar?.({ message: `Fejl: ${err?.message || "Kunne ikke sende cfadmin-adgangskode"}`, severity: "error" });
    } finally {
      setSavingCfadminPassword(false);
    }
  };

  const refreshConfigNow = async () => {
    if (typeof onRefresh !== "function" || saving || hasChanges) return;
    try {
      await onRefresh();
    } catch {
      // Ignorer stille refresh-fejl. Manuel header-refresh kan stadig bruges.
    }
  };

  const resetForm = () => {
    setForm(initialForm);
  };

  const lockdownDesiredEnabled = String(form.desktop_lockdown_enabled || "false") === "true";
  const lockdownMeta = getKioskLockdownMeta(client?.desktop_lockdown_status, lockdownDesiredEnabled);
  const localManagementStatus = normalizeLocalManagementStatus(localManagementSnapshot.status);
  const localManagementMeta = getLocalManagementMeta(localManagementStatus);
  const localManagementActionLabel = getLocalManagementActionLabel(localManagementSnapshot.action);
  const localManagementMessage = localManagementSnapshot.message || localManagementSnapshot.error || "Ingen lokal klienthandling i gang";
  const localManagementBusy = localManagementStatus === "pending" || localManagementStatus === "running";
  const localManagementFlow = buildLocalManagementFlow(localManagementSnapshot);
  const localManagementProgress = getLocalManagementProgress(localManagementStatus);
  const cfadminPasswordsMismatch = !!cfadminPasswordRepeat && cfadminPassword !== cfadminPasswordRepeat;

  const textFieldSx = {
    "& .MuiInputBase-root": {
      color: TEXT,
      background: FIELD_BG,
      borderRadius: 2,
    },
    "& .MuiInputLabel-root": { color: MUTED },
    "& .MuiOutlinedInput-notchedOutline": { borderColor: BORDER },
    "&:hover .MuiOutlinedInput-notchedOutline": { borderColor: "rgba(125,211,252,0.42)" },
    "& .MuiSelect-icon": { color: MUTED },
  };

  return (
    <>
      <DataPanel
        title="Konfiguration"
        description="Stamdata, kioskvisning og lokale klientindstillinger samlet i færre sektioner."
        action={onRefresh ? (
          <Button
            size="small"
            variant="outlined"
            startIcon={<RefreshIcon />}
            onClick={refreshConfigNow}
            disabled={saving || hasChanges}
            sx={{ borderRadius: 999, color: TEXT, borderColor: BORDER }}
          >
            Opdater
          </Button>
        ) : null}
      >
        <Box component="form" onSubmit={handleSubmit}>
          {error && <Alert severity="warning" sx={{ mb: 1.5 }}>{error}</Alert>}

          <Stack spacing={1.6}>
            <Box sx={{ p: 1.35, borderRadius: 2, background: "rgba(15,23,42,0.28)", border: `1px solid ${BORDER}` }}>
              <Typography sx={{ color: TEXT, fontWeight: 950, mb: 0.35 }}>
                Stamdata
              </Typography>
              <Typography variant="caption" sx={{ color: MUTED, display: "block", mb: 1.25 }}>
                Klientnavnet gemmes i backend og lokalt på Ubuntu-klienten. Linux-hostname dannes automatisk uden mellemrum. Lokation er valgfri og kan beskrive placering hos kunden.
              </Typography>
              <Grid container spacing={1.25}>
                <Grid
                  size={{
                    xs: 12,
                    md: 6
                  }}>
                  <TextField
                    fullWidth
                    label="Klientnavn"
                    value={form.name}
                    onChange={setField("name")}
                    disabled={saving || !canEditClientName || localManagementBusy}
                    helperText={canEditClientName ? "Mellemrum er tilladt. Linux-hostname dannes automatisk og sendes som lokal klientstyring." : "Kun superadministrator kan ændre klientnavn"}
                    sx={textFieldSx}
                  />
                </Grid>
                <Grid
                  size={{
                    xs: 12,
                    md: 6
                  }}>
                  <TextField
                    fullWidth
                    label="Lokation"
                    value={form.locality}
                    onChange={setField("locality")}
                    disabled={saving || !canEditKioskUrlAndLocality}
                    helperText="Valgfri tekst, fx lokale, afdeling eller adresse."
                    sx={textFieldSx}
                  />
                </Grid>
                {canChangeOrganization && (
                  <Grid
                    size={{
                      xs: 12,
                      md: 6
                    }}>
                    <TextField
                      select
                      fullWidth
                      label="Organisation"
                      value={form.organization_id || ""}
                      onChange={setField("organization_id")}
                      disabled={loading || saving}
                      helperText="Flyt kun klienten, hvis den reelt hører til en anden organisation."
                      sx={textFieldSx}
                    >
                      <MenuItem value=""><em>Ingen organisation</em></MenuItem>
                      {loading && (
                        <MenuItem value="" disabled>Henter organisationer…</MenuItem>
                      )}
                      {organizations.map((organization) => (
                        <MenuItem key={organization.id} value={String(organization.id)}>{organization.name}</MenuItem>
                      ))}
                    </TextField>
                  </Grid>
                )}
              </Grid>
            </Box>

            <Box sx={{ p: 1.35, borderRadius: 2, background: "rgba(15,23,42,0.28)", border: `1px solid ${BORDER}` }}>
              <Typography sx={{ color: TEXT, fontWeight: 950, mb: 0.35 }}>
                Kioskvisning
              </Typography>
              <Typography variant="caption" sx={{ color: MUTED, display: "block", mb: 1.25 }}>
                Her styres den URL og browseradfærd, som infoskærmen viser.
              </Typography>
              <Grid container spacing={1.25}>
                <Grid size={12}>
                  <TextField
                    fullWidth
                    label="Kiosk URL"
                    value={form.kiosk_url}
                    onChange={setField("kiosk_url")}
                    disabled={saving || !canEditKioskUrlAndLocality}
                    helperText={canEditKioskUrlAndLocality ? "HTTPS kræves. HTTP er kun tilladt til localhost eller 127.0.0.1." : "Du har kun læseadgang til kiosk URL"}
                    sx={textFieldSx}
                  />
                </Grid>
                <Grid
                  size={{
                    xs: 12,
                    md: 6
                  }}>
                  <Box sx={{ height: "100%", p: 1.25, borderRadius: 2, background: FIELD_BG, border: `1px solid ${BORDER}` }}>
                    <Stack
                      direction={{ xs: "column", sm: "row" }}
                      spacing={1}
                      sx={{
                        alignItems: { xs: "stretch", sm: "center" },
                        justifyContent: "space-between"
                      }}>
                      <Box sx={{
                        minWidth: 0
                      }}>
                        <Typography variant="caption" sx={{ color: MUTED, fontWeight: 900, textTransform: "uppercase", letterSpacing: 0.45 }}>
                          Browser vedligeholdelse
                        </Typography>
                        <Typography variant="body2" sx={{ color: MUTED, mt: 0.25 }}>
                          Ryd profil, cookies og cache, når kiosksiden hænger eller login er gået i stykker.
                        </Typography>
                      </Box>
                      <Button
                        variant="outlined"
                        color="warning"
                        startIcon={resettingBrowser ? <CircularProgress size={16} color="inherit" /> : <DeleteSweepIcon />}
                        type="button"
                        onClick={openResetBrowserDialog}
                        disabled={!canResetBrowser}
                        sx={{ borderRadius: 2, fontWeight: 900, flexShrink: 0 }}
                      >
                        {resettingBrowser ? "Nulstiller…" : "Nulstil browser"}
                      </Button>
                    </Stack>
                    {!canResetBrowser && (
                      <Typography variant="caption" sx={{ display: "block", mt: 0.75, color: MUTED }}>
                        Kræver online klient og ingen anden aktiv handling.
                      </Typography>
                    )}
                  </Box>
                </Grid>
              </Grid>
            </Box>

            {canViewSecuritySection && (
            <Box sx={{ p: 1.35, borderRadius: 2, background: "rgba(15,23,42,0.28)", border: `1px solid ${BORDER}` }}>
              <Typography sx={{ color: TEXT, fontWeight: 950, mb: 0.35 }}>
                Sikkerhed på klienten
              </Typography>
              <Typography variant="caption" sx={{ color: MUTED, display: "block", mb: 1.25 }}>
                Indstillingerne her påvirker kun den lokale Ubuntu-klient. Kiosk-brugeren får ikke sudo/administrator-rettigheder.
              </Typography>
              <Grid container spacing={1.25}>
                <Grid
                  size={{
                    xs: 12,
                    md: 6
                  }}>
                  <TextField
                    select
                    fullWidth
                    label="Kiosk lockdown"
                    value={form.desktop_lockdown_enabled}
                    onChange={setField("desktop_lockdown_enabled")}
                    disabled
                    helperText="Canonical ClientFlow understøtter endnu ikke kiosk lockdown; kontrollen er fail-closed."
                    sx={textFieldSx}
                  >
                    <MenuItem value="true">Til</MenuItem>
                    <MenuItem value="false">Fra</MenuItem>
                  </TextField>
                </Grid>
                <Grid
                  size={{
                    xs: 12,
                    md: 6
                  }}>
                  <Box sx={{ height: "100%", p: 1.25, borderRadius: 2, background: FIELD_BG, border: `1px solid ${BORDER}` }}>
                    <Stack
                      direction="row"
                      spacing={1}
                      useFlexGap
                      sx={{
                        alignItems: "center",
                        flexWrap: "wrap"
                      }}>
                      <Chip
                        size="small"
                        label={lockdownMeta.label}
                        sx={compactDarkChipSx(lockdownMeta.color)}
                      />
                      <Typography variant="caption" sx={{ color: MUTED, fontWeight: 800 }}>
                        Ønske: {lockdownDesiredEnabled ? "Til" : "Fra"}
                      </Typography>
                    </Stack>
                    <Typography variant="caption" sx={{ color: MUTED, display: "block", mt: 0.75 }}>
                      {client?.desktop_lockdown_message || lockdownMeta.description}
                    </Typography>
                  </Box>
                </Grid>

                {isSuperadmin && (
                  <>
                    <Grid size={12}>
                      <Divider sx={{ borderColor: BORDER, my: 0.2 }} />
                      <Typography sx={{ color: TEXT, fontWeight: 950, mt: 0.4 }}>
                        Skift cfadmin-adgangskode
                      </Typography>
                    </Grid>
                    <Grid
                      size={{
                        xs: 12,
                        md: 5
                      }}>
                      <TextField
                        fullWidth
                        label="Ny cfadmin-adgangskode"
                        type="password"
                        value={cfadminPassword}
                        onChange={(event) => setCfadminPassword(event.target.value)}
                        disabled={savingCfadminPassword || localManagementBusy}
                        autoComplete="new-password"
                        helperText="Min. 8 tegn med stort bogstav, lille bogstav og tal"
                        sx={textFieldSx}
                      />
                    </Grid>
                    <Grid
                      size={{
                        xs: 12,
                        md: 5
                      }}>
                      <TextField
                        fullWidth
                        label="Gentag adgangskode"
                        type="password"
                        value={cfadminPasswordRepeat}
                        onChange={(event) => setCfadminPasswordRepeat(event.target.value)}
                        disabled={savingCfadminPassword || localManagementBusy}
                        error={cfadminPasswordsMismatch}
                        autoComplete="new-password"
                        helperText={cfadminPasswordsMismatch ? "Adgangskoderne matcher ikke" : " "}
                        sx={textFieldSx}
                      />
                    </Grid>
                    <Grid
                      sx={{ display: "flex", alignItems: "flex-start" }}
                      size={{
                        xs: 12,
                        md: 2
                      }}>
                      <Button
                        fullWidth
                        variant="contained"
                        type="button"
                        onClick={saveCfadminPassword}
                        disabled={savingCfadminPassword || localManagementBusy || !cfadminPassword || cfadminPasswordsMismatch}
                        startIcon={savingCfadminPassword ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
                        sx={{ borderRadius: 2, fontWeight: 900, minHeight: 54 }}
                      >
                        {savingCfadminPassword ? "Sender…" : "Skift"}
                      </Button>
                    </Grid>
                  </>
                )}
              </Grid>
            </Box>
            )}

            {canViewLocalManagementSection && (
            <Box sx={{ p: 1.25, borderRadius: 2, background: FIELD_BG, border: `1px solid ${BORDER}` }}>
              <Stack
                direction="row"
                spacing={1}
                useFlexGap
                sx={{
                  alignItems: "center",
                  justifyContent: "space-between",
                  flexWrap: "wrap"
                }}>
                <Box sx={{
                  minWidth: 0
                }}>
                  <Typography variant="caption" sx={{ color: MUTED, fontWeight: 900, textTransform: "uppercase", letterSpacing: 0.45 }}>
                    Seneste lokale klienthandling
                  </Typography>
                  <Typography sx={{ color: TEXT, fontWeight: 950, lineHeight: 1.2 }}>
                    {localManagementActionLabel}
                  </Typography>
                </Box>
                <Stack
                  direction="row"
                  spacing={1}
                  useFlexGap
                  sx={{
                    alignItems: "center",
                    flexWrap: "wrap"
                  }}>
                  <Chip
                    size="small"
                    label={localManagementMeta.label}
                    sx={compactDarkChipSx(localManagementMeta.color)}
                  />
                  {localManagementBusy && <CircularProgress size={18} />}
                  <Button
                    size="small"
                    type="button"
                    variant="outlined"
                    onClick={refreshLocalManagement}
                    disabled={!client?.id}
                    sx={{ borderRadius: 999, color: TEXT, borderColor: BORDER, fontWeight: 900 }}
                  >
                    Opdater status
                  </Button>
                </Stack>
              </Stack>

              {(localManagementBusy || localManagementStatus === "success" || localManagementStatus === "error") && (
                <Box sx={{ mt: 1.1 }}>
                  <LinearProgress
                    variant="determinate"
                    value={localManagementProgress}
                    color={localManagementStatus === "error" ? "error" : localManagementStatus === "success" ? "success" : "primary"}
                    sx={{ height: 8, borderRadius: 999, backgroundColor: "rgba(148,163,184,0.16)" }}
                  />
                  <Stack
                    direction={{ xs: "column", md: "row" }}
                    spacing={0.75}
                    useFlexGap
                    sx={{
                      flexWrap: "wrap",
                      mt: 1
                    }}>
                    {localManagementFlow.map((step, index) => (
                      <Box
                        key={step.key}
                        sx={{
                          flex: 1,
                          minWidth: 150,
                          p: 0.85,
                          borderRadius: 2,
                          border: `1px solid ${
                            step.error
                              ? "rgba(248,113,113,0.45)"
                              : step.success
                                ? "rgba(34,197,94,0.55)"
                                : step.active
                                  ? "rgba(56,189,248,0.42)"
                                  : step.done
                                    ? "rgba(34,197,94,0.35)"
                                    : BORDER
                          }`,
                          background: step.error
                            ? "rgba(127,29,29,0.24)"
                            : step.success
                              ? "rgba(22,101,52,0.24)"
                              : step.active
                                ? "rgba(14,165,233,0.18)"
                                : step.done
                                  ? "rgba(34,197,94,0.12)"
                                  : "rgba(15,23,42,0.34)",
                        }}
                      >
                        <Typography variant="caption" sx={{ color: MUTED, fontWeight: 900 }}>
                          {index + 1}. trin
                        </Typography>
                        <Typography sx={{ color: TEXT, fontWeight: 950, fontSize: 13 }}>
                          {step.label}
                        </Typography>
                      </Box>
                    ))}
                  </Stack>
                </Box>
              )}

              <Typography variant="caption" sx={{ color: MUTED, display: "block", mt: 0.9 }}>
                {localManagementMessage}
              </Typography>
              {localManagementSnapshot.desired_hostname && (
                <Typography variant="caption" sx={{ color: MUTED, display: "block", mt: 0.35 }}>
                  Nyt klientnavn/hostname: {localManagementSnapshot.desired_hostname}
                </Typography>
              )}
              {(localManagementSnapshot.requested_at || localManagementSnapshot.started_at || localManagementSnapshot.finished_at) && (
                <Typography variant="caption" sx={{ color: MUTED, display: "block", mt: 0.35 }}>
                  {localManagementSnapshot.requested_at ? `Sendt: ${formatDateTime(localManagementSnapshot.requested_at, true)}` : ""}
                  {localManagementSnapshot.started_at ? ` · Startet: ${formatDateTime(localManagementSnapshot.started_at, true)}` : ""}
                  {localManagementSnapshot.finished_at ? ` · Afsluttet: ${formatDateTime(localManagementSnapshot.finished_at, true)}` : ""}
                </Typography>
              )}
            </Box>
            )}

            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{
              alignItems: { xs: "stretch", sm: "center" }
            }}>
              <Button
                variant="contained"
                startIcon={saving ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
                type="submit"
                disabled={saving || !hasChanges}
                sx={{ borderRadius: 2, fontWeight: 900 }}
              >
                {saving ? "Gemmer…" : "Gem konfiguration"}
              </Button>
              {hasChanges && (
                <Button
                  variant="outlined"
                  type="button"
                  onClick={resetForm}
                  disabled={saving}
                  sx={{ borderRadius: 2, fontWeight: 900 }}
                >
                  Fortryd ændringer
                </Button>
              )}
            </Stack>
          </Stack>
        </Box>
      </DataPanel>
      <Dialog
        open={resetConfirmOpen}
        onClose={() => !resettingBrowser && setResetConfirmOpen(false)}
        maxWidth="xs"
        fullWidth
        disableRestoreFocus
      >
        <DialogTitle>Nulstil kiosk-browser?</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 1.5 }}>
            Chrome lukkes, browserprofil/cookies/cache ryddes, og kiosk-browseren startes igen efter countdown.
          </Alert>
          <Typography variant="body2" sx={{
            color: "text.secondary"
          }}>
            Brug handlingen når siden hænger, login/cookies er gået i stykker, eller browseren skal starte helt rent.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setResetConfirmOpen(false)} disabled={resettingBrowser}>Annullér</Button>
          <Button onClick={resetBrowser} color="warning" variant="contained" disabled={!canResetBrowser}>
            {resettingBrowser ? "Nulstiller…" : "Ja, nulstil browser"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}


function DiagnosticsPanel({ client, onRefresh }) {
  const hasDiagnosticValue = (value) => value !== null && value !== undefined && String(value).trim() !== "";

  const formatDiagnosticValue = (value, fallback = "ukendt") => {
    if (!hasDiagnosticValue(value)) return fallback;
    if (typeof value === "boolean") return value ? "Ja" : "Nej";
    if (Array.isArray(value)) return value.length ? value.join(", ") : fallback;
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  };

  const formatDiagnosticBoolean = (value, fallback = "ukendt") => {
    if (value === null || value === undefined || value === "") return fallback;
    return value ? "Ja" : "Nej";
  };

  const formatDiagnosticDate = (value) => hasDiagnosticValue(value) ? formatDateTime(value, true) : "ukendt";

  const formatResolution = (width, height) => (
    hasDiagnosticValue(width) && hasDiagnosticValue(height) ? `${width}×${height}` : "ukendt"
  );

  const formatRefreshRate = (value) => {
    if (!hasDiagnosticValue(value)) return "ukendt";
    const n = Number.parseFloat(String(value));
    return Number.isFinite(n) ? `${n.toFixed(2).replace(/\.00$/, "")} Hz` : String(value);
  };

  const formatClockDrift = (value) => {
    if (!hasDiagnosticValue(value)) return "ukendt";
    const seconds = Number.parseFloat(String(value));
    if (!Number.isFinite(seconds)) return String(value);
    return `${seconds.toFixed(seconds >= 10 ? 1 : 2).replace(/\.00$/, "")} sek.`;
  };

  const summarizeDetectedDisplays = (outputs) => {
    if (!Array.isArray(outputs) || outputs.length === 0) return "Ingen fundne outputs";
    return outputs
      .filter((output) => output && output.connected !== false)
      .slice(0, 4)
      .map((output) => {
        const name = output.output || output.name || "output";
        const mode = output.width && output.height ? `${output.width}×${output.height}` : "ukendt";
        const refresh = output.refresh_rate ? ` @ ${output.refresh_rate}Hz` : "";
        const modesCount = Array.isArray(output.modes) ? ` · ${output.modes.length} modes` : "";
        return `${name}: ${mode}${refresh}${modesCount}`;
      })
      .join(" | ") || "Ingen aktive outputs";
  };

  const formatUpdateCount = (value) => {
    const count = Number.parseInt(String(value ?? ""), 10);
    if (!Number.isFinite(count) || count < 0) return "ukendt";
    return count === 0 ? "Ingen" : `${count} pakke(r)`;
  };

  const levelColors = {
    ok: "#22c55e",
    info: "#38bdf8",
    warn: "#fbbf24",
    error: "#f87171",
    neutral: MUTED,
  };

  const levelBackgrounds = {
    ok: "rgba(34,197,94,0.10)",
    info: "rgba(56,189,248,0.10)",
    warn: "rgba(251,191,36,0.10)",
    error: "rgba(248,113,113,0.10)",
    neutral: "rgba(148,163,184,0.08)",
  };

  const normalizeText = (value) => String(value || "").trim().toLowerCase();
  const statusText = (value, fallback = "ukendt") => formatDiagnosticValue(value, fallback);
  const onlineValue = client?.presence?.is_online;
  const isOnline = onlineValue === true;
  const networkLevel = networkStatusLevel(client);
  const networkMessage = networkStatusMessage(client);
  const networkUnavailable = isNetworkUnavailable(client);
  const ubuntuUpdateCount = Number.parseInt(String(client?.ubuntu_updates_available ?? ""), 10);
  const hasUbuntuUpdates = Number.isFinite(ubuntuUpdateCount) && ubuntuUpdateCount > 0;
  const pendingChromeAction = normalizeText(client?.pending_chrome_action || "none");
  const hasPendingChromeAction = pendingChromeAction && pendingChromeAction !== "none";
  const livestreamStatus = normalizeText(client?.livestream_status || "idle");
  const livestreamExpectedRunning = ["running", "starting", "restarting"].includes(livestreamStatus);
  const timeSyncStatus = normalizeText(client?.time_sync_status || "unknown");
  const timeSyncLevel = timeSyncStatus === "ok" ? "ok" : timeSyncStatus === "warning" ? "warn" : timeSyncStatus === "critical" ? "error" : "neutral";
  const timeSyncMessage = statusText(client?.time_sync_message, "Tidsstatus er endnu ikke rapporteret");

  const getStatusLevel = (value) => {
    const s = normalizeText(value);
    if (!s) return "neutral";
    if (["kører", "aktiv", "klar", "running", "active", "success", "ready", "applied", "detected", "up_to_date", "normal", "approved", "ja", "ok"].includes(s)) return "ok";
    if (["warning", "advarsel"].includes(s)) return "warn";
    if (["critical", "kritisk"].includes(s)) return "error";
    if (["requested", "starting", "preparing", "fetching_manifest", "downloading", "verifying", "installing", "stopping_services", "pending", "applying", "opdaterer", "starter", "stopper", "rebooting", "shutdown", "shutting_down"].includes(s)) return "info";
    if (["none", "ingen", "nej", "false", "0", "idle", "inactive", "stoppet", "stop", "disabled"].includes(s)) return "neutral";
    if (["fejl", "failed", "error", "mangler", "not-found", "stale"].includes(s)) return "error";
    return "neutral";
  };

  const getBooleanLevel = (value, trueLevel = "warn", falseLevel = "ok") => (
    value === true ? trueLevel : value === false ? falseLevel : "neutral"
  );

  const getServiceLevel = (row) => {
    const s = normalizeText(row.value);
    if (!s) return row.required === false ? "neutral" : "warn";
    if (["fejl", "failed", "error"].includes(s)) return "error";
    if (["mangler", "not-found"].includes(s)) return row.required === false ? "neutral" : "error";
    if (["starter", "stopper", "activating", "deactivating", "opdaterer", "kører"].includes(s) && row.oneshot) return "info";
    if (["klar", "ready"].includes(s)) return "ok";
    if (["kører", "aktiv", "active", "running"].includes(s)) return "ok";
    if (["stop", "stoppet", "inactive", "idle"].includes(s)) {
      if (row.expectedStoppedOk) return "ok";
      if (row.required === false) return "neutral";
      return "error";
    }
    return getStatusLevel(row.value);
  };

  const getLivestreamServiceLevel = (value) => {
    const s = normalizeText(value);
    if (["fejl", "failed", "error", "mangler", "not-found"].includes(s)) return livestreamExpectedRunning ? "error" : "neutral";
    if (["kører", "aktiv", "active", "running"].includes(s)) return "ok";
    if (["starter", "stopper", "activating", "deactivating"].includes(s)) return "info";
    if (["stop", "stoppet", "inactive", "idle", "klar"].includes(s)) return livestreamExpectedRunning ? "error" : "ok";
    return livestreamExpectedRunning ? "warn" : "neutral";
  };

  const getRowLevel = (row) => {
    if (row.level) return row.level;
    if (row.service) return getServiceLevel(row);
    if (row.livestreamService) return getLivestreamServiceLevel(row.value);
    if (row.error) return hasDiagnosticValue(row.rawValue ?? row.value) ? "error" : "ok";
    if (row.boolean !== undefined) return getBooleanLevel(row.boolean, row.trueLevel || "warn", row.falseLevel || "ok");
    if (row.status) return getStatusLevel(row.rawValue ?? row.value);
    return "neutral";
  };

  const criticalServiceRows = [
    { label: "Backend sync", value: client?.service_clientflow_status, service: true, unit: "clientflow-status-agent.service" },
    { label: "Kalender", value: client?.service_calendar_status, service: true, unit: "clientflow-calendar.service" },
    { label: "Display runtime", value: client?.service_browser_guard_status, service: true, unit: "clientflow-display-runtime.service" },
    { label: "Terminal", value: client?.service_remote_terminal_status, service: true, unit: "clientflow-terminal-agent.service" },
    { label: "Administrator terminal", value: client?.service_admin_terminal_status, service: true, unit: "clientflow-root-terminal-broker.socket" },
    { label: "Fjernskrivebord", value: client?.service_remote_desktop_status, service: true, unit: "clientflow-remote-desktop-agent.service" },
  ];

  const supportServiceRows = [
    { label: "Livestream service", value: client?.service_livestream_status, livestreamService: true, unit: "clientflow-livestream-producer.service", helper: livestreamExpectedRunning ? "Skal køre når livestream er åbnet/ønsket" : "Må gerne være stoppet når livestream ikke bruges" },
    { label: "Livestream process", value: client?.livestream_process_status, livestreamService: true, unit: "gst-launch / livestream_wayland.py / uploader", helper: livestreamExpectedRunning ? "Skal være Aktiv når livestream_status=running" : "Må gerne være Stoppet når livestream er idle" },
    { label: "Ubuntu update", value: client?.service_ubuntu_update_status, service: true, oneshot: true, unit: "clientflow_ubuntu_update.service", helper: "Klar er normal idle-status" },
    { label: "Lifecycle reboot", value: client?.service_local_reboot_reporter_status, service: true, oneshot: true, unit: "clientflow_local_reboot_reporter.service", helper: "Klar er normal idle-status" },
    { label: "Lifecycle shutdown", value: client?.service_local_shutdown_reporter_status, service: true, oneshot: true, unit: "clientflow_local_shutdown_reporter.service", helper: "Klar er normal idle-status" },
  ];

  const serviceRows = [...criticalServiceRows, ...supportServiceRows];
  const serviceIssues = serviceRows.filter((row) => {
    const level = getRowLevel(row);
    return level === "warn" || level === "error";
  });

  const lifecycleLabelMap = {
    reboot_started: "Genstart startet",
    reboot_completed: "Genstart fuldført",
    shutdown_started: "Nedlukning startet",
    boot_detected: "Boot registreret",
    boot_after_shutdown: "Boot efter nedlukning",
  };
  const lifecycleEventLabel = lifecycleLabelMap[normalizeText(client?.last_power_event)] || statusText(client?.last_power_event, "Ingen");

  const attentionItems = [
    networkUnavailable ? { label: "Netværk mangler", level: "error", value: networkMessage } : null,
    serviceIssues.length > 0 ? { label: `${serviceIssues.length} systemd-status kræver tjek`, level: "error", value: serviceIssues.map((row) => row.label).join(", ") } : null,
    hasPendingChromeAction ? { label: "Pending browser-handling", level: "info", value: client?.pending_chrome_action } : null,
    client?.pending_reboot ? { label: "Pending reboot", level: "warn", value: "Ja" } : null,
    client?.pending_shutdown ? { label: "Pending shutdown", level: "warn", value: "Ja" } : null,
    client?.pending_os_update ? { label: "Ubuntu-opdatering venter", level: "info", value: "Ja" } : null,
    hasUbuntuUpdates ? { label: "Ubuntu-pakker klar", level: "warn", value: formatUpdateCount(client?.ubuntu_updates_available) } : null,
    hasDiagnosticValue(client?.livestream_last_error) ? { label: "Livestream-fejl", level: "error", value: client?.livestream_last_error } : null,
    hasDiagnosticValue(client?.display_resolution_error) ? { label: "Display-fejl", level: "error", value: client?.display_resolution_error } : null,
    timeSyncLevel === "error" ? { label: "Systemtid er kritisk", level: "error", value: timeSyncMessage } : null,
    timeSyncLevel === "warn" ? { label: "Systemtid kræver tjek", level: "warn", value: timeSyncMessage } : null,
  ].filter(Boolean);

  const criticalIssues = criticalServiceRows.filter((row) => ["warn", "error"].includes(getRowLevel(row)));
  const supportIssues = supportServiceRows.filter((row) => ["warn", "error"].includes(getRowLevel(row)));

  const serviceOkCount = serviceRows.length - serviceIssues.length;
  const serviceIssueText = serviceIssues.length ? serviceIssues.map((row) => row.label).join(", ") : "Alle overvågede services ser OK ud";
  const displaySummary = formatResolution(client?.display_resolution_current_width, client?.display_resolution_current_height);

  const summaryCards = [
    {
      label: "Klient",
      value: isOnline ? "Online" : "Offline",
      helper: `${statusText(client?.state)} · ${statusText(client?.client_version ? `v${String(client.client_version).replace(/^v/i, "")}` : "")}`,
      level: isOnline ? "ok" : "error",
    },
    {
      label: "Netværk",
      value: networkUnavailable ? "Mangler" : networkLevel === "ok" ? "OK" : "Ukendt",
      helper: networkMessage,
      level: networkLevel,
    },
    {
      label: "Services",
      value: `${serviceOkCount}/${serviceRows.length} OK`,
      helper: serviceIssueText,
      level: serviceIssues.length ? "error" : "ok",
    },
    {
      label: "Drift",
      value: statusText(client?.chrome_status),
      helper: `Livestream: ${statusText(client?.livestream_status || "idle")} · Display: ${displaySummary}`,
      level: getStatusLevel(client?.chrome_color || client?.chrome_step || client?.chrome_status),
    },
    {
      label: "Systemtid",
      value: timeSyncStatus === "ok" ? "Korrekt" : timeSyncStatus === "warning" ? "Advarsel" : timeSyncStatus === "critical" ? "Kritisk" : "Ukendt",
      helper: timeSyncMessage,
      level: timeSyncLevel,
    },
  ];

  const overviewSections = [
    {
      title: "Driftsoverblik",
      description: "De felter man normalt skal bruge først ved fejlsøgning.",
      columns: 2,
      rows: [
        { label: "Klientnavn", value: client?.name || client?.client_name },
        { label: "ClientFlow version", value: client?.client_version ? `v${String(client.client_version).replace(/^v/i, "")}` : "" },
        { label: "State", value: client?.state, status: true },
        { label: "Sidst set", value: formatDiagnosticDate(client?.presence?.status?.reported_at) },
        { label: "Chrome status", value: client?.chrome_status, status: true, wide: true },
        { label: "Netværk", value: networkMessage, level: networkLevel, wide: true },
        { label: "Display", value: `${displaySummary} · ${statusText(client?.display_resolution_current_output)}`, level: getStatusLevel(client?.display_resolution_status) },
        { label: "Ubuntu updates", value: formatUpdateCount(client?.ubuntu_updates_available), level: hasUbuntuUpdates ? "warn" : "ok" },
      ],
    },
    {
      title: "Systemtid",
      description: "Backend-kontrolleret status for tidszone, NTP og afvigelse fra serverens UTC-tid.",
      columns: 2,
      rows: [
        { label: "Status", value: client?.time_sync_status, status: true, level: timeSyncLevel },
        { label: "Tidszone", value: client?.system_timezone, level: client?.system_timezone === "Europe/Copenhagen" ? "ok" : hasDiagnosticValue(client?.system_timezone) ? "error" : "neutral" },
        { label: "NTP aktiveret", value: formatDiagnosticBoolean(client?.ntp_enabled), boolean: client?.ntp_enabled, trueLevel: "ok", falseLevel: "error" },
        { label: "NTP synkroniseret", value: formatDiagnosticBoolean(client?.ntp_synchronized), boolean: client?.ntp_synchronized, trueLevel: "ok", falseLevel: "error" },
        { label: "Ur-afvigelse", value: formatClockDrift(client?.clock_drift_seconds), level: timeSyncLevel },
        { label: "Klientens UTC-tid", value: formatDiagnosticDate(client?.client_time_utc) },
        { label: "Vurdering", value: timeSyncMessage, level: timeSyncLevel, wide: true },
      ],
    },
    {
      title: "Vigtige services",
      description: "Kerneservices vises her. Den fulde systemd-liste ligger under tekniske detaljer.",
      columns: 2,
      rows: [
        { label: "Backend sync", value: client?.service_clientflow_status, service: true, unit: "clientflow-status-agent.service" },
        { label: "Kalender", value: client?.service_calendar_status, service: true, unit: "clientflow-calendar.service" },
        { label: "Display runtime", value: client?.service_browser_guard_status, service: true, unit: "clientflow-display-runtime.service" },
        { label: "Fjernskrivebord", value: client?.service_remote_desktop_status, service: true, unit: "clientflow-remote-desktop-agent.service" },
        { label: "Livestream", value: client?.livestream_status || "idle", status: true, helper: `Service: ${statusText(client?.service_livestream_status, "ukendt")}` },
      ],
    },
  ];

  const technicalSections = [
    {
      title: "Kritiske systemd services",
      description: "Services der normalt skal køre hele tiden på en godkendt klient.",
      columns: 2,
      rows: criticalServiceRows,
    },
    {
      title: "Support og oneshot systemd services",
      description: "Livestream, opdatering og lifecycle. Klar/Stop kan være normal status afhængigt af service-type.",
      columns: 2,
      rows: supportServiceRows,
    },
    {
      title: "Lifecycle / strøm",
      description: "Seneste boot/reboot/shutdown-hændelse. State viser aktuel tilstand; lifecycle viser historik.",
      columns: 2,
      rows: [
        { label: "Seneste hændelse", value: lifecycleEventLabel, status: true },
        { label: "Kilde", value: client?.last_power_event_source, fallback: "ukendt", status: true },
        { label: "Event-tid", value: formatDiagnosticDate(client?.last_power_event_at) },
        { label: "Seneste boot", value: formatDiagnosticDate(client?.last_boot_at) },
        { label: "Boot ID", value: client?.last_boot_id, copy: true, wide: true },
        { label: "Reboot startet", value: formatDiagnosticDate(client?.last_reboot_started_at) },
        { label: "Shutdown startet", value: formatDiagnosticDate(client?.last_shutdown_started_at) },
      ],
    },
    {
      title: "Klient / OS",
      description: "Identitet, versioner og seneste kontakt.",
      columns: 2,
      rows: [
        { label: "Klient ID", value: client?.id, copy: true },
        { label: "Navn", value: client?.name || client?.client_name },
        { label: "Machine ID", value: client?.machine_id, copy: true, wide: true },
        { label: "Online", value: formatDiagnosticBoolean(onlineValue), boolean: !isOnline, trueLevel: "error", falseLevel: "ok" },
        { label: "Status", value: client?.status, status: true },
        { label: "State", value: client?.state, status: true },
        { label: "ClientFlow version", value: client?.client_version ? `v${String(client.client_version).replace(/^v/i, "")}` : "" },
        { label: "Ubuntu version", value: client?.ubuntu_version },
        { label: "Oppetid", value: formatUptime(client?.uptime) },
        { label: "Sidst set", value: formatDiagnosticDate(client?.presence?.status?.reported_at) },
        { label: "Diagnostik opdateret", value: formatDiagnosticDate(client?.diagnostics_updated_at), wide: true },
      ],
    },
    {
      title: "Systemtid / NTP",
      description: "ClientFlow status-domain rapporterer tidszone/NTP. Backend beregner ur-afvigelsen ved modtagelse.",
      columns: 2,
      rows: [
        { label: "Tidsstatus", value: client?.time_sync_status, status: true, level: timeSyncLevel },
        { label: "Tidszone", value: client?.system_timezone, copy: true },
        { label: "NTP aktiveret", value: formatDiagnosticBoolean(client?.ntp_enabled), boolean: client?.ntp_enabled, trueLevel: "ok", falseLevel: "error" },
        { label: "NTP synkroniseret", value: formatDiagnosticBoolean(client?.ntp_synchronized), boolean: client?.ntp_synchronized, trueLevel: "ok", falseLevel: "error" },
        { label: "Klientens UTC-tid", value: formatDiagnosticDate(client?.client_time_utc) },
        { label: "Ur-afvigelse", value: formatClockDrift(client?.clock_drift_seconds), level: timeSyncLevel },
        { label: "Backend-vurdering", value: timeSyncMessage, level: timeSyncLevel, wide: true },
        { label: "Diagnostik opdateret", value: formatDiagnosticDate(client?.diagnostics_updated_at), wide: true },
      ],
    },
    {
      title: "Netværk",
      description: "Aktiv forbindelse først, derefter adaptere.",
      columns: 2,
      rows: [
        { label: "Netværksstatus", value: networkMessage, level: networkLevel, wide: true },
        { label: "Statuskode", value: client?.network_status || "unknown", status: true },
        { label: "Aktiv type", value: client?.active_network_type, status: true },
        { label: "Aktivt interface", value: client?.active_network_interface, copy: true },
        { label: "Aktiv IP", value: client?.active_network_ip, copy: true },
        { label: "Aktiv MAC", value: client?.active_network_mac, copy: true },
        { label: "WLAN IP", value: client?.wifi_ip_address, copy: true },
        { label: "WLAN MAC", value: client?.wifi_mac_address, copy: true },
        { label: "LAN IP", value: client?.lan_ip_address, copy: true, fallback: "Ingen" },
        { label: "LAN MAC", value: client?.lan_mac_address, copy: true, fallback: "Ingen" },
      ],
    },
    {
      title: "Browser / kiosk",
      description: "Seneste kiosk-step og backend-pending handlinger.",
      columns: 2,
      rows: [
        { label: "Chrome status", value: client?.chrome_status, status: true, wide: true },
        { label: "Chrome step", value: client?.chrome_step, copy: true },
        { label: "Chrome farve", value: client?.chrome_color, status: true },
        { label: "Chrome opdateret", value: formatDiagnosticDate(client?.chrome_last_updated) },
        { label: "Pending action", value: hasPendingChromeAction ? client?.pending_chrome_action : "Ingen", level: hasPendingChromeAction ? "info" : "ok" },
        { label: "Pending source", value: client?.pending_chrome_action_source, fallback: "Ingen" },
        { label: "Pending reboot", value: formatDiagnosticBoolean(client?.pending_reboot), boolean: client?.pending_reboot },
        { label: "Pending shutdown", value: formatDiagnosticBoolean(client?.pending_shutdown), boolean: client?.pending_shutdown },
      ],
    },
    {
      title: "Livestream",
      description: "Ønsket stream-status, systemd-service, lokal proces og sidste segment.",
      columns: 2,
      rows: [
        { label: "Livestream status", value: client?.livestream_status, status: true },
        { label: "Livestream service", value: client?.service_livestream_status, livestreamService: true, unit: "clientflow-livestream-producer.service" },
        { label: "Livestream process", value: client?.livestream_process_status, livestreamService: true, unit: "gst-launch / uploader" },
        { label: "Sidste segment", value: formatDiagnosticDate(client?.livestream_last_segment) },
        { label: "Livestream fejl", value: client?.livestream_last_error, fallback: "Ingen", error: true, wide: true },
      ],
    },
    {
      title: "Display",
      description: "Faktisk output øverst; ønsket config nedenunder.",
      columns: 2,
      rows: [
        { label: "Display status", value: client?.display_resolution_status, status: true },
        { label: "Output", value: client?.display_resolution_current_output, copy: true },
        { label: "Aktuel opløsning", value: formatResolution(client?.display_resolution_current_width, client?.display_resolution_current_height) },
        { label: "Aktuel refresh", value: formatRefreshRate(client?.display_resolution_current_refresh_rate) },
        { label: "Fundne outputs", value: summarizeDetectedDisplays(client?.display_detected_outputs), wide: true },
        { label: "Sidst detekteret", value: formatDiagnosticDate(client?.display_detected_updated_at), wide: true },
        { label: "Sidst anvendt", value: formatDiagnosticDate(client?.display_resolution_last_applied_at), wide: true },
        { label: "Ønsket preset", value: client?.display_resolution_preset },
        { label: "Ønsket mode", value: client?.display_resolution_mode },
        { label: "Ønsket opløsning", value: formatResolution(client?.display_resolution_width, client?.display_resolution_height) },
        { label: "Ønsket refresh", value: formatRefreshRate(client?.display_resolution_refresh_rate) },
        { label: "Rotation", value: client?.display_resolution_rotation },
        { label: "Display action", value: client?.display_resolution_action, fallback: "Ingen" },
        { label: "Config opdateret", value: formatDiagnosticDate(client?.display_resolution_updated_at) },
        { label: "Display fejl", value: client?.display_resolution_error, fallback: "Ingen", error: true, wide: true },
      ],
    },
    {
      title: "Opdateringer",
      description: "Ubuntu-pakker. ClientFlow-deployments vises i Software-panelet fra den canonical deployment-state-machine.",
      columns: 2,
      rows: [
        { label: "Ubuntu updates", value: formatUpdateCount(client?.ubuntu_updates_available), level: hasUbuntuUpdates ? "warn" : "ok" },
        { label: "Ubuntu update service", value: client?.service_ubuntu_update_status, service: true, oneshot: true, unit: "clientflow_ubuntu_update.service" },
        { label: "Pending OS update", value: formatDiagnosticBoolean(client?.pending_os_update), boolean: client?.pending_os_update, trueLevel: "info" },
      ],
    },
  ];

  const [showTechnicalDetails, setShowTechnicalDetails] = React.useState(false);

  const renderStatusDot = (level) => {

    const color = levelColors[level] || levelColors.neutral;
    return (
      <Box
        component="span"
        sx={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          bgcolor: color,
          boxShadow: `0 0 0 4px ${color}22`,
          flex: "0 0 auto",
        }}
      />
    );
  };

  const renderSummaryCard = (card) => {
    const color = levelColors[card.level] || levelColors.neutral;
    return (
      <Grid
        key={card.label}
        size={{
          xs: 12,
          sm: 6,
          md: 3
        }}>
        <Box
          sx={{
            p: 1.15,
            height: "100%",
            borderRadius: 2,
            background: levelBackgrounds[card.level] || FIELD_BG,
            border: `1px solid ${color}55`,
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
          }}
        >
          <Stack direction="row" spacing={0.75} sx={{
            alignItems: "center"
          }}>
            {renderStatusDot(card.level)}
            <Typography variant="caption" sx={{ color: MUTED, fontWeight: 900, textTransform: "uppercase", letterSpacing: 0.55 }}>
              {card.label}
            </Typography>
          </Stack>
          <Typography sx={{ mt: 0.5, color: TEXT, fontWeight: 950, lineHeight: 1.16, overflowWrap: "anywhere" }}>
            {card.value}
          </Typography>
          <Typography variant="caption" sx={{ display: "block", mt: 0.35, color: MUTED, overflowWrap: "anywhere" }}>
            {card.helper}
          </Typography>
        </Box>
      </Grid>
    );
  };

  const renderDiagnosticRow = (row) => {
    const level = getRowLevel(row);
    const color = levelColors[level] || levelColors.neutral;
    const value = formatDiagnosticValue(row.value, row.fallback || "ukendt");

    return (
      <Grid
        key={row.label}
        size={{
          xs: 12,
          sm: row.wide ? 12 : 6
        }}>
        <Box
          sx={{
            p: 1,
            borderRadius: 2,
            background: "rgba(15,23,42,0.30)",
            border: `1px solid ${BORDER}`,
            borderLeft: `3px solid ${color}`,
            minHeight: row.unit || row.helper ? 86 : 66,
          }}
        >
          <Stack
            direction="row"
            spacing={0.75}
            sx={{
              alignItems: "flex-start",
              justifyContent: "space-between"
            }}>
            <Stack
              direction="row"
              spacing={0.7}
              sx={{
                alignItems: "center",
                minWidth: 0
              }}>
              {renderStatusDot(level)}
              <Typography variant="caption" sx={{ color: MUTED, fontWeight: 850, lineHeight: 1.2 }}>
                {row.label}
              </Typography>
            </Stack>
            {row.copy ? <CopyButton value={value} /> : null}
          </Stack>
          <Typography
            sx={{
              mt: 0.45,
              color: row.error && hasDiagnosticValue(row.value) ? "#fca5a5" : TEXT,
              fontWeight: 850,
              lineHeight: 1.22,
              overflowWrap: "anywhere",
              wordBreak: "break-word",
            }}
          >
            {value}
          </Typography>
          {row.unit || row.helper ? (
            <Typography variant="caption" sx={{ display: "block", mt: 0.45, color: MUTED, overflowWrap: "anywhere" }}>
              {row.unit ? row.unit : row.helper}{row.unit && row.helper ? ` · ${row.helper}` : ""}
            </Typography>
          ) : null}
        </Box>
      </Grid>
    );
  };

  const renderSection = (section) => (
    <Grid
      key={section.title}
      size={{
        xs: 12,
        md: section.columns === 1 ? 12 : 6
      }}>
      <Box
        sx={{
          height: "100%",
          p: 1.25,
          borderRadius: 2,
          background: "rgba(15,23,42,0.34)",
          border: `1px solid ${BORDER}`,
        }}
      >
        <Stack spacing={0.35} sx={{ mb: 1.15 }}>
          <Typography sx={{ color: TEXT, fontWeight: 950, lineHeight: 1.15 }}>{section.title}</Typography>
          {section.description && (
            <Typography variant="body2" sx={{ color: MUTED, lineHeight: 1.35 }}>
              {section.description}
            </Typography>
          )}
        </Stack>
        <Grid container spacing={0.85}>
          {section.rows.map(renderDiagnosticRow)}
        </Grid>
      </Box>
    </Grid>
  );

  return (
    <DataPanel
      title="Diagnostik"
      description="Samlet driftsstatus. De tekniske felter er samlet nederst og kan foldes ud efter behov. Kun synlig for superadministratorer."
      action={
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{
          alignItems: { xs: "flex-start", sm: "center" }
        }}>
          <Typography variant="caption" sx={{ color: MUTED, fontWeight: 800 }}>
            Opdateret: {formatDiagnosticDate(client?.diagnostics_updated_at)} · auto hvert 10 sek.
          </Typography>
          {onRefresh ? (
            <Button size="small" variant="outlined" startIcon={<RefreshIcon />} onClick={onRefresh} sx={{ borderRadius: 999, color: TEXT, borderColor: BORDER }}>
              Opdater
            </Button>
          ) : null}
        </Stack>
      }
    >
      <Stack spacing={1.5}>
        <Grid container spacing={1} sx={{
          alignItems: "stretch"
        }}>
          {summaryCards.map(renderSummaryCard)}
        </Grid>

        <Box
          sx={{
            p: 1.15,
            borderRadius: 2,
            background: attentionItems.length ? "rgba(251,191,36,0.09)" : "rgba(34,197,94,0.08)",
            border: attentionItems.length ? "1px solid rgba(251,191,36,0.28)" : "1px solid rgba(34,197,94,0.22)",
          }}
        >
          <Stack spacing={0.75}>
            <Typography sx={{ color: TEXT, fontWeight: 950 }}>
              {attentionItems.length ? "Kræver opmærksomhed" : "Ingen tydelige diagnostikproblemer"}
            </Typography>
            {attentionItems.length ? attentionItems.map((item) => (
              <Stack key={item.label} direction={{ xs: "column", sm: "row" }} spacing={0.75} sx={{
                alignItems: { xs: "flex-start", sm: "center" }
              }}>
                {renderStatusDot(item.level)}
                <Typography variant="body2" sx={{ color: TEXT, fontWeight: 850 }}>{item.label}</Typography>
                <Typography variant="body2" sx={{ color: MUTED, overflowWrap: "anywhere" }}>{item.value}</Typography>
              </Stack>
            )) : (
              <Typography variant="body2" sx={{ color: MUTED }}>
                Kritiske systemd-services, livestream-status, display og update-felter ser normale ud.
              </Typography>
            )}
          </Stack>
        </Box>

        <Grid container spacing={1.25}>
          {overviewSections.map(renderSection)}
        </Grid>

        <Box
          sx={{
            p: 1.15,
            borderRadius: 2,
            background: "rgba(15,23,42,0.24)",
            border: `1px solid ${BORDER}`,
          }}
        >
          <Stack
            direction={{ xs: "column", sm: "row" }}
            spacing={1}
            sx={{
              alignItems: { xs: "flex-start", sm: "center" },
              justifyContent: "space-between"
            }}>
            <Box>
              <Typography sx={{ color: TEXT, fontWeight: 950 }}>Tekniske detaljer</Typography>
              <Typography variant="body2" sx={{ color: MUTED, lineHeight: 1.35 }}>
                Fuld liste med rå statusfelter for services, netværk, display, livestream, lifecycle og opdateringer.
              </Typography>
            </Box>
            <Button
              size="small"
              variant="outlined"
              onClick={() => setShowTechnicalDetails((value) => !value)}
              sx={{ borderRadius: 999, color: TEXT, borderColor: BORDER, flex: "0 0 auto" }}
            >
              {showTechnicalDetails ? "Skjul tekniske detaljer" : "Vis tekniske detaljer"}
            </Button>
          </Stack>

          {showTechnicalDetails ? (
            <Grid container spacing={1.25} sx={{ mt: 1.15 }}>
              {technicalSections.map(renderSection)}
            </Grid>
          ) : (
            <Typography variant="body2" sx={{ mt: 1, color: MUTED }}>
              Detaljerne er skjult for at gøre Diagnostik mere overskuelig. Fold dem ud ved dybere fejlsøgning.
            </Typography>
          )}
        </Box>
      </Stack>
    </DataPanel>
  );
}

export default function ClientDetailsInfoSection({
  client,
  markedDays,
  uptime,
  lastSeen,
  setCalendarDialogOpen,
  clientOnline,
  calendarLoading = false,
  showSnackbar,
  onUbuntuUpdateStarted,
  onDiagnosticsRefresh,
  onConfigSaved,
  handleClientAction,
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const { user } = useAuth();
  const isSuperadmin = user?.role === "superadmin";
  const isViewer = user?.role === "viewer";
  const canViewDiagnostics = isSuperadmin || isViewer;
  const [activeTab, setActiveTab] = React.useState("calendar");
  const diagnosticsRefreshInFlightRef = React.useRef(false);
  const configRefreshInFlightRef = React.useRef(false);

  const tabs = React.useMemo(() => {
    const base = [
      { value: "calendar", label: "Kalender" },
      { value: "system", label: "System" },
      { value: "network", label: "Netværk" },
      { value: "config", label: "Konfiguration" },
    ];
    if (canViewDiagnostics) base.push({ value: "diagnostics", label: "Diagnostik" });
    return base;
  }, [canViewDiagnostics]);

  React.useEffect(() => {
    if (!tabs.some((tab) => tab.value === activeTab)) {
      setActiveTab("calendar");
    }
  }, [activeTab, tabs]);

  const currentTab = tabs.some((tab) => tab.value === activeTab) ? activeTab : "calendar";

  React.useEffect(() => {
    if (currentTab !== "config" || typeof onDiagnosticsRefresh !== "function") {
      return undefined;
    }

    let alive = true;

    const refreshConfig = async () => {
      if (!alive || configRefreshInFlightRef.current) return;
      configRefreshInFlightRef.current = true;
      try {
        await onDiagnosticsRefresh();
      } catch {
        // Ignorer stille refresh-fejl i Konfiguration. Næste interval prøver igen.
      } finally {
        configRefreshInFlightRef.current = false;
      }
    };

    refreshConfig();
    const timer = window.setInterval(refreshConfig, 15_000);

    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [currentTab, onDiagnosticsRefresh]);

  React.useEffect(() => {
    if (!canViewDiagnostics || currentTab !== "diagnostics" || typeof onDiagnosticsRefresh !== "function") {
      return undefined;
    }

    let alive = true;

    const refreshDiagnostics = async () => {
      if (!alive || diagnosticsRefreshInFlightRef.current) return;
      diagnosticsRefreshInFlightRef.current = true;
      try {
        await onDiagnosticsRefresh();
      } catch {
        // Ignorer stille refresh-fejl i diagnostik. Næste interval prøver igen.
      } finally {
        diagnosticsRefreshInFlightRef.current = false;
      }
    };

    refreshDiagnostics();
    const timer = window.setInterval(refreshDiagnostics, 10_000);

    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [canViewDiagnostics, currentTab, onDiagnosticsRefresh]);

  return (
    <Box sx={{ color: TEXT }}>
      <Box
        sx={{
          mb: 1.6,
          borderRadius: 2,
          background: "rgba(15,23,42,0.32)",
          border: `1px solid ${BORDER}`,
          overflow: "hidden",
        }}
      >
        <Tabs
          value={currentTab}
          onChange={(_event, value) => setActiveTab(value)}
          variant={isMobile ? "scrollable" : "standard"}
          scrollButtons={isMobile ? "auto" : false}
          allowScrollButtonsMobile
          sx={{
            minHeight: 46,
            px: 0.5,
            "& .MuiTabs-indicator": { height: 3, borderRadius: 999, backgroundColor: "#38bdf8" },
            "& .MuiTab-root": {
              minHeight: 46,
              textTransform: "none",
              fontWeight: 900,
              color: MUTED,
            },
            "& .Mui-selected": { color: `${TEXT} !important` },
          }}
        >
          {tabs.map((tab) => <Tab key={tab.value} value={tab.value} label={tab.label} />)}
        </Tabs>
      </Box>

      {currentTab === "calendar" && (
        <ScheduleStrip
          markedDays={markedDays || {}}
          calendarLoading={calendarLoading}
          clientId={client?.id}
          onOpenCalendar={() => setCalendarDialogOpen?.(true)}
          onCalendarDaySaved={onConfigSaved || onDiagnosticsRefresh}
          organizationTimes={client?.organization_times || client?.organizationTimes || null}
        />
      )}

      {currentTab === "system" && (
        <SystemPanel
          client={client}
          uptime={uptime}
          lastSeen={lastSeen}
          clientOnline={clientOnline}
          showSnackbar={showSnackbar}
          onUbuntuUpdateStarted={onUbuntuUpdateStarted}
          onDiagnosticsRefresh={onDiagnosticsRefresh}
        />
      )}

      {currentTab === "network" && <NetworkPanel client={client} />}

      {currentTab === "config" && (
        <ConfigurationPanel
          client={client}
          showSnackbar={showSnackbar}
          onSaved={onConfigSaved || onDiagnosticsRefresh}
          onRefresh={onDiagnosticsRefresh}
          handleClientAction={handleClientAction}
          clientOnline={clientOnline}
        />
      )}

      {currentTab === "diagnostics" && canViewDiagnostics && (
        <DiagnosticsPanel client={client} onRefresh={onDiagnosticsRefresh} />
      )}
    </Box>
  );
}
