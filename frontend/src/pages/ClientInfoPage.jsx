import AppSnackbar from "../components/AppSnackbar";
import React, { useState, useEffect, useRef, useCallback, memo } from "react";
import {
  Box,
  Typography,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  IconButton,
  Button,
  Tooltip,
  CircularProgress,
  Stack,
  Alert as MuiAlert,
  Select,
  MenuItem,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Chip,
  TextField,
  Collapse,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import DeleteForeverIcon from "@mui/icons-material/DeleteForever";
import RestoreFromTrashIcon from "@mui/icons-material/RestoreFromTrash";
import AddIcon from "@mui/icons-material/Add";
import RefreshIcon from "@mui/icons-material/Refresh";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import LocationOnIcon from "@mui/icons-material/LocationOn";
import DevicesIcon from "@mui/icons-material/Devices";
import PendingActionsIcon from "@mui/icons-material/PendingActions";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { compactDarkChipSx } from "../utils/chipStyles";
import {
  pageHeaderIconSx,
  pageHeaderPaperSx,
  pageShellSx,
} from "../utils/layoutStyles";
import { Link } from "react-router-dom";
import {
  getClients,
  getMyClients,
  approveClient,
  removeClient,
  restoreClient,
  purgeClient,
  getDeletedClients,
  updateClient,
  getOrganizations,
} from "../api";
import { useAuth } from "../auth/AuthProvider";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";

/*
  ClientInfoPage.jsx

  Formål:
  - Viser godkendte klienter.
  - Viser nye/pending klienter fra enrollment/installationskode-flow.
  - Godkender pending klienter med organisationsvalg.
  - Fjerner klienter med robust loading/error-flow.

  Relevante forbedringer:
  - Pending/enrollment-klienter viser nu lokalitet tydeligt.
  - Pending-listen sorteres med nyeste klienter først.
  - Slet/fjern har loading state og lukker kun dialog ved succes.
  - Fjern opdaterer UI optimistisk og henter derefter listen igen.
  - Baggrundspolling spammer ikke snackbar.
  - Polling pauser under drag/sort.
  - Hurtigere online/offline-polling med guard mod overlappende requests.
  - Fokus/visibility refresh, så listen opdateres straks når fanen åbnes igen.
  - Netværksfelter viser "ikke tilsluttet" for LAN når backend angiver det.
*/

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------

// Detaljesiden får online/offline hurtigt via /chrome-status.
// Oversigten henter hele klientlisten, så vi poller lidt langsommere, men
// stadig hurtigere end før, så status ikke føles forsinket.
const CLIENT_LIST_POLL_MS = 2_000;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimestamp(isoDate) {
  if (!isoDate) return { date: "", time: "" };

  const raw = String(isoDate);
  const dateObj = new Date(
    raw.endsWith("Z") || /[+\-]\d{2}:?\d{2}$/.test(raw) ? raw : raw + "Z",
  );

  if (Number.isNaN(dateObj.getTime())) {
    return { date: "", time: "" };
  }

  const formatter = new Intl.DateTimeFormat("da-DK", {
    timeZone: "Europe/Copenhagen",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  const parts = formatter.formatToParts(dateObj);
  const get = (type) => parts.find((p) => p.type === type)?.value || "";

  return {
    date: `${get("day")}-${get("month")}-${get("year")}`,
    time: `Kl. ${get("hour")}:${get("minute")}:${get("second")}`,
  };
}

function getTimestampMs(value) {
  if (!value) return 0;
  const raw = String(value);
  const d = new Date(
    raw.endsWith("Z") || /[+\-]\d{2}:?\d{2}$/.test(raw) ? raw : raw + "Z",
  );
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
}

function getClientOrganizationId(client) {
  return client?.organization_id ?? client?.organizationId ?? "";
}

function getClientDisplayName(client) {
  return client?.name || client?.hostname || `Klient #${client?.id ?? "?"}`;
}

function getClientLocality(client) {
  return client?.locality || client?.location || "";
}

function getClientOnline(client) {
  return client?.presence?.is_online === true;
}

function normalizeNetworkValue(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const lower = text.toLowerCase();
  if (
    ["null", "none", "undefined", "ukendt", "unknown", "n/a", "-"].includes(
      lower,
    )
  )
    return "";
  if (text === "0.0.0.0" || text === "00:00:00:00:00:00") return "";
  return text;
}

function normalizeBooleanLike(value) {
  if (value === true || value === 1 || value === "1") return true;
  if (value === false || value === 0 || value === "0") return false;
  if (typeof value === "string") {
    const lower = value.trim().toLowerCase();
    if (["true", "yes", "ja", "connected", "tilsluttet", "up"].includes(lower))
      return true;
    if (
      [
        "false",
        "no",
        "nej",
        "disconnected",
        "ikke_tilsluttet",
        "down",
      ].includes(lower)
    )
      return false;
  }
  return null;
}

function getLanConnected(client) {
  const explicit =
    client?.lan_connected ??
    client?.ethernet_connected ??
    client?.lan_is_connected ??
    client?.wired_connected;

  const explicitValue = normalizeBooleanLike(explicit);
  if (explicitValue !== null) return explicitValue;

  // Fallback til eksisterende data, hvis backend endnu ikke sender et
  // eksplicit LAN-connected felt.
  return !!(
    normalizeNetworkValue(client?.lan_ip_address) ||
    normalizeNetworkValue(client?.lan_mac_address)
  );
}

function getNetworkDisplayValue(client, key) {
  const isLan = String(key || "").startsWith("lan_");
  if (isLan && !getLanConnected(client)) return "ikke tilsluttet";

  const value = normalizeNetworkValue(client?.[key]);
  if (value) return value;

  return isLan ? "ikke tilsluttet" : "ukendt";
}

function getNetworkCopyValue(client, key) {
  const value = getNetworkDisplayValue(client, key);
  return value === "ukendt" || value === "ikke tilsluttet" ? "" : value;
}

function getClientStatusChipProps(status) {
  const value = String(status || "").toLowerCase();

  if (value === "approved") {
    return { label: "Godkendt", color: "success" };
  }

  if (value === "pending" || value === "awaiting_approval") {
    return { label: "Afventer", color: "warning" };
  }

  if (value === "rejected" || value === "disabled") {
    return { label: "Deaktiveret", color: "default" };
  }

  return { label: status || "Ukendt", color: "default" };
}

function getClientRuntimeStateChipProps(client) {
  const pendingAction = String(
    client?.pending_chrome_action || client?.pendingChromeAction || "none",
  )
    .trim()
    .toLowerCase();
  const state = String(client?.state || "")
    .trim()
    .toLowerCase();
  const chromeStep = String(
    client?.chrome_step || client?.last_chrome_step || "",
  )
    .trim()
    .toLowerCase();
  const displayPower = String(client?.display_power_status || "")
    .trim()
    .toLowerCase();
  const hasPendingAction = !!pendingAction && pendingAction !== "none";
  const stateIsNormal = !state || state === "normal" || state === "approved";

  // ClientInfoPage skal følge samme hovedsandhed som Control Room:
  // client.state + aktiv pending_chrome_action. Gamle chrome_step/last_chrome_step
  // kan hænge længe efter en handling og må derfor ikke gøre en normal klient til
  // fx "starter" i oversigten, når Control Room allerede viser normal.
  const stateLabels = {
    normal: { label: "Normal", color: "default" },
    approved: { label: "Normal", color: "default" },
    sleep: { label: "Dvale", color: "info" },
    sleeping: { label: "Dvale", color: "info" },
    display_sleep: { label: "Dvale", color: "info" },
    system_sleep: { label: "Dvale", color: "info" },
    waking: { label: "Vækker", color: "warning" },
    wake: { label: "Vækker", color: "warning" },
    display_wake: { label: "Vækker", color: "warning" },
    system_wake: { label: "Vækker", color: "warning" },
    updating: { label: "Opdaterer", color: "warning" },
    rebooting: { label: "Genstarter", color: "warning" },
    system_rebooting: { label: "Genstarter", color: "warning" },
    shutdown: { label: "Slukker", color: "error" },
    shutting_down: { label: "Slukker", color: "error" },
    system_shutting_down: { label: "Slukker", color: "error" },
  };

  if (!stateIsNormal && stateLabels[state]) {
    return stateLabels[state];
  }

  if (!stateIsNormal) {
    return { label: state.replaceAll("_", " "), color: "default" };
  }

  if (
    ["sleep", "display_sleep", "system_sleep", "sleeping"].includes(
      pendingAction,
    )
  ) {
    return { label: "Dvale", color: "info" };
  }

  if (
    ["wakeup", "wake", "display_wake", "system_wake"].includes(pendingAction)
  ) {
    return { label: "Vækker", color: "warning" };
  }

  if (pendingAction === "os_update") {
    return { label: "Opdaterer", color: "warning" };
  }

  if (["reboot", "rebooting", "system_rebooting"].includes(pendingAction)) {
    return { label: "Genstarter", color: "warning" };
  }

  if (
    ["shutdown", "shutting_down", "system_shutting_down"].includes(
      pendingAction,
    )
  ) {
    return { label: "Slukker", color: "error" };
  }

  if (
    ["start", "starting", "start_chrome", "starting_chrome"].includes(
      pendingAction,
    )
  ) {
    return { label: "Starter", color: "warning" };
  }

  if (
    ["stop", "stopping", "stop_chrome", "shutdown_chrome"].includes(
      pendingAction,
    )
  ) {
    return { label: "Stopper", color: "warning" };
  }

  // Kun hvis der faktisk er en aktiv pending action må step-felter bruges som
  // sekundær live-indikator. Det forhindrer stale chrome_step="starting" i at
  // overstyre state="normal".
  if (hasPendingAction) {
    if (chromeStep.startsWith("os_"))
      return { label: "Opdaterer", color: "warning" };
    if (chromeStep === "system_rebooting")
      return { label: "Genstarter", color: "warning" };
    if (chromeStep === "system_shutting_down")
      return { label: "Slukker", color: "error" };
    if (["display_sleep", "display_sleep_complete"].includes(chromeStep))
      return { label: "Dvale", color: "info" };
    if (["starting", "starting_chrome"].includes(chromeStep))
      return { label: "Starter", color: "warning" };
    if (["stopping", "shutdown_chrome"].includes(chromeStep))
      return { label: "Stopper", color: "warning" };
  }

  // Hvis backend kun rapporterer display_power_status og ingen state/pending,
  // må skærm-sluk stadig vises. Dette bruges ikke til at vise "starter".
  if (
    ["off_requested", "off", "display_off", "display_sleep_complete"].includes(
      displayPower,
    )
  ) {
    return { label: "Dvale", color: "info" };
  }

  return { label: "Normal", color: "default" };
}

function getDeletedByLabel(client) {
  const value = client?.deleted_by_user_id ?? client?.deletedByUserId;
  return value ? `Bruger #${value}` : "Ukendt";
}

function getDeletedReason(client) {
  return String(client?.deleted_reason || "").trim();
}

// Sammenlign kun felter, der bruges på denne oversigt.
// Uptime ændres løbende, men vises ikke her.
function isClientListEqual(a = [], b = []) {
  if (a.length !== b.length) return false;

  for (let i = 0; i < a.length; i++) {
    const ca = a[i] || {};
    const cb = b[i] || {};

    if (
      ca.id !== cb.id ||
      ca.name !== cb.name ||
      ca.hostname !== cb.hostname ||
      ca.locality !== cb.locality ||
      ca.location !== cb.location ||
      ca.status !== cb.status ||
      ca.state !== cb.state ||
      ca.pending_chrome_action !== cb.pending_chrome_action ||
      ca.chrome_step !== cb.chrome_step ||
      ca.last_chrome_step !== cb.last_chrome_step ||
      ca.display_power_status !== cb.display_power_status ||
      ca.sort_order !== cb.sort_order ||
      getClientOnline(ca) !== getClientOnline(cb) ||
      String(getClientOrganizationId(ca)) !==
        String(getClientOrganizationId(cb)) ||
      // Felter vist for ikke-godkendte/enrollment klienter
      ca.wifi_ip_address !== cb.wifi_ip_address ||
      ca.lan_ip_address !== cb.lan_ip_address ||
      ca.wifi_mac_address !== cb.wifi_mac_address ||
      ca.lan_mac_address !== cb.lan_mac_address ||
      ca.lan_connected !== cb.lan_connected ||
      ca.ethernet_connected !== cb.ethernet_connected ||
      ca.lan_is_connected !== cb.lan_is_connected ||
      ca.wired_connected !== cb.wired_connected ||
      ca.machine_id !== cb.machine_id ||
      ca.created_at !== cb.created_at
    ) {
      return false;
    }
  }

  return true;
}

// ---------------------------------------------------------------------------
// Sub-komponenter
// ---------------------------------------------------------------------------

const CopyIconButton = memo(function CopyIconButton({
  value,
  disabled,
  iconSize = 16,
}) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async (e) => {
    e.stopPropagation();
    if (disabled || value === null || value === undefined || value === "")
      return;
    const text = String(value);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // ignore
    }
  };

  return (
    <Tooltip title={copied ? "Kopieret!" : "Kopiér"}>
      <span>
        <IconButton
          size="small"
          onClick={handleCopy}
          sx={{ ml: 0.5, p: 0.2 }}
          disabled={disabled}
        >
          <ContentCopyIcon
            sx={{ fontSize: iconSize * 0.96 }}
            color={copied ? "success" : "inherit"}
          />
        </IconButton>
      </span>
    </Tooltip>
  );
});

const ClientStatusCell = memo(function ClientStatusCell({ isOnline, client }) {
  const runtimeState = getClientRuntimeStateChipProps(client);
  const onlineText = isOnline ? "online" : "offline";
  const stateText = String(runtimeState.label || "normal")
    .trim()
    .toLowerCase();
  const tone = !isOnline
    ? "error"
    : runtimeState.color === "warning"
      ? "warning"
      : runtimeState.color === "info"
        ? "info"
        : "success";

  return (
    <Chip
      size="small"
      label={`${onlineText} / ${stateText}`}
      sx={compactDarkChipSx(tone, { minWidth: 104 })}
    />
  );
});

const EnrollmentIdentityCell = memo(function EnrollmentIdentityCell({
  client,
}) {
  const locality = getClientLocality(client);
  const machineId = client?.machine_id || "";

  return (
    <Stack spacing={0.35}>
      <Stack direction="row" spacing={0.75} sx={{
        alignItems: "center"
      }}>
        <DevicesIcon sx={{ fontSize: 17, color: "primary.main" }} />
        <Typography sx={{ fontWeight: 700 }}>
          {getClientDisplayName(client)}
        </Typography>
      </Stack>
      <Stack direction="row" spacing={0.75} sx={{
        alignItems: "center"
      }}>
        <LocationOnIcon sx={{ fontSize: 16, color: "text.secondary" }} />
        <Typography
          variant="body2"
          color={locality ? "text.primary" : "text.secondary"}
        >
          {locality || "Ingen lokation angivet"}
        </Typography>
      </Stack>
      {machineId && (
        <Typography
          variant="caption"
          sx={{
            color: "text.secondary",
            wordBreak: "break-all"
          }}>
          Machine ID: {machineId}
          <CopyIconButton value={machineId} iconSize={13} />
        </Typography>
      )}
    </Stack>
  );
});

// ---------------------------------------------------------------------------
// Hoved-komponent
// ---------------------------------------------------------------------------

export default function ClientInfoPage() {
  const { user } = useAuth();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));

  const [clients, setClients] = useState([]);
  const [deletedClients, setDeletedClients] = useState([]);
  const [organizations, setOrganizations] = useState([]);
  const [organizationSelections, setOrganizationSelections] = useState({});
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [dragClients, setDragClients] = useState([]);
  const [savingSort, setSavingSort] = useState(false);

  const [removingClientId, setRemovingClientId] = useState(null);
  const [restoringClientId, setRestoringClientId] = useState(null);
  const [purgingClientId, setPurgingClientId] = useState(null);
  const [loadingDeletedClients, setLoadingDeletedClients] = useState(false);
  const [approvingClientId, setApprovingClientId] = useState(null);

  const lastFetchedClients = useRef([]);
  const isDraggingRef = useRef(false);
  const fetchingClientsRef = useRef(false);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmClientId, setConfirmClientId] = useState(null);
  const [confirmDeleteText, setConfirmDeleteText] = useState("");
  const [removeReason, setRemoveReason] = useState("");
  const [trashExpanded, setTrashExpanded] = useState(false);

  const [purgeDialogOpen, setPurgeDialogOpen] = useState(false);
  const [purgeClientId, setPurgeClientId] = useState(null);
  const [purgeConfirmText, setPurgeConfirmText] = useState("");

  const [snackbar, setSnackbar] = useState({
    open: false,
    message: "",
    severity: "success",
  });

  const showSnackbar = useCallback((message, severity = "success") => {
    setSnackbar({ open: true, message, severity });
  }, []);

  const handleCloseSnackbar = useCallback(() => {
    setSnackbar({ open: false, message: "", severity: "success" });
  }, []);

  const role = user?.role || "";
  const isSuperadmin = role === "superadmin";
  const isAdmin = role === "admin" || isSuperadmin;
  const isViewer = role === "viewer";
  const isOrgReadRole = role === "bruger";
  const canViewClientId = isSuperadmin;
  const canManageClients = isSuperadmin;
  const canViewTrash = isSuperadmin || isViewer;

  const selectedClientForRemoval =
    clients.find((client) => client.id === confirmClientId) || null;

  const selectedClientForPurge =
    deletedClients.find((client) => client.id === purgeClientId) || null;

  // ---------------------------------------------------------------------------
  // Data-hentning
  // ---------------------------------------------------------------------------

  const fetchClients = useCallback(
    async (forceUpdate = false, showLoading = false) => {
      if (isDraggingRef.current) return;
      if (fetchingClientsRef.current) return;

      fetchingClientsRef.current = true;
      if (showLoading) setLoading(true);
      try {
        const data = isOrgReadRole ? await getMyClients() : await getClients();

        if (
          forceUpdate ||
          !isClientListEqual(data, lastFetchedClients.current)
        ) {
          setClients(data);
          lastFetchedClients.current = data;
        }
      } catch (err) {
        if (forceUpdate || showLoading) {
          showSnackbar("Fejl: " + (err?.message || err), "error");
        }
      } finally {
        fetchingClientsRef.current = false;
        if (showLoading) setLoading(false);
      }
    },
    [isOrgReadRole, showSnackbar],
  );

  const fetchDeletedClients = useCallback(
    async (showLoading = false) => {
      if (!canViewTrash) return;
      if (showLoading) setLoadingDeletedClients(true);
      try {
        const data = await getDeletedClients();
        setDeletedClients(Array.isArray(data) ? data : []);
      } catch (err) {
        if (showLoading) {
          showSnackbar(
            "Kunne ikke hente papirkurv: " + (err?.message || err),
            "error",
          );
        }
      } finally {
        if (showLoading) setLoadingDeletedClients(false);
      }
    },
    [canViewTrash, showSnackbar],
  );

  const fetchOrganizations = useCallback(async () => {
    try {
      const data = await getOrganizations();
      setOrganizations(Array.isArray(data) ? data : []);
    } catch {
      setOrganizations([]);
    }
  }, []);

  // Initial load + hurtigere polling af online/offline-status.
  useEffect(() => {
    fetchClients(false, true);
    fetchDeletedClients(false);
    const timer = setInterval(() => {
      fetchClients(false, false);
    }, CLIENT_LIST_POLL_MS);
    return () => clearInterval(timer);
  }, [fetchClients, fetchDeletedClients]);

  // Når brugeren vender tilbage til fanen/siden, hent status med det samme
  // i stedet for at vente på næste polling-interval.
  useEffect(() => {
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") {
        fetchClients(false, false);
      }
    };

    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);

    return () => {
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [fetchClients]);

  // Hent organisationer
  useEffect(() => {
    fetchOrganizations();
  }, [fetchOrganizations]);

  // Opdater dragClients når clients ændres
  useEffect(() => {
    if (isDraggingRef.current) return;

    const approved = clients
      .filter((c) => c.status === "approved")
      .slice()
      .sort((a, b) => {
        const aHas = a.sort_order !== null && a.sort_order !== undefined;
        const bHas = b.sort_order !== null && b.sort_order !== undefined;
        if (aHas && bHas) return a.sort_order - b.sort_order;
        if (aHas) return -1;
        if (bHas) return 1;
        return a.id - b.id;
      });

    setDragClients(approved);
  }, [clients]);

  // Pending/enrollment-klienter: nyeste først.
  const unapprovedClients = clients
    .filter((c) => c.status !== "approved")
    .slice()
    .sort((a, b) => {
      const byCreated =
        getTimestampMs(b.created_at) - getTimestampMs(a.created_at);
      if (byCreated !== 0) return byCreated;
      return (b.id || 0) - (a.id || 0);
    });

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        fetchClients(true, true),
        fetchDeletedClients(false),
        fetchOrganizations(),
      ]);
      showSnackbar("Siden er opdateret.", "success");
    } finally {
      setRefreshing(false);
    }
  }, [fetchClients, fetchDeletedClients, fetchOrganizations, showSnackbar]);

  const openRemoveDialog = useCallback((clientId) => {
    // Undgå MUI aria-hidden warning hvis knappen beholder fokus, mens dialogen åbner.
    if (
      typeof document !== "undefined" &&
      document.activeElement instanceof HTMLElement
    ) {
      document.activeElement.blur();
    }
    setConfirmClientId(clientId);
    setConfirmDeleteText("");
    setRemoveReason("");
    setConfirmOpen(true);
  }, []);

  const closeRemoveDialog = useCallback(() => {
    if (removingClientId) return;
    setConfirmOpen(false);
    setConfirmClientId(null);
    setConfirmDeleteText("");
    setRemoveReason("");
  }, [removingClientId]);

  const handleRemoveClient = useCallback(
    async (clientId) => {
      setRemovingClientId(clientId);

      try {
        await removeClient(clientId, removeReason.trim());

        // Optimistisk fjern fra aktive/pending lister med det samme.
        setClients((prev) => {
          const next = prev.filter((client) => client.id !== clientId);
          lastFetchedClients.current = next;
          return next;
        });
        setDragClients((prev) =>
          prev.filter((client) => client.id !== clientId),
        );

        showSnackbar("Klient flyttet til papirkurv.", "success");
        setConfirmOpen(false);
        setConfirmClientId(null);
        setConfirmDeleteText("");

        // Hent endelig sandhed fra backend.
        await Promise.all([
          fetchClients(true, false),
          fetchDeletedClients(false),
        ]);
      } catch (err) {
        showSnackbar(
          "Kunne ikke fjerne klient: " + (err?.message || err),
          "error",
        );
      } finally {
        setRemovingClientId(null);
      }
    },
    [fetchClients, fetchDeletedClients, removeReason, showSnackbar],
  );

  const confirmRemoveClient = useCallback(async () => {
    if (confirmClientId !== null && confirmClientId !== undefined) {
      await handleRemoveClient(confirmClientId);
    }
  }, [confirmClientId, handleRemoveClient]);

  const onDragStart = useCallback(() => {
    if (!canManageClients) return;
    isDraggingRef.current = true;
  }, [canManageClients]);

  const onDragEnd = useCallback(
    async (result) => {
      if (!canManageClients) {
        isDraggingRef.current = false;
        return;
      }

      if (!result.destination) {
        isDraggingRef.current = false;
        return;
      }

      if (result.destination.index === result.source.index) {
        isDraggingRef.current = false;
        return;
      }

      const reordered = Array.from(dragClients);
      const [removed] = reordered.splice(result.source.index, 1);
      reordered.splice(result.destination.index, 0, removed);

      // Opdater UI øjeblikkeligt, men hold polling pauset indtil save er færdig.
      setDragClients(reordered);
      setSavingSort(true);

      try {
        await Promise.all(
          reordered.map((client, i) =>
            updateClient(client.id, { sort_order: i + 1 }),
          ),
        );

        showSnackbar("Sortering opdateret!", "success");

        isDraggingRef.current = false;
        await fetchClients(true, false);
      } catch (err) {
        showSnackbar(
          "Kunne ikke opdatere sortering: " + (err?.message || err),
          "error",
        );

        isDraggingRef.current = false;
        await fetchClients(true, false);
      } finally {
        isDraggingRef.current = false;
        setSavingSort(false);
      }
    },
    [dragClients, fetchClients, showSnackbar, canManageClients],
  );

  const handleRestoreClient = useCallback(
    async (clientId) => {
      setRestoringClientId(clientId);
      try {
        await restoreClient(clientId);
        showSnackbar("Klient gendannet.", "success");
        await Promise.all([
          fetchClients(true, false),
          fetchDeletedClients(false),
        ]);
      } catch (err) {
        showSnackbar(
          "Kunne ikke gendanne klient: " + (err?.message || err),
          "error",
        );
      } finally {
        setRestoringClientId(null);
      }
    },
    [fetchClients, fetchDeletedClients, showSnackbar],
  );

  const openPurgeDialog = useCallback((clientId) => {
    if (
      typeof document !== "undefined" &&
      document.activeElement instanceof HTMLElement
    ) {
      document.activeElement.blur();
    }
    setPurgeClientId(clientId);
    setPurgeConfirmText("");
    setPurgeDialogOpen(true);
  }, []);

  const closePurgeDialog = useCallback(() => {
    if (purgingClientId) return;
    setPurgeDialogOpen(false);
    setPurgeClientId(null);
    setPurgeConfirmText("");
  }, [purgingClientId]);

  const handlePurgeClient = useCallback(async () => {
    if (!selectedClientForPurge) return;
    const clientId = selectedClientForPurge.id;
    setPurgingClientId(clientId);
    try {
      await purgeClient(clientId);
      setDeletedClients((prev) =>
        prev.filter((client) => client.id !== clientId),
      );
      showSnackbar("Klient slettet permanent.", "success");
      setPurgeDialogOpen(false);
      setPurgeClientId(null);
      setPurgeConfirmText("");
    } catch (err) {
      showSnackbar(
        "Kunne ikke slette permanent: " + (err?.message || err),
        "error",
      );
    } finally {
      setPurgingClientId(null);
    }
  }, [selectedClientForPurge, showSnackbar]);

  const handleOrganizationChange = useCallback((clientId, organizationId) => {
    setOrganizationSelections((prev) => ({
      ...prev,
      [clientId]: organizationId,
    }));
  }, []);

  const handleApproveClient = useCallback(
    async (clientId) => {
      const organizationId = organizationSelections[clientId];

      if (!organizationId) {
        showSnackbar("Vælg en organisation først!", "warning");
        return;
      }

      setApprovingClientId(clientId);

      try {
        await approveClient(clientId, organizationId);
        showSnackbar("Klient godkendt!", "success");

        setOrganizationSelections((prev) => {
          const next = { ...prev };
          delete next[clientId];
          return next;
        });

        await fetchClients(true, true);
      } catch (err) {
        showSnackbar(
          "Kunne ikke godkende klient: " + (err?.message || err),
          "error",
        );
      } finally {
        setApprovingClientId(null);
      }
    },
    [organizationSelections, fetchClients, showSnackbar],
  );

  const getOrganizationName = useCallback(
    (organizationId) => {
      const organization = organizations.find(
        (item) => String(item.id) === String(organizationId),
      );
      return organization ? (
        organization.name
      ) : (
        <span style={{ color: "rgba(203,213,225,0.62)" }}>
          Ingen organisation
        </span>
      );
    },
    [organizations],
  );

  // ---------------------------------------------------------------------------
  // Mobil-række renderer
  // ---------------------------------------------------------------------------
  const renderMobileRow = useCallback(
    (client, _idx, provided, snapshot) => (
      <TableRow
        ref={provided?.innerRef}
        {...(provided ? provided.draggableProps : {})}
        style={{
          ...provided?.draggableProps?.style,
          background: snapshot?.isDragging
            ? "rgba(56,189,248,0.14)"
            : undefined,
        }}
        hover
      >
        {canViewClientId && <TableCell>{client.id}</TableCell>}
        <TableCell>
          <Stack direction="column" spacing={0.5}>
            <Typography sx={{ fontWeight: 600 }}>{client.name}</Typography>
            {client.locality && (
              <Typography
                sx={{ fontSize: "0.92em", color: "rgba(203,213,225,0.62)" }}
              >
                {client.locality}
              </Typography>
            )}
            <Typography sx={{ fontSize: "0.92em" }}>
              {getOrganizationName(getClientOrganizationId(client))}
            </Typography>
          </Stack>
        </TableCell>
        <TableCell align="center">
          <ClientStatusCell
            isOnline={getClientOnline(client)}
            client={client}
          />
        </TableCell>
        <TableCell align="center">
          <Button
            component={Link}
            to={`/clients/${client.id}`}
            variant="outlined"
            size="small"
            sx={{ textTransform: "none", whiteSpace: "nowrap" }}
          >
            Control Room
          </Button>
        </TableCell>
        {canManageClients && (
          <TableCell align="center">
            <Tooltip title="Fjern klient">
              <span>
                <IconButton
                  color="error"
                  onClick={() => openRemoveDialog(client.id)}
                  size="small"
                  disabled={removingClientId === client.id}
                >
                  {removingClientId === client.id ? (
                    <CircularProgress size={18} />
                  ) : (
                    <DeleteIcon />
                  )}
                </IconButton>
              </span>
            </Tooltip>
          </TableCell>
        )}
        {canManageClients && (
          <TableCell
            align="right"
            {...provided?.dragHandleProps}
            sx={{ cursor: "grab", width: 45 }}
          >
            <span style={{ fontSize: 20 }}>☰</span>
          </TableCell>
        )}
      </TableRow>
    ),
    [
      canViewClientId,
      canManageClients,
      getOrganizationName,
      openRemoveDialog,
      removingClientId,
    ],
  );

  const removalRequiresTypedId =
    !!selectedClientForRemoval &&
    (selectedClientForRemoval.status === "approved" ||
      getClientOnline(selectedClientForRemoval));

  const removalTypedIdMatches =
    !removalRequiresTypedId ||
    String(confirmDeleteText).trim() ===
      String(selectedClientForRemoval?.id ?? "");

  const canConfirmRemoval =
    !!selectedClientForRemoval && !removingClientId && removalTypedIdMatches;

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const colSpanApproved = canManageClients
    ? isMobile
      ? 6
      : 8
    : isMobile
      ? 3
      : 5;

  return (
    <Box
      sx={{
        ...pageShellSx,
        position: "relative",
        minHeight: "60vh",
        color: "#f8fafc",
      }}
    >
      {/* Snackbar */}
      <AppSnackbar
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={handleCloseSnackbar}
      />
      {/* Bekræftelsesdialog */}
      <Dialog
        open={confirmOpen}
        onClose={closeRemoveDialog}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Fjern klient?</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5}>
            {selectedClientForRemoval && (
              <Paper
                variant="outlined"
                sx={{
                  p: 2,
                  bgcolor: "rgba(15,23,42,0.52)",
                  borderColor: "rgba(148,163,184,0.18)",
                  borderRadius: 2,
                }}
              >
                <Typography sx={{ fontWeight: 700 }}>
                  #{selectedClientForRemoval.id} ·{" "}
                  {getClientDisplayName(selectedClientForRemoval)}
                </Typography>
                <Typography variant="body2" sx={{
                  color: "text.secondary"
                }}>
                  Status: {selectedClientForRemoval.status || "ukendt"}
                </Typography>
                <Typography variant="body2" sx={{
                  color: "text.secondary"
                }}>
                  Online:{" "}
                  {getClientOnline(selectedClientForRemoval) ? "Ja" : "Nej"}
                </Typography>
                <Typography variant="body2" sx={{
                  color: "text.secondary"
                }}>
                  Lokation:{" "}
                  {getClientLocality(selectedClientForRemoval) ||
                    "ikke angivet"}
                </Typography>
              </Paper>
            )}

            <TextField
              size="small"
              fullWidth
              multiline
              minRows={2}
              label="Årsag til papirkurv"
              placeholder="Valgfrit — fx udskiftet klient, fejlregistrering eller testklient."
              value={removeReason}
              onChange={(e) => setRemoveReason(e.target.value.slice(0, 500))}
              disabled={!!removingClientId}
              helperText={`${removeReason.trim().length}/500 tegn · Gemmes i kolonnen Årsag i papirkurven.`}
            />

            {getClientOnline(selectedClientForRemoval) && (
              <MuiAlert severity="error">
                Klienten ser ud til at være online. Slet kun en online klient,
                hvis du er sikker på, at den skal fjernes fra driften.
              </MuiAlert>
            )}

            {removalRequiresTypedId && selectedClientForRemoval && (
              <TextField
                size="small"
                fullWidth
                label={`Skriv klient-ID ${selectedClientForRemoval.id} for at bekræfte`}
                value={confirmDeleteText}
                onChange={(e) => setConfirmDeleteText(e.target.value)}
                disabled={!!removingClientId}
                error={!!confirmDeleteText && !removalTypedIdMatches}
                helperText={
                  removalTypedIdMatches ? " " : "Klient-ID matcher ikke."
                }
              />
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeRemoveDialog} disabled={!!removingClientId}>
            Annullér
          </Button>
          <Button
            onClick={confirmRemoveClient}
            color="error"
            variant="contained"
            disabled={!canConfirmRemoval}
            startIcon={
              removingClientId ? (
                <CircularProgress size={18} color="inherit" />
              ) : (
                <DeleteIcon />
              )
            }
          >
            {removingClientId ? "Flytter..." : "Flyt til papirkurv"}
          </Button>
        </DialogActions>
      </Dialog>
      {/* Permanent slet-dialog */}
      <Dialog
        open={purgeDialogOpen}
        onClose={closePurgeDialog}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Slet klient permanent?</DialogTitle>
        <DialogContent>
          <Stack spacing={1.5}>
            <MuiAlert severity="error">
              Denne handling kan ikke fortrydes. Kalenderdata slettes,
              enrollment-link frakobles, og klientrækken fjernes fysisk fra
              databasen.
            </MuiAlert>

            {selectedClientForPurge && (
              <Paper
                variant="outlined"
                sx={{
                  p: 2,
                  bgcolor: "rgba(15,23,42,0.52)",
                  borderColor: "rgba(148,163,184,0.18)",
                  borderRadius: 2,
                }}
              >
                <Typography sx={{ fontWeight: 700 }}>
                  #{selectedClientForPurge.id} ·{" "}
                  {getClientDisplayName(selectedClientForPurge)}
                </Typography>
                <Typography variant="body2" sx={{
                  color: "text.secondary"
                }}>
                  Slettet:{" "}
                  {(() => {
                    const ts = formatTimestamp(
                      selectedClientForPurge.deleted_at,
                    );
                    return ts.date ? `${ts.date} ${ts.time}` : "ukendt";
                  })()}
                </Typography>
                <Typography variant="body2" sx={{
                  color: "text.secondary"
                }}>
                  Slettet af: {getDeletedByLabel(selectedClientForPurge)}
                </Typography>
              </Paper>
            )}

            {selectedClientForPurge && (
              <TextField
                size="small"
                fullWidth
                label={`Skriv klient-ID ${selectedClientForPurge.id} for at slette permanent`}
                value={purgeConfirmText}
                onChange={(e) => setPurgeConfirmText(e.target.value)}
                disabled={!!purgingClientId}
                error={
                  !!purgeConfirmText &&
                  String(purgeConfirmText).trim() !==
                    String(selectedClientForPurge.id)
                }
                helperText={
                  String(purgeConfirmText).trim() ===
                  String(selectedClientForPurge.id)
                    ? " "
                    : "Klient-ID matcher ikke."
                }
              />
            )}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={closePurgeDialog} disabled={!!purgingClientId}>
            Annullér
          </Button>
          <Button
            onClick={handlePurgeClient}
            color="error"
            variant="contained"
            disabled={
              !selectedClientForPurge ||
              !!purgingClientId ||
              String(purgeConfirmText).trim() !==
                String(selectedClientForPurge.id)
            }
            startIcon={
              purgingClientId ? (
                <CircularProgress size={18} color="inherit" />
              ) : (
                <DeleteForeverIcon />
              )
            }
          >
            {purgingClientId ? "Sletter..." : "Slet permanent"}
          </Button>
        </DialogActions>
      </Dialog>
      {/* Sideheader */}
      <Paper elevation={0} sx={pageHeaderPaperSx}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={1.5}
          sx={{
            alignItems: { xs: "stretch", md: "flex-end" },
            justifyContent: "space-between"
          }}>
          <Stack direction="row" spacing={1.35} sx={{
            alignItems: "center"
          }}>
            <Box sx={pageHeaderIconSx}>
              <DevicesIcon />
            </Box>
            <Box sx={{
              minWidth: 0
            }}>
              <Typography
                variant="h4"
                sx={{
                  fontWeight: 950,
                  letterSpacing: -0.7,
                  fontSize: { xs: "1.55rem", sm: "2rem", md: "2.35rem" },
                }}
              >
                Control Room
              </Typography>
              <Typography sx={{ color: "rgba(203,213,225,0.68)", mt: 0.35 }}>
                Se skærme, status, godkendelser og papirkurv på tværs af
                organisationer.
              </Typography>
            </Box>
          </Stack>

          <Tooltip title="Opdater hele siden">
            <span>
              <Button
                startIcon={
                  refreshing ? (
                    <CircularProgress size={20} color="inherit" />
                  ) : (
                    <RefreshIcon />
                  )
                }
                onClick={handleRefresh}
                disabled={refreshing || savingSort}
                variant="contained"
                sx={{
                  minHeight: 42,
                  borderRadius: 2,
                  fontWeight: 900,
                  width: { xs: "100%", md: "auto" },
                }}
              >
                {refreshing ? "Opdaterer..." : "Opdater"}
              </Button>
            </span>
          </Tooltip>
        </Stack>
      </Paper>
      {/* Godkendte klienter */}
      <Typography
        variant="h5"
        sx={{
          mb: 2,
          fontWeight: 700,
          fontSize: { xs: "1.1rem", sm: "1.4rem" },
        }}
      >
        Godkendte klienter
      </Typography>
      {/* Godkendte klienter */}
      <Paper
        sx={{
          mb: 4,
          px: { xs: 0.5, sm: 0 },
          borderRadius: 2,
          overflow: "hidden",
          bgcolor: "rgba(15,23,42,0.74)",
          border: "1px solid rgba(148,163,184,0.16)",
          boxShadow: "0 24px 80px rgba(0,0,0,0.22)",
        }}
      >
        <TableContainer style={{ position: "relative" }}>
          {(loading || savingSort) && (
            <Box
              sx={{
                position: "absolute",
                left: 0,
                top: 0,
                right: 0,
                bottom: 0,
                background: "rgba(2,6,23,0.68)",
                display: "flex",
                flexDirection: "column",
                gap: 1,
                alignItems: "center",
                justifyContent: "center",
                zIndex: 10,
              }}
            >
              <CircularProgress />
              {savingSort && (
                <Typography variant="body2">Gemmer sortering...</Typography>
              )}
            </Box>
          )}

          <DragDropContext onDragStart={onDragStart} onDragEnd={onDragEnd}>
            <Droppable droppableId="clients-droppable">
              {(provided) => (
                <Table
                  size="small"
                  ref={provided.innerRef}
                  {...provided.droppableProps}
                  sx={{
                    minWidth: 300,
                    "& td, & th": {
                      py: { xs: 1, sm: 1.2 },
                      px: { xs: 0.5, sm: 2 },
                      fontSize: { xs: "0.98em", sm: "0.875rem" },
                      borderColor: "rgba(148,163,184,0.12)",
                      color: "rgba(226,232,240,0.92)",
                    },
                    "& tbody tr:hover": {
                      backgroundColor: "rgba(56,189,248,0.08)",
                    },
                  }}
                >
                  <TableHead>
                    <TableRow
                      sx={{
                        background: "rgba(15,23,42,0.92)",
                        "& th": {
                          fontWeight: 700,
                          fontSize: { xs: "1em", sm: "0.875rem" },
                          whiteSpace: { xs: "nowrap", sm: "normal" },
                          color: "rgba(226,232,240,0.95)",
                        },
                      }}
                    >
                      {isMobile ? (
                        [
                          ...(canViewClientId ? ["ID"] : []),
                          "Klientnavn",
                          "Status",
                          "Control Room",
                          ...(canManageClients ? ["Fjern", "Sort"] : []),
                        ].map((header, idx) => (
                          <TableCell key={header + idx}>{header}</TableCell>
                        ))
                      ) : (
                        <>
                          {canViewClientId && <TableCell>Klient ID</TableCell>}
                          <TableCell>Klientnavn</TableCell>
                          <TableCell>Lokalitet</TableCell>
                          <TableCell sx={{ textAlign: "center" }}>
                            Status
                          </TableCell>
                          <TableCell sx={{ textAlign: "center" }}>
                            Organisation
                          </TableCell>
                          <TableCell sx={{ textAlign: "center" }}>
                            Control Room
                          </TableCell>
                          {canManageClients && (
                            <TableCell sx={{ textAlign: "center" }}>
                              Fjern
                            </TableCell>
                          )}
                          {canManageClients && (
                            <TableCell sx={{ width: 60, textAlign: "right" }}>
                              Sortering
                            </TableCell>
                          )}
                        </>
                      )}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {dragClients.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={colSpanApproved} align="center">
                          Ingen godkendte klienter.
                        </TableCell>
                      </TableRow>
                    ) : (
                      dragClients.map((client, idx) => (
                        <Draggable
                          key={client.id}
                          draggableId={String(client.id)}
                          index={idx}
                          isDragDisabled={
                            !canManageClients ||
                            savingSort ||
                            !!removingClientId
                          }
                        >
                          {(provided, snapshot) =>
                            isMobile ? (
                              renderMobileRow(client, idx, provided, snapshot)
                            ) : (
                              <TableRow
                                ref={provided.innerRef}
                                {...provided.draggableProps}
                                style={{
                                  ...provided.draggableProps.style,
                                  background: snapshot.isDragging
                                    ? "rgba(56,189,248,0.14)"
                                    : undefined,
                                }}
                                hover
                              >
                                {canManageClients && (
                                  <TableCell>{client.id}</TableCell>
                                )}
                                <TableCell>{client.name}</TableCell>
                                <TableCell>
                                  {client.locality || (
                                    <span
                                      style={{
                                        color: "rgba(203,213,225,0.62)",
                                      }}
                                    >
                                      Ingen lokalitet
                                    </span>
                                  )}
                                </TableCell>
                                <TableCell align="center">
                                  <ClientStatusCell
                                    isOnline={getClientOnline(client)}
                                    client={client}
                                  />
                                </TableCell>
                                <TableCell align="center">
                                  {getOrganizationName(
                                    getClientOrganizationId(client),
                                  )}
                                </TableCell>
                                <TableCell align="center">
                                  <Button
                                    component={Link}
                                    to={`/clients/${client.id}`}
                                    variant="outlined"
                                    size="small"
                                    sx={{
                                      textTransform: "none",
                                      whiteSpace: "nowrap",
                                    }}
                                  >
                                    Control Room
                                  </Button>
                                </TableCell>
                                {canManageClients && (
                                  <TableCell align="center">
                                    <Tooltip title="Fjern klient">
                                      <span>
                                        <IconButton
                                          color="error"
                                          onClick={() =>
                                            openRemoveDialog(client.id)
                                          }
                                          disabled={
                                            removingClientId === client.id
                                          }
                                        >
                                          {removingClientId === client.id ? (
                                            <CircularProgress size={20} />
                                          ) : (
                                            <DeleteIcon />
                                          )}
                                        </IconButton>
                                      </span>
                                    </Tooltip>
                                  </TableCell>
                                )}
                                {canManageClients && (
                                  <TableCell
                                    align="right"
                                    {...provided.dragHandleProps}
                                    sx={{ cursor: "grab", width: 60 }}
                                  >
                                    <span style={{ fontSize: 20 }}>☰</span>
                                  </TableCell>
                                )}
                              </TableRow>
                            )
                          }
                        </Draggable>
                      ))
                    )}
                    {provided.placeholder}
                  </TableBody>
                </Table>
              )}
            </Droppable>
          </DragDropContext>
        </TableContainer>
      </Paper>
      {/* Ikke-godkendte klienter — kun admin */}
      {canManageClients && (
        <>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            sx={{
              alignItems: { xs: "flex-start", sm: "center" },
              justifyContent: "space-between",
              mb: 2,
              gap: 1
            }}>
            <Box>
              <Typography
                variant="h5"
                sx={{
                  fontWeight: 700,
                  fontSize: { xs: "1.1rem", sm: "1.4rem" },
                }}
              >
                Ikke godkendte klienter
              </Typography>
            </Box>

            <Chip
              icon={<PendingActionsIcon />}
              label={`${unapprovedClients.length} afventer`}
              sx={compactDarkChipSx(
                unapprovedClients.length ? "warning" : "neutral",
              )}
            />
          </Stack>

          <Paper
            sx={{
              px: { xs: 0.5, sm: 0 },
              borderRadius: 2,
              overflow: "hidden",
              bgcolor: "rgba(15,23,42,0.74)",
              border: "1px solid rgba(148,163,184,0.16)",
              boxShadow: "0 24px 80px rgba(0,0,0,0.22)",
            }}
          >
            <TableContainer>
              <Table
                size="small"
                sx={{
                  minWidth: 300,
                  "& td, & th": {
                    py: { xs: 1, sm: 1.2 },
                    px: { xs: 0.5, sm: 2 },
                    fontSize: { xs: "0.98em", sm: "0.875rem" },
                    borderColor: "rgba(148,163,184,0.12)",
                    color: "rgba(226,232,240,0.92)",
                  },
                  "& tbody tr:hover": {
                    backgroundColor: "rgba(56,189,248,0.08)",
                  },
                }}
              >
                <TableHead>
                  <TableRow
                    sx={{
                      background: "rgba(15,23,42,0.92)",
                      "& th": {
                        fontWeight: 700,
                        fontSize: { xs: "1em", sm: "0.875rem" },
                        whiteSpace: { xs: "nowrap", sm: "normal" },
                      },
                    }}
                  >
                    <TableCell>Klient ID</TableCell>
                    <TableCell>Installationsoplysninger</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell>IP-adresser</TableCell>
                    <TableCell>MAC-adresser</TableCell>
                    <TableCell>Tilføjet</TableCell>
                    <TableCell>Organisation</TableCell>
                    <TableCell sx={{ textAlign: "center" }}>Godkend</TableCell>
                    <TableCell sx={{ textAlign: "center" }}>Fjern</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {unapprovedClients.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={9} align="center">
                        Ingen ikke-godkendte klienter.
                      </TableCell>
                    </TableRow>
                  ) : (
                    unapprovedClients.map((client) => {
                      const statusChip = getClientStatusChipProps(
                        client.status,
                      );
                      const isApproving = approvingClientId === client.id;
                      const isRemoving = removingClientId === client.id;

                      return (
                        <TableRow key={client.id} hover>
                          <TableCell>
                            <Stack
                              direction="row"
                              spacing={0.5}
                              sx={{
                                alignItems: "center"
                              }}
                            >
                              <Typography sx={{ fontWeight: 700 }}>
                                {client.id}
                              </Typography>
                              <CopyIconButton value={client.id} iconSize={14} />
                            </Stack>
                          </TableCell>
                          <TableCell>
                            <EnrollmentIdentityCell client={client} />
                          </TableCell>
                          <TableCell>
                            <Chip
                              size="small"
                              label={statusChip.label}
                              sx={compactDarkChipSx(statusChip.color)}
                            />
                          </TableCell>
                          <TableCell>
                            <Stack spacing={0.25}>
                              <Box
                                sx={{
                                  display: "flex",
                                  alignItems: "center",
                                  whiteSpace: "nowrap",
                                }}
                              >
                                <b>WiFi:</b>&nbsp;
                                <span>
                                  {getNetworkDisplayValue(
                                    client,
                                    "wifi_ip_address",
                                  )}
                                </span>
                                <CopyIconButton
                                  value={getNetworkCopyValue(
                                    client,
                                    "wifi_ip_address",
                                  )}
                                  disabled={
                                    !getNetworkCopyValue(
                                      client,
                                      "wifi_ip_address",
                                    )
                                  }
                                  iconSize={14}
                                />
                              </Box>
                              <Box
                                sx={{
                                  display: "flex",
                                  alignItems: "center",
                                  whiteSpace: "nowrap",
                                }}
                              >
                                <b>LAN:</b>&nbsp;
                                <span>
                                  {getNetworkDisplayValue(
                                    client,
                                    "lan_ip_address",
                                  )}
                                </span>
                                <CopyIconButton
                                  value={getNetworkCopyValue(
                                    client,
                                    "lan_ip_address",
                                  )}
                                  disabled={
                                    !getNetworkCopyValue(
                                      client,
                                      "lan_ip_address",
                                    )
                                  }
                                  iconSize={14}
                                />
                              </Box>
                            </Stack>
                          </TableCell>
                          <TableCell>
                            <Stack spacing={0.25}>
                              <Box
                                sx={{
                                  display: "flex",
                                  alignItems: "center",
                                  whiteSpace: "nowrap",
                                }}
                              >
                                <b>WiFi:</b>&nbsp;
                                <span>
                                  {getNetworkDisplayValue(
                                    client,
                                    "wifi_mac_address",
                                  )}
                                </span>
                                <CopyIconButton
                                  value={getNetworkCopyValue(
                                    client,
                                    "wifi_mac_address",
                                  )}
                                  disabled={
                                    !getNetworkCopyValue(
                                      client,
                                      "wifi_mac_address",
                                    )
                                  }
                                  iconSize={14}
                                />
                              </Box>
                              <Box
                                sx={{
                                  display: "flex",
                                  alignItems: "center",
                                  whiteSpace: "nowrap",
                                }}
                              >
                                <b>LAN:</b>&nbsp;
                                <span>
                                  {getNetworkDisplayValue(
                                    client,
                                    "lan_mac_address",
                                  )}
                                </span>
                                <CopyIconButton
                                  value={getNetworkCopyValue(
                                    client,
                                    "lan_mac_address",
                                  )}
                                  disabled={
                                    !getNetworkCopyValue(
                                      client,
                                      "lan_mac_address",
                                    )
                                  }
                                  iconSize={14}
                                />
                              </Box>
                            </Stack>
                          </TableCell>
                          <TableCell>
                            {(() => {
                              const ts = formatTimestamp(client.created_at);
                              return (
                                <span style={{ whiteSpace: "pre-line" }}>
                                  {ts.date || "-"}
                                  {ts.time ? `\n${ts.time}` : ""}
                                </span>
                              );
                            })()}
                          </TableCell>
                          <TableCell>
                            <Select
                              size="small"
                              value={organizationSelections[client.id] || ""}
                              displayEmpty
                              onChange={(e) =>
                                handleOrganizationChange(
                                  client.id,
                                  e.target.value,
                                )
                              }
                              disabled={isApproving || isRemoving}
                              sx={{
                                minWidth: { xs: 95, sm: 140 },
                                fontSize: { xs: "0.97em", sm: "0.875rem" },
                              }}
                            >
                              <MenuItem value="">Vælg organisation</MenuItem>
                              {organizations.map((organization) => (
                                <MenuItem
                                  key={organization.id}
                                  value={organization.id}
                                >
                                  {organization.name}
                                </MenuItem>
                              ))}
                            </Select>
                          </TableCell>
                          <TableCell align="center">
                            <Button
                              variant="contained"
                              color="success"
                              size="small"
                              startIcon={
                                isApproving ? (
                                  <CircularProgress size={16} color="inherit" />
                                ) : (
                                  <AddIcon />
                                )
                              }
                              onClick={() => handleApproveClient(client.id)}
                              disabled={isApproving || isRemoving}
                              sx={{
                                minWidth: 44,
                                fontSize: { xs: "0.97em", sm: "0.875rem" },
                              }}
                            >
                              {isApproving ? "Godkender..." : "Godkend"}
                            </Button>
                          </TableCell>
                          <TableCell align="center">
                            <Tooltip title="Fjern klient">
                              <span>
                                <IconButton
                                  color="error"
                                  onClick={() => openRemoveDialog(client.id)}
                                  size="small"
                                  disabled={isApproving || isRemoving}
                                >
                                  {isRemoving ? (
                                    <CircularProgress size={18} />
                                  ) : (
                                    <DeleteIcon />
                                  )}
                                </IconButton>
                              </span>
                            </Tooltip>
                          </TableCell>
                        </TableRow>
                      );
                    })
                  )}
                </TableBody>
              </Table>
            </TableContainer>
          </Paper>
        </>
      )}
      {/* Papirkurv — superadministrator + Se adgang read-only */}
      {canViewTrash && (
        <Box sx={{ mt: 4 }}>
          <Stack
            direction={{ xs: "column", sm: "row" }}
            sx={{
              alignItems: { xs: "flex-start", sm: "center" },
              justifyContent: "space-between",
              mb: 2,
              gap: 1
            }}>
            <Stack
              direction="row"
              spacing={1}
              useFlexGap
              sx={{
                alignItems: "center",
                flexWrap: "wrap"
              }}>
              <Typography
                variant="h5"
                sx={{
                  fontWeight: 700,
                  fontSize: { xs: "1.1rem", sm: "1.4rem" },
                }}
              >
                Papirkurv
              </Typography>
              <Button
                size="small"
                variant={trashExpanded ? "contained" : "outlined"}
                endIcon={
                  <ExpandMoreIcon
                    sx={{
                      transition: "transform 160ms ease",
                      transform: trashExpanded
                        ? "rotate(180deg)"
                        : "rotate(0deg)",
                    }}
                  />
                }
                onClick={() => setTrashExpanded((value) => !value)}
              >
                {trashExpanded ? "Skjul papirkurv" : "Vis papirkurv"}
              </Button>
            </Stack>

            <Chip
              label={`${deletedClients.length} slettet`}
              sx={compactDarkChipSx(
                deletedClients.length ? "warning" : "neutral",
              )}
            />
          </Stack>

          <Collapse in={trashExpanded} timeout="auto" unmountOnExit>
            <Paper
              sx={{
                px: { xs: 0.5, sm: 0 },
                borderRadius: 2,
                overflow: "hidden",
                bgcolor: "rgba(15,23,42,0.74)",
                border: "1px solid rgba(148,163,184,0.16)",
                boxShadow: "0 24px 80px rgba(0,0,0,0.22)",
              }}
            >
              <TableContainer>
                <Table
                  size="small"
                  sx={{
                    minWidth: 300,
                    "& td, & th": {
                      py: { xs: 1, sm: 1.2 },
                      px: { xs: 0.5, sm: 2 },
                      fontSize: { xs: "0.98em", sm: "0.875rem" },
                      borderColor: "rgba(148,163,184,0.12)",
                      color: "rgba(226,232,240,0.92)",
                    },
                  }}
                >
                  <TableHead>
                    <TableRow sx={{ background: "rgba(15,23,42,0.92)" }}>
                      {canViewClientId && <TableCell>Klient ID</TableCell>}
                      <TableCell>Klient</TableCell>
                      <TableCell>Organisation</TableCell>
                      <TableCell>Slettet</TableCell>
                      <TableCell>Årsag</TableCell>
                      {isSuperadmin && (
                        <TableCell sx={{ textAlign: "center" }}>
                          Gendan
                        </TableCell>
                      )}
                      {isSuperadmin && (
                        <TableCell sx={{ textAlign: "center" }}>
                          Permanent
                        </TableCell>
                      )}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {deletedClients.length === 0 ? (
                      <TableRow>
                        <TableCell
                          colSpan={
                            (canViewClientId ? 1 : 0) +
                            4 +
                            (isSuperadmin ? 2 : 0)
                          }
                          align="center"
                        >
                          Papirkurven er tom.
                        </TableCell>
                      </TableRow>
                    ) : (
                      deletedClients.map((client) => {
                        const ts = formatTimestamp(client.deleted_at);
                        const isRestoring = restoringClientId === client.id;
                        const isPurging = purgingClientId === client.id;
                        return (
                          <TableRow key={client.id} hover>
                            {canViewClientId && (
                              <TableCell>
                                <Stack
                                  direction="row"
                                  spacing={0.5}
                                  sx={{
                                    alignItems: "center"
                                  }}
                                >
                                  <Typography sx={{ fontWeight: 700 }}>
                                    {client.id}
                                  </Typography>
                                  <CopyIconButton
                                    value={client.id}
                                    iconSize={14}
                                  />
                                </Stack>
                              </TableCell>
                            )}
                            <TableCell>
                              <Stack spacing={0.35}>
                                <Typography sx={{ fontWeight: 700 }}>
                                  {getClientDisplayName(client)}
                                </Typography>
                                <Typography
                                  variant="body2"
                                  sx={{
                                    color: "text.secondary"
                                  }}
                                >
                                  {getClientLocality(client) ||
                                    "Ingen lokalitet"}
                                </Typography>
                                {client.deleted_previous_status && (
                                  <Typography
                                    variant="caption"
                                    sx={{
                                      color: "text.secondary"
                                    }}
                                  >
                                    Tidligere status:{" "}
                                    {client.deleted_previous_status}
                                  </Typography>
                                )}
                              </Stack>
                            </TableCell>
                            <TableCell>
                              {getOrganizationName(
                                getClientOrganizationId(client),
                              )}
                            </TableCell>
                            <TableCell>
                              <span style={{ whiteSpace: "pre-line" }}>
                                {ts.date || "-"}
                                {ts.time ? `\n${ts.time}` : ""}
                              </span>
                              <Typography
                                variant="caption"
                                sx={{
                                  color: "text.secondary",
                                  display: "block"
                                }}>
                                {getDeletedByLabel(client)}
                              </Typography>
                            </TableCell>
                            <TableCell>
                              {getDeletedReason(client) || (
                                <span
                                  style={{ color: "rgba(203,213,225,0.62)" }}
                                >
                                  Ingen årsag
                                </span>
                              )}
                            </TableCell>
                            {isSuperadmin && (
                              <TableCell align="center">
                                <Button
                                  size="small"
                                  variant="contained"
                                  color="success"
                                  startIcon={
                                    isRestoring ? (
                                      <CircularProgress
                                        size={16}
                                        color="inherit"
                                      />
                                    ) : (
                                      <RestoreFromTrashIcon />
                                    )
                                  }
                                  onClick={() => handleRestoreClient(client.id)}
                                  disabled={isRestoring || isPurging}
                                >
                                  {isRestoring ? "Gendanner..." : "Gendan"}
                                </Button>
                              </TableCell>
                            )}
                            {isSuperadmin && (
                              <TableCell align="center">
                                <Tooltip title="Slet permanent">
                                  <span>
                                    <IconButton
                                      color="error"
                                      onClick={() => openPurgeDialog(client.id)}
                                      disabled={isRestoring || isPurging}
                                    >
                                      {isPurging ? (
                                        <CircularProgress size={18} />
                                      ) : (
                                        <DeleteForeverIcon />
                                      )}
                                    </IconButton>
                                  </span>
                                </Tooltip>
                              </TableCell>
                            )}
                          </TableRow>
                        );
                      })
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>
          </Collapse>
        </Box>
      )}
    </Box>
  );
}
