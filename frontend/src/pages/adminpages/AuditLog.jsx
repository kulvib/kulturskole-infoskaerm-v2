import * as React from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import HistoryIcon from "@mui/icons-material/History";
import RefreshIcon from "@mui/icons-material/Refresh";
import SearchIcon from "@mui/icons-material/Search";
import ClearIcon from "@mui/icons-material/Clear";
import VisibilityIcon from "@mui/icons-material/Visibility";
import DownloadIcon from "@mui/icons-material/Download";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";

import { useAuth } from "../../auth/AuthProvider";
import { cleanupExpiredAuditLogs, fetchAuditLogs, fetchAuditLogRetention } from "./auditLogService";
import { errorToString } from "./userAdminService";
import { compactDarkChipSx } from "../../utils/chipStyles";
import { embeddedPageShellSx } from "../../utils/layoutStyles";
import { getRoleLabel } from "../../utils/roleUtils";
import AppSnackbar from "../../components/AppSnackbar";


const pageShellSx = { ...embeddedPageShellSx, color: "#f8fafc" };

const pagePaperSx = {
  p: { xs: 1.5, md: 2 },
  mb: 2,
  border: "1px solid rgba(148,163,184,0.16)",
  borderRadius: 2,
  background: "rgba(15,23,42,0.74)",
  color: "#f8fafc",
};

const darkPaperSx = {
  border: "1px solid rgba(148,163,184,0.16)",
  borderRadius: 2,
  background: "rgba(15,23,42,0.74)",
  color: "#f8fafc",
};

const darkSubtlePaperSx = {
  border: "1px solid rgba(148,163,184,0.14)",
  borderRadius: 2,
  background: "rgba(30,41,59,0.46)",
  color: "#f8fafc",
};

const mutedTextSx = { color: "rgba(203,213,225,0.74)" };

const ACTION_META = {
  user_created: { label: "Bruger oprettet", category: "Bruger", color: "success" },
  user_updated: { label: "Bruger ændret", category: "Bruger", color: "info" },
  role_changed: { label: "Rolle ændret", category: "Adgang", color: "error", critical: true },
  email_changed: { label: "Email ændret", category: "Bruger", color: "error", critical: true },
  user_activated: { label: "Bruger aktiveret", category: "Status", color: "success" },
  user_deactivated: { label: "Bruger deaktiveret", category: "Status", color: "warning" },
  user_deleted: { label: "Bruger slettet (historisk)", category: "Bruger", color: "error", critical: true },
  user_permanently_deleted: { label: "Bruger permanent slettet", category: "Bruger", color: "error", critical: true },
  password_changed: { label: "Adgangskode ændret", category: "Adgangskode", color: "secondary" },
  password_reset_completed: { label: "Adgangskode nulstillet", category: "Adgangskode", color: "error", critical: true },
  password_reset_link_requested: { label: "Reset-link sendt", category: "Adgangskode", color: "secondary" },
  password_reset_link_sent_by_admin: { label: "Reset-link sendt og låst ude", category: "Adgangskode", color: "error", critical: true },
  temporary_password_assigned: { label: "Midlertidigt password tildelt", category: "Adgangskode", color: "error", critical: true },
  login_success: { label: "Login gennemført", category: "Login", color: "success" },
  login_failed: { label: "Login afvist", category: "Login", color: "warning" },
  audit_logs_cleanup_expired: { label: "Udløbne logs ryddet", category: "Audit-log", color: "warning" },
  client_created: { label: "Klient oprettet", category: "Klient", color: "success" },
  client_approved: { label: "Klient godkendt", category: "Klient", color: "success" },
  client_organization_changed: { label: "Klient flyttet", category: "Klient", color: "info" },
  client_soft_deleted: { label: "Klient lagt i papirkurv", category: "Klient", color: "warning" },
  client_restored: { label: "Klient gendannet", category: "Klient", color: "success" },
  client_permanently_deleted: { label: "Klient permanent slettet", category: "Klient", color: "error", critical: true },
  client_secret_rotated: { label: "Klienthemmelighed roteret", category: "Adgang", color: "error", critical: true },
  client_secret_revoked: { label: "Klienthemmelighed tilbagekaldt", category: "Adgang", color: "error", critical: true },
  organization_created: { label: "Organisation oprettet", category: "Organisation", color: "success" },
  organization_name_changed: { label: "Organisation omdøbt", category: "Organisation", color: "info" },
  organization_logo_updated: { label: "Organisationslogo ændret", category: "Organisation", color: "info" },
  organization_logo_deleted: { label: "Organisationslogo slettet", category: "Organisation", color: "warning" },
  organization_times_updated: { label: "Organisationstider ændret", category: "Kalender", color: "info" },
  organization_season_times_updated: { label: "Sæsontider ændret", category: "Kalender", color: "info" },
  organization_season_times_applied: { label: "Sæsontider anvendt", category: "Kalender", color: "success" },
  organization_season_times_applied_safely: { label: "Sæsontider anvendt sikkert", category: "Kalender", color: "success" },
  organization_season_calendars_replaced: { label: "Klientkalendere overskrevet", category: "Kalender", color: "error", critical: true },
  organization_deleted: { label: "Organisation slettet", category: "Organisation", color: "error", critical: true },
  enrollment_token_created: { label: "Installationskode oprettet", category: "Installation", color: "success" },
  enrollment_token_revoked: { label: "Installationskode tilbagekaldt", category: "Installation", color: "warning" },
  client_enrolled: { label: "Klient installeret", category: "Installation", color: "success" },
  clientflow_deployment_authorized: { label: "ClientFlow-deployment autoriseret", category: "ClientFlow", color: "warning" },
  clientflow_deployment_cancelled: { label: "ClientFlow-deployment annulleret", category: "ClientFlow", color: "warning" },
  clientflow_update_requested: { label: "ClientFlow-version bestilt (historisk)", category: "ClientFlow", color: "default" },
  clientflow_downgrade_requested: { label: "ClientFlow-nedgradering bestilt (historisk)", category: "ClientFlow", color: "default", critical: true },
};


const SEVERITY_LABELS = {
  info: "Normal",
  warning: "Vigtig",
  critical: "Kritisk",
};

const SEVERITY_COLORS = {
  info: "default",
  warning: "warning",
  critical: "error",
};

const RETENTION_POLICY_TEXT = "Audit-log gemmes i 90 dage.";

const ACTION_OPTIONS = Object.keys(ACTION_META);

const ENTITY_LABELS = {
  user: "Bruger",
  audit_log: "Audit-log",
};

const ENTITY_TYPE_OPTIONS = Object.keys(ENTITY_LABELS);

const ROLE_LABELS = {
  superadmin: "Superadministrator",
  admin: "Administrator",
  superadministrator: "Superadministrator",
  administrator: "Administrator",
  viewer: "Se adgang",
  se: "Se adgang",
  se_adgang: "Se adgang",
  "se adgang": "Se adgang",
  bruger: "Bruger",
};

const FIELD_LABELS = {
  username: "Brugernavn",
  name: "Navn",
  email: "Email",
  email_before: "Tidligere email",
  email_after: "Ny email",
  role: "Rolle",
  actor_role: "Udførers rolle",
  role_before: "Tidligere rolle",
  role_after: "Ny rolle",
  organization_id: "Organisation",
  actor_organization_id: "Udførers organisation",
  target_organization_id: "Målets organisation",
  organization_id_before: "Tidligere organisation",
  organization_id_after: "Ny organisation",
  company_id: "Organisation",
  actor_company_id: "Udførers organisation",
  target_company_id: "Målets organisation",
  company_id_before: "Tidligere organisation",
  company_id_after: "Ny organisation",
  is_admin: "Administratorrolle",
  is_superadmin: "Superadministratorrolle",
  is_viewer: "Se adgang",
  is_active: "Aktiv status",
  previous_is_active: "Tidligere aktiv status",
  must_change_password: "Tvunget adgangskodeskift",
  old_password_invalidated: "Gammelt password låst ude",
  active_sessions_invalidated: "Aktive sessions ugyldiggjort",
  password_reset_token_cleared: "Reset-token ryddet",
};

const SOURCE_LABELS = {
  forgot_password: "Glemt adgangskode",
  reset_link: "Reset-link",
  activation: "Aktivering",
  admin_reset: "Administrator-reset",
};

const STATUS_LABELS = {
  success: "Gennemført",
  failed: "Fejlet",
  failure: "Fejlet",
  error: "Fejl",
};

const LOGIN_REASON_LABELS = {
  unknown_user: "Ukendt bruger",
  wrong_password: "Forkert adgangskode",
  inactive_user: "Deaktiveret konto",
};

function actionMeta(action) {
  return ACTION_META[action] || { label: action || "Ukendt handling", category: "Andet", color: "default" };
}

function actionLabel(action) {
  return actionMeta(action).label;
}

function logIsCritical(log) {
  return Boolean(log?.is_critical || actionMeta(log?.action).critical || log?.severity === "critical");
}

function severityLabel(severity) {
  return SEVERITY_LABELS[severity] || severity || "Normal";
}

function severityColor(severity, isCritical = false) {
  if (isCritical) return "error";
  return SEVERITY_COLORS[severity] || "default";
}

function roleLabel(role) {
  return role ? getRoleLabel(role) : "—";
}

function entityLabel(entityType) {
  return ENTITY_LABELS[entityType] || entityType || "—";
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || "—";
}

function fieldLabel(field) {
  return FIELD_LABELS[field] || field;
}

function sourceLabel(source) {
  return SOURCE_LABELS[source] || source;
}

function loginReasonLabel(reason) {
  return LOGIN_REASON_LABELS[reason] || reason;
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("da-DK", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(date);
}

function formatActor(log) {
  if (log.actor_username) {
    const role = log.actor_role ? ` · ${roleLabel(log.actor_role)}` : "";
    return `${log.actor_username}${role}`;
  }
  return "System/offentlig handling";
}

function formatActorPrimary(log) {
  return log.actor_username || "System/offentlig";
}

function formatTarget(log) {
  if (log.target_username) return log.target_username;
  if (log.entity_label) return log.entity_label;
  if (log.target_user_id) return `Bruger #${log.target_user_id}`;
  if (log.entity_type && log.entity_id) return `${entityLabel(log.entity_type)} #${log.entity_id}`;
  return "—";
}

function formatBoolean(value) {
  if (value === true) return "Ja";
  if (value === false) return "Nej";
  return "—";
}

function formatChangedFields(fields) {
  if (!Array.isArray(fields) || fields.length === 0) return "";
  return fields.map(fieldLabel).join(", ");
}

function formatDetailsShort(log) {
  const details = log?.details;
  if (!details || typeof details !== "object") return "";

  if (details.role_before || details.role_after) {
    return `${roleLabel(details.role_before)} → ${roleLabel(details.role_after)}`;
  }

  if (details.email_before || details.email_after) {
    return `${details.email_before || "—"} → ${details.email_after || "—"}`;
  }

  if (Array.isArray(details.changed_fields) && details.changed_fields.length > 0) {
    return `Ændret: ${formatChangedFields(details.changed_fields)}`;
  }

  if (details.self_service === true) return "Brugeren ændrede selv adgangskoden";
  if (details.self_service === false) return "Adgangskode ændret af administrator";

  if (details.old_password_invalidated || details.active_sessions_invalidated) {
    return "Gammelt password/sessions låst ude";
  }

  if (details.reason) return `Årsag: ${loginReasonLabel(details.reason)}`;

  if (typeof details.deleted_count !== "undefined") {
    return `${details.deleted_count} rækker ryddet`;
  }

  if (details.previous_last_login_at) {
    return `Forrige login: ${formatDate(details.previous_last_login_at)}`;
  }

  if (details.source) return `Kilde: ${sourceLabel(details.source)}`;

  if (typeof details.activation_email_sent === "boolean") {
    return `Aktiveringsmail: ${formatBoolean(details.activation_email_sent)}`;
  }

  const keys = Object.keys(details);
  if (!keys.length) return "";
  return keys.slice(0, 3).map(fieldLabel).join(", ");
}

function formatHumanSummary(log) {
  const target = formatTarget(log);
  const actor = formatActorPrimary(log);
  const details = log.details || {};

  switch (log.action) {
    case "user_created":
      return `${actor} oprettede brugeren ${target}.`;
    case "user_updated": {
      const fields = formatChangedFields(details.changed_fields);
      return fields ? `${actor} ændrede ${fields} for ${target}.` : `${actor} ændrede brugeren ${target}.`;
    }
    case "role_changed":
      return `${actor} ændrede rollen for ${target} fra ${roleLabel(details.role_before)} til ${roleLabel(details.role_after)}.`;
    case "email_changed":
      if (details.email_before || details.email_after) {
        return `${actor} ændrede email for ${target} fra ${details.email_before || "—"} til ${details.email_after || "—"}.`;
      }
      return `${actor} ændrede email for ${target}.`;
    case "user_activated":
      return `${actor} aktiverede brugeren ${target}.`;
    case "user_deactivated":
      return `${actor} deaktiverede brugeren ${target}.`;
    case "user_deleted":
      return `${actor} slettede brugeren ${target}.`;
    case "user_permanently_deleted":
      return `${actor} slettede brugeren ${target} permanent.`;
    case "password_changed":
      return details.self_service ? `${target} ændrede selv sin adgangskode.` : `${actor} ændrede adgangskoden for ${target}.`;
    case "password_reset_completed":
      return `${target} nulstillede adgangskoden via reset-link.`;
    case "password_reset_link_requested":
      return `Der blev sendt reset-link til ${target} via glemt-adgangskode flowet.`;
    case "password_reset_link_sent_by_admin":
      return `${actor} sendte reset-link til ${target} og låste gammelt password/sessions ude.`;
    case "temporary_password_assigned":
      return `${actor} tildelte midlertidigt password til ${target}.`;
    case "login_success":
      return `${target} loggede ind.`;
    case "login_failed":
      return `Login blev afvist for ${target}.`;
    case "audit_logs_cleanup_expired":
      return `${actor} ryddede ${details.deleted_count ?? 0} udløbne audit-log rækker.`;
    case "client_created":
      return `${actor} oprettede klienten ${target}.`;
    case "client_approved":
      return `${actor} godkendte klienten ${target}.`;
    case "client_organization_changed":
      return `${actor} flyttede klienten ${target} til organisation ${details.organization_id_after ?? "ingen"}.`;
    case "client_soft_deleted":
      return `${actor} lagde klienten ${target} i papirkurven.`;
    case "client_restored":
      return `${actor} gendannede klienten ${target}.`;
    case "client_permanently_deleted":
      return `${actor} slettede klienten ${target} permanent.`;
    case "client_secret_rotated":
      return `${actor} roterede klienthemmeligheden for ${target}.`;
    case "client_secret_revoked":
      return `${actor} tilbagekaldte klienthemmeligheden for ${target}.`;
    case "organization_created":
      return `${actor} oprettede organisationen ${target}.`;
    case "organization_name_changed":
      return `${actor} omdøbte organisationen fra ${details.name_before || "—"} til ${details.name_after || target}.`;
    case "organization_season_times_applied_safely":
      return `${actor} anvendte sæsontider sikkert på ${details.updated_clients ?? 0} klient(er) i ${details.season || "den valgte sæson"}; ${details.changed_days ?? 0} dag(e) blev opdateret, og ${details.preserved_manual_days ?? 0} manuel(le) afvigelse(r) blev bevaret.`;
    case "organization_season_calendars_replaced":
      return `${actor} overskrev alle kalenderdata for ${details.updated_clients ?? 0} klient(er) i ${details.season || "den valgte sæson"}.`;
    case "organization_deleted":
      return `${actor} slettede organisationen ${target}.`;
    case "enrollment_token_created":
      return `${actor} oprettede en installationskode til ${target}.`;
    case "enrollment_token_revoked":
      return `${actor} tilbagekaldte installationskoden ${target}.`;
    case "client_enrolled":
      return `Klienten ${target} blev installeret via en installationskode.`;
    default:
      return `${actionLabel(log.action)} for ${target}.`;
  }
}

function hasDetails(log) {
  return Boolean(
    (log.details && Object.keys(log.details).length > 0) ||
    log.user_agent ||
    log.request_ip ||
    log.id
  );
}

function normalizeSearchValue(value) {
  return String(value ?? "").toLowerCase().trim();
}

function logMatchesSearch(log, query) {
  const q = normalizeSearchValue(query);
  if (!q) return true;

  const haystack = [
    log.id,
    log.action,
    actionLabel(log.action),
    actionMeta(log.action).category,
    statusLabel(log.status),
    log.actor_username,
    roleLabel(log.actor_role),
    log.target_username,
    entityLabel(log.entity_type),
    log.entity_label,
    log.request_ip,
    log.request_id,
    log.user_agent,
    severityLabel(log.severity),
    logIsCritical(log) ? "kritisk" : "normal",
    formatDate(log.retain_until),
    formatHumanSummary(log),
    formatDetailsShort(log),
    JSON.stringify(log.details || {}),
  ]
    .map((value) => normalizeSearchValue(value))
    .join(" ");

  return haystack.includes(q);
}

function downloadCsv(logs) {
  const header = [
    "id",
    "tidspunkt",
    "kategori",
    "handling",
    "status",
    "vigtighed",
    "kritisk",
    "gemmes_til",
    "udfoert_af",
    "rolle",
    "maal",
    "ip",
    "request_id",
    "kort_beskrivelse",
    "detaljer",
  ];

  const escapeCell = (value) => {
    const clean = String(value ?? "").replace(/\r?\n/g, " ");
    return `"${clean.replace(/"/g, '""')}"`;
  };

  const rows = logs.map((log) => [
    log.id,
    formatDate(log.created_at),
    actionMeta(log.action).category,
    actionLabel(log.action),
    statusLabel(log.status),
    severityLabel(log.severity),
    logIsCritical(log) ? "Ja" : "Nej",
    formatDate(log.retain_until),
    log.actor_username || "System/offentlig handling",
    roleLabel(log.actor_role),
    formatTarget(log),
    log.request_ip || "",
    log.request_id || "",
    formatHumanSummary(log),
    JSON.stringify(log.details || {}),
  ]);

  const csv = [header, ...rows].map((row) => row.map(escapeCell).join(";")).join("\n");
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `planiq-display-audit-log-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function DetailField({ label, children }) {
  return (
    <Box>
      <Typography variant="caption" sx={{ ...mutedTextSx, fontWeight: 700, textTransform: "uppercase" }}>
        {label}
      </Typography>
      <Typography sx={{ color: "#f8fafc", wordBreak: "break-word" }}>{children || "—"}</Typography>
    </Box>
  );
}

function DetailsDialog({ log, onClose }) {
  if (!log) return null;

  const detailsJson = JSON.stringify(log.details || {}, null, 2);
  const meta = actionMeta(log.action);

  return (
    <Dialog
      open={Boolean(log)}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      slotProps={{
        paper: {
          sx: {
            border: "1px solid rgba(148,163,184,0.22)",
            background: "linear-gradient(180deg, rgba(15,23,42,0.98), rgba(2,6,23,0.98))",
            color: "#f8fafc",
            boxShadow: "0 24px 80px rgba(0,0,0,0.55)",
          },
        }
      }}
    >
      <DialogTitle sx={{ fontWeight: 700, color: "#f8fafc" }}>
        Audit-detaljer
      </DialogTitle>
      <DialogContent dividers sx={{ borderColor: "rgba(148,163,184,0.18)" }}>
        <Stack spacing={2.5}>
          <Paper elevation={0} sx={{ ...darkSubtlePaperSx, p: 2 }}>
            <Stack spacing={1}>
              <Stack
                direction="row"
                spacing={1}
                useFlexGap
                sx={{
                  alignItems: "center",
                  flexWrap: "wrap"
                }}>
                <Chip size="small" label={meta.category} sx={compactDarkChipSx(meta.color)} />
                <Typography variant="h6" sx={{ fontWeight: 700 }}>{meta.label}</Typography>
              </Stack>
              <Typography variant="body2" sx={{ ...mutedTextSx }}>
                {formatHumanSummary(log)}
              </Typography>
            </Stack>
          </Paper>

          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" }, gap: 2 }}>
            <DetailField label="Tidspunkt">{formatDate(log.created_at)}</DetailField>
            <DetailField label="Status">{statusLabel(log.status)}</DetailField>
            <DetailField label="Vigtighed">
              <Chip
                size="small"
                label={logIsCritical(log) ? "Kritisk" : severityLabel(log.severity)}
                sx={compactDarkChipSx(severityColor(log.severity, logIsCritical(log)))}
              />
            </DetailField>
            <DetailField label="Gemmes til">{formatDate(log.retain_until)}</DetailField>
            <DetailField label="Retention">{log.retention_days ? `${log.retention_days} dage` : "—"}</DetailField>
            <DetailField label="Udført af">{formatActor(log)}</DetailField>
            <DetailField label="Mål">{formatTarget(log)}</DetailField>
            <DetailField label="IP-adresse">{log.request_ip}</DetailField>
            <DetailField label="Request-id">{log.request_id}</DetailField>
            <DetailField label="Entitet">{entityLabel(log.entity_type)}{log.entity_id ? ` · ID ${log.entity_id}` : ""}</DetailField>
          </Box>

          {formatDetailsShort(log) && (
            <DetailField label="Kort detalje">{formatDetailsShort(log)}</DetailField>
          )}

          {log.user_agent && (
            <DetailField label="Browser / enhed">
              <Typography component="span" sx={{ fontSize: 13 }}>{log.user_agent}</Typography>
            </DetailField>
          )}

          <Box component="details">
            <Box
              component="summary"
              sx={{
                cursor: "pointer",
                color: "#c4b5fd",
                fontWeight: 800,
                outline: "none",
                "&:hover": { color: "#ddd6fe" },
              }}
            >
              Vis tekniske detaljer
            </Box>
            <Box
              component="pre"
              sx={{
                mt: 1,
                p: 2,
                border: "1px solid rgba(125,211,252,0.28)",
                borderRadius: 2,
                background: "rgba(2,6,23,0.88)",
                color: "#e2e8f0",
                overflow: "auto",
                fontSize: 13,
                lineHeight: 1.55,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                boxShadow: "inset 0 0 0 1px rgba(15,23,42,0.42)",
              }}
            >
              {detailsJson === "{}" ? "Ingen ekstra tekniske detaljer." : detailsJson}
            </Box>
          </Box>
        </Stack>
      </DialogContent>
      <DialogActions sx={{ borderTop: "1px solid rgba(148,163,184,0.18)", px: 3, py: 2 }}>
        <Button onClick={onClose} variant="contained">Luk</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function AuditLog() {
  const { user: me, loading: authLoading, isViewer } = useAuth();
  const isSuperadmin = me?.role === "superadmin" || Boolean(me?.is_superadmin || me?.isSuperadmin);
  const canViewAudit = isSuperadmin || isViewer;
  const token = null;

  const [logs, setLogs] = React.useState([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const [selectedLog, setSelectedLog] = React.useState(null);
  const [refreshTick, setRefreshTick] = React.useState(0);
  const [retentionStatus, setRetentionStatus] = React.useState(null);
  const [retentionLoading, setRetentionLoading] = React.useState(false);
  const [cleanupConfirmOpen, setCleanupConfirmOpen] = React.useState(false);
  const [cleanupLoading, setCleanupLoading] = React.useState(false);
  const [cleanupMessage, setCleanupMessage] = React.useState("");
  const [cleanupSeverity, setCleanupSeverity] = React.useState("success");

  const [filters, setFilters] = React.useState({
    action: "",
    is_critical: "",
    severity: "",
    entity_type: "",
    actor_user_id: "",
    target_user_id: "",
  });
  const [search, setSearch] = React.useState("");
  const [page, setPage] = React.useState(0);
  const [rowsPerPage, setRowsPerPage] = React.useState(50);

  const visibleLogs = React.useMemo(
    () => logs.filter((log) => logMatchesSearch(log, search)),
    [logs, search]
  );

  const hasMore = logs.length === rowsPerPage;
  const firstRowNumber = logs.length ? page * rowsPerPage + 1 : 0;
  const lastRowNumber = page * rowsPerPage + logs.length;
  const activeFilterCount = Object.values(filters).filter(Boolean).length + (search.trim() ? 1 : 0);

  const updateFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setPage(0);
  };

  const clearFilters = () => {
    setFilters({ action: "", is_critical: "", severity: "", entity_type: "", actor_user_id: "", target_user_id: "" });
    setSearch("");
    setPage(0);
  };

  React.useEffect(() => {
    if (authLoading || !canViewAudit) return undefined;

    const controller = new AbortController();

    async function load() {
      setLoading(true);
      setError("");
      try {
        const data = await fetchAuditLogs(token, {
          ...filters,
          limit: rowsPerPage,
          offset: page * rowsPerPage,
          signal: controller.signal,
        });
        setLogs(Array.isArray(data) ? data : []);
      } catch (err) {
        if (err?.name === "AbortError") return;
        setError(errorToString(err));
        setLogs([]);
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }

    load();
    return () => controller.abort();
  }, [authLoading, canViewAudit, filters, page, rowsPerPage, refreshTick]);

  React.useEffect(() => {
    if (authLoading || !canViewAudit) return undefined;

    const controller = new AbortController();

    async function loadRetention() {
      setRetentionLoading(true);
      try {
        const data = await fetchAuditLogRetention(token, { signal: controller.signal });
        setRetentionStatus(data || null);
      } catch (err) {
        if (err?.name !== "AbortError") {
          setRetentionStatus(null);
        }
      } finally {
        if (!controller.signal.aborted) setRetentionLoading(false);
      }
    }

    loadRetention();
    return () => controller.abort();
  }, [authLoading, canViewAudit, refreshTick]);

  const handleCleanupExpiredLogs = async () => {
    setCleanupLoading(true);
    setCleanupMessage("");
    setCleanupSeverity("success");
    try {
      const result = await cleanupExpiredAuditLogs(token);
      const deletedCount = Number(result?.deleted_count || 0);
      setCleanupSeverity("success");
      setCleanupMessage(
        deletedCount === 1
          ? "1 udløben audit-log række blev ryddet."
          : `${deletedCount} udløbne audit-log rækker blev ryddet.`
      );
      setCleanupConfirmOpen(false);
      setRefreshTick((v) => v + 1);
    } catch (err) {
      setCleanupSeverity("error");
      setCleanupMessage(errorToString(err));
    } finally {
      setCleanupLoading(false);
    }
  };

  if (!canViewAudit) {
    return (
      <Box sx={pageShellSx}>
        <Alert severity="warning">
          Audit-loggen er kun tilgængelig for superadministrator og Se adgang.
        </Alert>
      </Box>
    );
  }

  return (
    <Box sx={pageShellSx}>
      <Paper sx={pagePaperSx}>
        <Box sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 2, mb: 2 }}>
        <Box>
          <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.5 }}>
            <HistoryIcon color="primary" />
            <Typography variant="h5" sx={{ fontWeight: 700, color: "#f8fafc" }}>
              Audit-log
            </Typography>
          </Box>
        </Box>

        <Stack
          direction="row"
          spacing={1}
          useFlexGap
          sx={{
            flexWrap: "wrap",
            justifyContent: "flex-end",
            flexShrink: 0
          }}>
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={() => downloadCsv(visibleLogs)}
            disabled={!visibleLogs.length}
          >
            Eksportér CSV
          </Button>
          <Button
            variant="contained"
            startIcon={<RefreshIcon />}
            loading={loading}
            loadingPosition="start"
            onClick={() => setRefreshTick((v) => v + 1)}
            disabled={loading}
          >
            Opdater
          </Button>
        </Stack>
      </Box>

      <Alert severity="info" sx={{ mb: 2 }}>
        {RETENTION_POLICY_TEXT}
      </Alert>

      <AppSnackbar
        open={Boolean(cleanupMessage)}
        message={cleanupMessage}
        severity={cleanupSeverity}
        onClose={() => setCleanupMessage("")}
      />

      <Paper elevation={0} sx={{ ...darkPaperSx, p: 2, mb: 2 }}>
        <Stack
          direction={{ xs: "column", sm: "row" }}
          spacing={1.5}
          sx={{
            alignItems: { xs: "flex-start", sm: "center" },
            justifyContent: "space-between"
          }}>
          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, color: "#f8fafc" }}>
              Retention-oprydning
            </Typography>
            <Typography variant="body2" sx={{ ...mutedTextSx }}>
              {retentionLoading
                ? "Tjekker udløbne audit-log rækker..."
                : `${Number(retentionStatus?.expired_count || 0)} udløbne audit-log rækker kan ryddes.`}
            </Typography>
          </Box>
          <Button
            variant="outlined"
            color="warning"
            startIcon={<DeleteSweepIcon />}
            onClick={() => setCleanupConfirmOpen(true)}
            disabled={!isSuperadmin || cleanupLoading || retentionLoading || !Number(retentionStatus?.expired_count || 0)}
          >
            Ryd udløbne logs
          </Button>
        </Stack>
      </Paper>

      <Paper elevation={0} sx={{ ...darkSubtlePaperSx, p: 2, mb: 2 }}>
        <Stack spacing={1.5}>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1.2fr 1fr 1.8fr auto" }, gap: 1.5, alignItems: "center" }}>
            <TextField
              select
              size="small"
              label="Handling"
              value={filters.action}
              onChange={(e) => updateFilter("action", e.target.value)}
            >
              <MenuItem value="">Alle handlinger</MenuItem>
              {ACTION_OPTIONS.map((action) => (
                <MenuItem key={action} value={action}>{actionLabel(action)}</MenuItem>
              ))}
            </TextField>

            <TextField
              select
              size="small"
              label="Vigtighed"
              value={filters.is_critical}
              onChange={(e) => updateFilter("is_critical", e.target.value)}
            >
              <MenuItem value="">Alle</MenuItem>
              <MenuItem value="true">Kun kritiske</MenuItem>
              <MenuItem value="false">Ikke kritiske</MenuItem>
            </TextField>

            <TextField
              size="small"
              label="Søg i viste rækker"
              placeholder="Søg efter bruger, handling, rolle, IP eller detalje"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              slotProps={{
                input: { startAdornment: <SearchIcon fontSize="small" sx={{ ...mutedTextSx, mr: 1 }} /> }
              }}
            />

            <Tooltip title="Ryd alle filtre">
              <span>
                <Button
                  variant="outlined"
                  startIcon={<ClearIcon />}
                  onClick={clearFilters}
                  disabled={loading || activeFilterCount === 0}
                  sx={{ whiteSpace: "nowrap" }}
                >
                  Ryd filtre{activeFilterCount ? ` (${activeFilterCount})` : ""}
                </Button>
              </span>
            </Tooltip>
          </Box>

          <Box component="details" sx={{ ...mutedTextSx }}>
            <Box component="summary" sx={{ cursor: "pointer", fontWeight: 700 }}>
              Tekniske filtre
            </Box>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr 1fr 1fr" }, gap: 1.5, mt: 1.5 }}>
              <TextField
                select
                size="small"
                label="Severity"
                value={filters.severity}
                onChange={(e) => updateFilter("severity", e.target.value)}
              >
                <MenuItem value="">Alle</MenuItem>
                <MenuItem value="info">Normal</MenuItem>
                <MenuItem value="warning">Vigtig</MenuItem>
                <MenuItem value="critical">Kritisk</MenuItem>
              </TextField>

              <TextField
                select
                size="small"
                label="Entitet"
                value={filters.entity_type}
                onChange={(e) => updateFilter("entity_type", e.target.value)}
              >
                <MenuItem value="">Alle entiteter</MenuItem>
                {ENTITY_TYPE_OPTIONS.map((type) => (
                  <MenuItem key={type} value={type}>{entityLabel(type)}</MenuItem>
                ))}
              </TextField>

              <TextField
                size="small"
                label="Udført af – bruger-id"
                type="number"
                value={filters.actor_user_id}
                onChange={(e) => updateFilter("actor_user_id", e.target.value)}
              />

              <TextField
                size="small"
                label="Mål – bruger-id"
                type="number"
                value={filters.target_user_id}
                onChange={(e) => updateFilter("target_user_id", e.target.value)}
              />
            </Box>
          </Box>
        </Stack>
      </Paper>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

      <Paper elevation={0} sx={{ ...darkPaperSx, overflow: "hidden" }}>
        <Box sx={{ px: 2, py: 1.5, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 2, background: "rgba(15,23,42,0.62)" }}>
          <Typography variant="body2" sx={{ ...mutedTextSx }}>
            {loading
              ? "Henter audit-log..."
              : logs.length
                ? `Viser ${firstRowNumber}-${lastRowNumber}${search ? ` · ${visibleLogs.length} matcher søgningen` : ""}`
                : "Ingen audit-events fundet med de valgte filtre."}
          </Typography>
          <Stack direction="row" spacing={1} sx={{
            alignItems: "center"
          }}>
            <TextField
              select
              size="small"
              label="Rækker"
              value={rowsPerPage}
              onChange={(e) => { setRowsPerPage(Number(e.target.value)); setPage(0); }}
              sx={{ width: 110 }}
            >
              {[25, 50, 100, 250].map((value) => (
                <MenuItem key={value} value={value}>{value}</MenuItem>
              ))}
            </TextField>
            <Button variant="outlined" disabled={loading || page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
              Forrige
            </Button>
            <Button variant="outlined" disabled={loading || !hasMore} onClick={() => setPage((p) => p + 1)}>
              Næste
            </Button>
          </Stack>
        </Box>
        <Divider />

        <TableContainer sx={{ maxHeight: 620 }}>
          <Table stickyHeader size="small" aria-label="Audit-log tabel">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 700 }}>Tidspunkt</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Handling</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Vigtighed</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Beskrivelse</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Udført af</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>Mål</TableCell>
                <TableCell sx={{ fontWeight: 700 }}>IP</TableCell>
                <TableCell align="right" sx={{ fontWeight: 700 }}>Detaljer</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {loading && (
                <TableRow>
                  <TableCell colSpan={8} align="center" sx={{ py: 6 }}>
                    <CircularProgress />
                  </TableCell>
                </TableRow>
              )}

              {!loading && visibleLogs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={8} align="center" sx={{ py: 5, ...mutedTextSx }}>
                    Ingen rækker at vise.
                  </TableCell>
                </TableRow>
              )}

              {!loading && visibleLogs.map((log) => {
                const meta = actionMeta(log.action);
                const critical = logIsCritical(log);
                return (
                  <TableRow
                    key={log.id}
                    hover
                    sx={critical ? { background: "rgba(127,29,29,0.36)", "&:hover": { background: "rgba(127,29,29,0.48)" } } : undefined}
                  >
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{formatDate(log.created_at)}</TableCell>
                    <TableCell>
                      <Stack spacing={0.5} sx={{
                        alignItems: "flex-start"
                      }}>
                        <Chip size="small" label={meta.label} sx={compactDarkChipSx(meta.color)} />
                        <Typography variant="caption" sx={{ ...mutedTextSx }}>
                          {meta.category}
                        </Typography>
                        {log.status && log.status !== "success" && (
                          <Chip size="small" label={statusLabel(log.status)} sx={compactDarkChipSx("warning")} />
                        )}
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <Stack spacing={0.5} sx={{
                        alignItems: "flex-start"
                      }}>
                        <Chip
                          size="small"
                          label={critical ? "Kritisk" : severityLabel(log.severity)}
                          sx={compactDarkChipSx(severityColor(log.severity, critical))}
                        />
                        {log.retain_until && (
                          <Typography variant="caption" sx={{ ...mutedTextSx }}>
                            Gemmes til {formatDate(log.retain_until)}
                          </Typography>
                        )}
                      </Stack>
                    </TableCell>
                    <TableCell sx={{ maxWidth: 380 }}>
                      <Typography variant="body2" title={formatHumanSummary(log)}>
                        {formatHumanSummary(log)}
                      </Typography>
                      {formatDetailsShort(log) && (
                        <Typography variant="caption" sx={{ ...mutedTextSx }}>
                          {formatDetailsShort(log)}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ fontWeight: log.actor_username ? 600 : 400 }}>
                        {formatActorPrimary(log)}
                      </Typography>
                      {log.actor_role && (
                        <Typography variant="caption" sx={{ ...mutedTextSx }}>
                          {roleLabel(log.actor_role)}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ fontWeight: log.target_username ? 600 : 400 }}>
                        {formatTarget(log)}
                      </Typography>
                      {log.entity_type && (
                        <Typography variant="caption" sx={{ ...mutedTextSx }}>
                          {entityLabel(log.entity_type)}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell sx={{ whiteSpace: "nowrap" }}>{log.request_ip || "—"}</TableCell>
                    <TableCell align="right">
                      <Tooltip title="Se detaljer">
                        <span>
                          <IconButton size="small" onClick={() => setSelectedLog(log)} disabled={!hasDetails(log)}>
                            <VisibilityIcon fontSize="small" />
                          </IconButton>
                        </span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      </Paper>
      </Paper>
      <Dialog open={cleanupConfirmOpen} onClose={() => !cleanupLoading && setCleanupConfirmOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle sx={{ fontWeight: 700 }}>Ryd udløbne audit-logs?</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <Alert severity="warning">
              Denne handling sletter kun audit-log rækker, hvor retention-perioden på 90 dage er udløbet.
            </Alert>
            <Typography>
              Der er {Number(retentionStatus?.expired_count || 0)} udløbne audit-log rækker klar til oprydning.
              Handlingen kan ikke fortrydes, men selve oprydningen bliver gemt som en ny audit-log.
            </Typography>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCleanupConfirmOpen(false)} disabled={cleanupLoading}>
            Annuller
          </Button>
          <Button
            variant="contained"
            color="warning"
            startIcon={<DeleteSweepIcon />}
            loading={cleanupLoading}
            loadingPosition="start"
            onClick={handleCleanupExpiredLogs}
            disabled={cleanupLoading}
          >
            Ryd udløbne logs
          </Button>
        </DialogActions>
      </Dialog>
      <DetailsDialog log={selectedLog} onClose={() => setSelectedLog(null)} />
    </Box>
  );
}
