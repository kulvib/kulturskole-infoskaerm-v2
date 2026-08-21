import AppSnackbar from "../../components/AppSnackbar";
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
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TableSortLabel,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import ClearIcon from "@mui/icons-material/Clear";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DeleteForeverIcon from "@mui/icons-material/DeleteForever";
import EditIcon from "@mui/icons-material/Edit";
import FilterListOffIcon from "@mui/icons-material/FilterListOff";
import HistoryIcon from "@mui/icons-material/History";
import PersonOffIcon from "@mui/icons-material/PersonOff";
import RestoreIcon from "@mui/icons-material/Restore";
import SaveIcon from "@mui/icons-material/Check";
import VpnKeyIcon from "@mui/icons-material/VpnKey";

import { useAuth } from "../../auth/AuthProvider";
import * as service from "./userAdminService";
import { fetchAuditLogs } from "./auditLogService";
import { compactDarkChipSx } from "../../utils/chipStyles";
import { embeddedPageShellSx } from "../../utils/layoutStyles";
import { getRoleLabel } from "../../utils/roleUtils";

// ─── Roller ───────────────────────────────────────────────────────────────────
const ROLE_DISPLAY = {
  superadmin: getRoleLabel("superadmin"),
  admin: getRoleLabel("admin"),
  bruger: getRoleLabel("bruger"),
  viewer: getRoleLabel("viewer"),
};

const ROLE_REQUIRES_ORGANIZATION = new Set(["admin", "bruger", "viewer"]);

// ─── Display-farvetema med Worklog-layout ────────────────────────────────────
const COLORS = {
  bg: "transparent",
  panel: "rgba(15, 23, 42, 0.88)",
  panelSoft: "rgba(15, 23, 42, 0.64)",
  panelHover: "rgba(30, 41, 59, 0.78)",
  selected: "rgba(56, 189, 248, 0.16)",
  selectedBorder: "#38bdf8",
  border: "rgba(148, 163, 184, 0.18)",
  borderStrong: "rgba(148, 163, 184, 0.28)",
  text: "#f8fafc",
  muted: "rgba(203, 213, 225, 0.72)",
  cyan: "#38bdf8",
  teal: "#14b8a6",
  green: "#86efac",
  amber: "#fde68a",
  red: "#fca5a5",
};

const pageShellSx = embeddedPageShellSx;

const pagePaperSx = {
  p: { xs: 1.5, md: 2 },
  mb: 2,
};

const highlightRowSx = {
  position: "relative",
  zIndex: 1,
  boxShadow: "inset 0 0 0 2px rgba(56,189,248,0.82), 0 6px 24px rgba(56,189,248,0.22)",
  backgroundColor: "rgba(56,189,248,0.14)",
};

const singleLineSx = {
  display: "block",
  minWidth: 0,
  whiteSpace: "normal",
  overflow: "visible",
  textOverflow: "clip",
  overflowWrap: "anywhere",
  lineHeight: 1.35,
};

const userAdminLayoutSx = {
  display: "grid",
  gridTemplateColumns: { xs: "1fr", lg: "minmax(300px, 2fr) minmax(0, 3fr)" },
  gap: 2,
  alignItems: "start",
};

const userListButtonSx = (selected, inactive) => ({
  width: "100%",
  display: "grid",
  gridTemplateColumns: "minmax(0, 1fr) auto",
  gap: 1.25,
  alignItems: "center",
  textAlign: "left",
  border: 0,
  borderBottom: `1px solid ${COLORS.border}`,
  bgcolor: selected ? COLORS.selected : inactive ? "rgba(15,23,42,0.46)" : COLORS.panel,
  color: COLORS.text,
  cursor: "pointer",
  px: { xs: 1.25, md: 1.5 },
  py: 0.85,
  minHeight: 58,
  borderLeft: selected ? `4px solid ${COLORS.selectedBorder}` : "4px solid transparent",
  transition: "background-color 160ms ease, border-color 160ms ease",
  "&:hover": { bgcolor: selected ? COLORS.selected : COLORS.panelHover },
});

const userListPanelSx = {
  border: `1px solid ${COLORS.border}`,
  borderRadius: 2,
  bgcolor: COLORS.panel,
  overflow: "hidden",
};

const userDetailPanelSx = {
  border: `1px solid ${COLORS.border}`,
  borderRadius: 2,
  bgcolor: COLORS.panel,
  position: { lg: "sticky" },
  top: { lg: 80 },
  overflow: "hidden",
};

const userTableRowSx = (selected, inactive) => ({
  cursor: "pointer",
  bgcolor: selected ? COLORS.selected : inactive ? "rgba(15,23,42,0.46)" : COLORS.panel,
  opacity: inactive ? 0.78 : 1,
  transition: "background-color 160ms ease, box-shadow 180ms ease",
  "&:hover": { bgcolor: selected ? COLORS.selected : COLORS.panelHover },
  "& td:first-of-type": {
    borderLeft: selected ? `4px solid ${COLORS.selectedBorder}` : "4px solid transparent",
  },
  "&.Mui-selected": {
    bgcolor: COLORS.selected,
    "&:hover": { bgcolor: COLORS.selected },
  },
});

const tableHeaderCellSx = {
  fontSize: 12,
  fontWeight: 850,
  color: COLORS.muted,
  bgcolor: COLORS.panelSoft,
  whiteSpace: "nowrap",
  cursor: "pointer",
  userSelect: "none",
  borderBottom: `1px solid ${COLORS.border}`,
};

const tableCellSx = {
  minWidth: 0,
  py: 0.85,
  verticalAlign: "middle",
  borderBottom: `1px solid ${COLORS.border}`,
  color: COLORS.text,
};

const tableMoreButtonSx = {
  textTransform: "none",
  fontWeight: 800,
  whiteSpace: "nowrap",
  borderRadius: 1.25,
  px: 1.25,
  py: 0.35,
};

const userDetailAnimationSx = {
  animation: "userDetailIn 190ms ease-out",
  "@keyframes userDetailIn": {
    from: { opacity: 0, transform: "translateY(8px)" },
    to: { opacity: 1, transform: "translateY(0)" },
  },
};

const viewSwitchSx = {
  animation: "userAdminViewIn 260ms cubic-bezier(0.2, 0, 0, 1)",
  "@keyframes userAdminViewIn": {
    from: { opacity: 0, transform: "translateX(22px) scale(0.985)" },
    to: { opacity: 1, transform: "translateX(0) scale(1)" },
  },
};

const initialsBadgeSx = (inactive = false) => ({
  width: 36,
  height: 36,
  borderRadius: "50%",
  bgcolor: inactive ? "rgba(148,163,184,0.20)" : "rgba(56,189,248,0.18)",
  color: inactive ? COLORS.muted : COLORS.cyan,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 13,
  fontWeight: 900,
  flexShrink: 0,
});

const detailHeaderSx = {
  px: { xs: 1.5, md: 2 },
  py: 2,
  bgcolor: COLORS.panelSoft,
  borderBottom: `1px solid ${COLORS.border}`,
};

const detailBodySx = {
  px: { xs: 1.5, md: 2 },
  py: 2,
};

const detailGridSx = {
  display: "grid",
  gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
  gap: 1.5,
};

const editableInlineFieldSx = {
  bgcolor: COLORS.panelSoft,
  border: `1px solid ${COLORS.borderStrong}`,
  borderRadius: 1.25,
  px: 1,
  py: 0.45,
  transition: "background-color 160ms ease, border-color 160ms ease, box-shadow 160ms ease",
  "&:focus-within": {
    bgcolor: COLORS.selected,
    borderColor: COLORS.cyan,
    boxShadow: "0 0 0 2px rgba(56,189,248,0.14)",
  },
  "& .MuiInputBase-root:before, & .MuiInputBase-root:after": {
    display: "none",
  },
  "& .MuiInputBase-input": {
    py: 0.35,
  },
};

const detailContentShellSx = {
  display: "grid",
  gridTemplateColumns: { xs: "1fr", md: "minmax(0, 1.15fr) minmax(220px, 0.85fr)" },
  gap: 2,
  alignItems: "start",
};

const actionsColumnSx = {
  border: `1px solid ${COLORS.border}`,
  borderRadius: 2,
  bgcolor: COLORS.panelSoft,
  p: 1.5,
  position: { md: "sticky" },
  top: { md: 96 },
};

const visibleActionsGridSx = {
  display: "grid",
  gridTemplateColumns: "1fr",
  gap: 1,
  mt: 1,
};

const visibleActionButtonSx = {
  justifyContent: "flex-start",
  textTransform: "none",
  minHeight: 38,
  borderRadius: 1.5,
  whiteSpace: "nowrap",
};

const filterBarSx = {
  display: "flex",
  flexWrap: "wrap",
  gap: { xs: 1, md: 1.5 },
  alignItems: { xs: "stretch", md: "center" },
  bgcolor: COLORS.panelSoft,
  border: `1px solid ${COLORS.border}`,
  borderRadius: 2,
  px: { xs: 1.25, md: 2 },
  py: { xs: 1, md: 1.25 },
  mb: 2,
};

const filterLabelSx = {
  fontSize: 11,
  fontWeight: 800,
  color: COLORS.muted,
  textTransform: "uppercase",
  letterSpacing: 0.5,
  whiteSpace: "nowrap",
};


const chipBaseSx = compactDarkChipSx("neutral");

const compactChipSx = compactDarkChipSx("neutral", {
  height: 18,
  fontSize: 10,
});

const countChipSx = compactDarkChipSx("info");

const currentUserChipSx = {
  ...compactDarkChipSx("info", { height: 18, fontSize: 10 }),
  flexShrink: 0,
};

const idChipSx = {
  ...compactDarkChipSx("neutral", { height: 18, fontSize: 10 }),
  flexShrink: 0,
};

const toggleGroupSx = {
  flexWrap: { xs: "wrap", md: "nowrap" },
  "& .MuiToggleButton-root": {
    fontSize: 12,
    py: 0.4,
    px: 1.2,
    textTransform: "none",
    border: `1px solid ${COLORS.borderStrong}`,
    color: COLORS.muted,
    "&.Mui-selected": {
      bgcolor: "rgba(59,130,246,0.35)",
      color: COLORS.text,
      borderColor: COLORS.cyan,
      "&:hover": { bgcolor: "rgba(56,189,248,0.28)" },
    },
    "&:hover": { bgcolor: COLORS.panelHover },
  },
};

function SingleLineText({ children, sx = {}, title }) {
  const value = children || "—";
  return (
    <Tooltip title={title ?? String(value)} arrow enterDelay={700}>
      <Box component="span" sx={{ ...singleLineSx, ...sx }}>
        {value}
      </Box>
    </Tooltip>
  );
}

function getInitials(user) {
  const source = String(user?.name || user?.username || user?.email || "?").trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

function DetailField({ label, children }) {
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="caption" sx={{ color: COLORS.muted, fontWeight: 850, textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </Typography>
      <Box sx={{ fontSize: 14, color: COLORS.text, minHeight: 30, display: "flex", alignItems: "center", minWidth: 0, overflowWrap: "anywhere", "& .MuiInputBase-root": { fontSize: 14 } }}>
        {children || "—"}
      </Box>
    </Box>
  );
}

function UserStatusChip({ active }) {
  return (
    <Chip
      size="small"
      label={active ? "Aktiv" : "Inaktiv"}
      sx={compactDarkChipSx(active ? "success" : "error")}
    />
  );
}

function PasswordStatusChip({ mustChange }) {
  return (
    <Chip
      size="small"
      label={mustChange ? "Skal skifte" : "OK"}
      sx={compactDarkChipSx(mustChange ? "warning" : "info")}
    />
  );
}

const AUDIT_ACTION_LABELS = {
  user_created: "Bruger oprettet",
  user_updated: "Bruger ændret",
  role_changed: "Rolle ændret",
  email_changed: "Email ændret",
  user_activated: "Bruger aktiveret",
  user_deactivated: "Bruger deaktiveret",
  user_deleted: "Bruger slettet",
  user_permanently_deleted: "Bruger permanent slettet",
  password_changed: "Adgangskode ændret",
  password_reset_completed: "Adgangskode nulstillet",
  password_reset_link_requested: "Reset-link sendt",
  password_reset_link_sent_by_admin: "Reset-link sendt og låst ude",
  temporary_password_assigned: "Midlertidigt password tildelt",
  login_success: "Login gennemført",
  login_failed: "Login afvist",
  audit_logs_cleanup_expired: "Udløbne logs ryddet",
  client_created: "Klient oprettet",
  client_approved: "Klient godkendt",
  client_organization_changed: "Klient flyttet",
  client_soft_deleted: "Klient lagt i papirkurv",
  client_restored: "Klient gendannet",
  client_permanently_deleted: "Klient permanent slettet",
  client_secret_rotated: "Klienthemmelighed roteret",
  client_secret_revoked: "Klienthemmelighed tilbagekaldt",
  organization_created: "Organisation oprettet",
  organization_name_changed: "Organisation omdøbt",
  organization_logo_updated: "Organisationslogo ændret",
  organization_logo_deleted: "Organisationslogo slettet",
  organization_times_updated: "Organisationstider ændret",
  organization_season_times_updated: "Sæsontider ændret",
  organization_season_times_applied: "Sæsontider anvendt",
  organization_season_times_applied_safely: "Sæsontider anvendt sikkert",
  organization_season_calendars_replaced: "Klientkalendere overskrevet",
  organization_deleted: "Organisation slettet",
  enrollment_token_created: "Installationskode oprettet",
  enrollment_token_revoked: "Installationskode tilbagekaldt",
  client_enrolled: "Klient installeret",
  clientflow_deployment_authorized: "ClientFlow-deployment autoriseret",
  clientflow_deployment_cancelled: "ClientFlow-deployment annulleret",
  clientflow_update_requested: "ClientFlow-version bestilt (historisk)",
  clientflow_downgrade_requested: "ClientFlow-nedgradering bestilt (historisk)",
};

const AUDIT_SEVERITY_LABELS = {
  info: "Normal",
  warning: "Vigtig",
  critical: "Kritisk",
};

function auditActionLabel(action) {
  return AUDIT_ACTION_LABELS[action] || action || "Ukendt handling";
}

function auditSeverityLabel(severity) {
  return AUDIT_SEVERITY_LABELS[severity] || severity || "Normal";
}

function auditSeverityColor(log) {
  if (log?.is_critical || log?.severity === "critical") return "error";
  if (log?.severity === "warning") return "warning";
  return "default";
}

function auditValueToText(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function AuditDetailLine({ label, value, mono = false }) {
  const text = auditValueToText(value);
  return (
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "180px minmax(0, 1fr)" }, gap: 1, py: 0.75, borderBottom: `1px solid ${COLORS.border}` }}>
      <Typography sx={{ fontSize: 12, fontWeight: 850, color: COLORS.muted, textTransform: "uppercase", letterSpacing: 0.35 }}>{label}</Typography>
      <Typography component="pre" sx={{ m: 0, fontSize: 13, color: COLORS.text, whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontFamily: mono ? "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" : "inherit" }}>
        {text}
      </Typography>
    </Box>
  );
}

function auditLogSearchText(log) {
  const actor = log.actor_name || log.actor_username || log.actor_email || log.actor_user_id || "System";
  const target = log.target_user_name || log.target_username || log.target_user_email || log.target_user_id || "";
  return [
    log.id,
    formatLastLogin(log.created_at),
    log.created_at,
    log.action,
    auditActionLabel(log.action),
    log.severity,
    auditSeverityLabel(log.severity),
    log.is_critical === true ? "kritisk ja" : log.is_critical === false ? "kritisk nej" : "",
    log.entity_type,
    log.entity_id,
    actor,
    log.actor_user_id,
    target,
    log.target_user_id,
    log.request_ip || log.ip_address || log.ip,
    log.user_agent,
    log.details,
    log.metadata,
    log.extra,
    log.payload,
  ].map(auditValueToText).join(" ").toLowerCase();
}

function AuditLogDialog({ open, user, logs, loading, error, onClose }) {
  const [auditSearch, setAuditSearch] = React.useState("");

  React.useEffect(() => {
    if (!open) setAuditSearch("");
  }, [open]);

  const filteredLogs = React.useMemo(() => {
    const q = auditSearch.trim().toLowerCase();
    if (!q) return logs;
    return logs.filter((log) => auditLogSearchText(log).includes(q));
  }, [logs, auditSearch]);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ fontWeight: 850 }}>Audit-log for {displayName(user) || user?.username || user?.email || "bruger"}</DialogTitle>
      <DialogContent dividers sx={{ bgcolor: COLORS.panel }}>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}

        <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap", alignItems: "center", mb: 2 }}>
          <TextField
            size="small"
            value={auditSearch}
            onChange={(e) => setAuditSearch(e.target.value)}
            placeholder="Søg i audit-log: handling, dato, ID, bruger, IP, detaljer…"
            sx={{ flex: "1 1 360px" }}
            slotProps={{
              input: {
                endAdornment: auditSearch ? (
                  <InputAdornment position="end">
                    <IconButton size="small" onClick={() => setAuditSearch("")}>
                      <ClearIcon fontSize="small" />
                    </IconButton>
                  </InputAdornment>
                ) : null,
              }
            }}
          />
          <Chip
            size="small"
            sx={compactDarkChipSx("info")}
            label={auditSearch ? `${filteredLogs.length} af ${logs.length} vist` : `${logs.length} logs`}
          />
        </Box>

        {loading ? (
          <Box sx={{ display: "flex", gap: 1, alignItems: "center", py: 3, color: COLORS.text }}>
            <CircularProgress size={18} />
            <Typography>Henter audit-log…</Typography>
          </Box>
        ) : logs.length === 0 ? (
          <Box sx={{ py: 4, textAlign: "center", color: COLORS.muted }}>Ingen audit-log fundet for brugeren.</Box>
        ) : filteredLogs.length === 0 ? (
          <Box sx={{ py: 4, textAlign: "center", color: COLORS.muted }}>Ingen logs matcher søgningen.</Box>
        ) : (
          <Box sx={{ display: "grid", gap: 1, maxHeight: "62vh", overflowY: "auto", pr: 0.5 }}>
            {filteredLogs.map((log) => {
              const actor = log.actor_name || log.actor_username || log.actor_email || log.actor_user_id || "System";
              const target = log.target_user_name || log.target_username || log.target_user_email || log.target_user_id;
              return (
                <Paper key={log.id || `${log.created_at}-${log.action}`} variant="outlined" sx={{ overflow: "hidden", borderRadius: 2, bgcolor: COLORS.panelSoft, borderColor: COLORS.border }}>
                  <Box sx={{ px: 1.5, py: 1.1, bgcolor: COLORS.panelSoft, borderBottom: `1px solid ${COLORS.border}`, display: "grid", gridTemplateColumns: { xs: "1fr", md: "minmax(0, 1fr) auto" }, gap: 1, alignItems: "center" }}>
                    <Box sx={{ minWidth: 0 }}>
                      <Typography sx={{ fontWeight: 850, color: COLORS.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{auditActionLabel(log.action)}</Typography>
                      <Typography sx={{ fontSize: 12, color: COLORS.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {formatLastLogin(log.created_at)} · Udført af {actor}{target ? ` · Mål: ${target}` : ""}
                      </Typography>
                    </Box>
                    <Box sx={{ display: "flex", gap: 0.75, justifyContent: { xs: "flex-start", md: "flex-end" }, flexWrap: "wrap" }}>
                      <Chip size="small" color={auditSeverityColor(log)} variant="outlined" label={auditSeverityLabel(log.severity)} sx={{ height: 24, fontSize: 11 }} />
                      {log.entity_type && <Chip size="small" variant="outlined" label={log.entity_type} sx={{ height: 24, fontSize: 11, color: COLORS.text, borderColor: COLORS.borderStrong }} />}
                      {log.id && <Chip size="small" variant="outlined" label={`Log ${log.id}`} sx={{ height: 24, fontSize: 11, color: COLORS.text, borderColor: COLORS.borderStrong }} />}
                    </Box>
                  </Box>
                  <Box
                    component="details"
                    sx={{
                      px: 1.5,
                      py: 0.75,
                      color: COLORS.text,
                      "& summary": {
                        cursor: "pointer",
                        fontSize: 13,
                        fontWeight: 850,
                        color: COLORS.cyan,
                        listStyle: "none",
                      },
                      "& summary::-webkit-details-marker": { display: "none" },
                    }}
                  >
                    <Box component="summary">Vis alle detaljer</Box>
                    <Box sx={{ pt: 0.75 }}>
                      <AuditDetailLine label="Log-ID" value={log.id} />
                      <AuditDetailLine label="Tidspunkt" value={formatLastLogin(log.created_at)} />
                      <AuditDetailLine label="Handling" value={log.action} />
                      <AuditDetailLine label="Visning" value={auditActionLabel(log.action)} />
                      <AuditDetailLine label="Niveau" value={log.severity} />
                      <AuditDetailLine label="Kritisk" value={log.is_critical === true ? "Ja" : log.is_critical === false ? "Nej" : null} />
                      <AuditDetailLine label="Objekttype" value={log.entity_type} />
                      <AuditDetailLine label="Objekt-ID" value={log.entity_id} />
                      <AuditDetailLine label="Udført af" value={actor} />
                      <AuditDetailLine label="Actor user ID" value={log.actor_user_id} />
                      <AuditDetailLine label="Målbruger" value={target} />
                      <AuditDetailLine label="Målbruger ID" value={log.target_user_id} />
                      <AuditDetailLine label="IP-adresse" value={log.request_ip || log.ip_address || log.ip} />
                      <AuditDetailLine label="User agent" value={log.user_agent} />
                      <AuditDetailLine label="Detaljer" value={log.details ?? log.metadata ?? log.extra ?? log.payload} mono />
                    </Box>
                  </Box>
                </Paper>
              );
            })}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button variant="outlined" onClick={onClose}>Luk</Button>
      </DialogActions>
    </Dialog>
  );
}

function formatLastLogin(value) {
  if (!value) return "Aldrig";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Aldrig";
  return new Intl.DateTimeFormat("da-DK", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function displayName(user) {
  return user?.name || user?.full_name || user?.username || "";
}

function userSearchText(user, orgNameById) {
  return [
    user.id,
    displayName(user),
    user.username,
    user.email,
    ROLE_DISPLAY[user.role] || user.role,
    orgNameById[user.organization_id],
    user.is_active === false ? "inaktiv" : "aktiv",
    user.must_change_password ? "skal skifte password" : "password ok",
    formatLastLogin(user.last_login_at),
  ].join(" ").toLowerCase();
}

export default function UserAdministration() {
  const auth = useAuth();
  const me = auth?.user || auth?.me || null;
  const authLoading = Boolean(auth?.loading);
  const isSuperadmin = Boolean(auth?.isSuperadmin ?? (me?.role === "superadmin"));
  const isAdmin = Boolean((auth?.isAdmin ?? auth?.isAdministrator ?? (me?.role === "admin")) || isSuperadmin);

  const [users, setUsers] = React.useState([]);
  const [organizations, setOrganizations] = React.useState([]);
  const [userLoading, setUserLoading] = React.useState(false);
  const [userError, setUserError] = React.useState("");
  const [userSuccess, setUserSuccess] = React.useState("");

  const [newUser, setNewUser] = React.useState({
    username: "",
    name: "",
    email: "",
    emailRepeat: "",
    role: "bruger",
    organization_id: null,
  });

  const [validation, setValidation] = React.useState({
    emailMatch: true,
    emailValid: true,
    nameValid: true,
    usernameValid: true,
  });

  const [editUserId, setEditUserId] = React.useState(null);
  const [editFields, setEditFields] = React.useState({});
  const [editLoading, setEditLoading] = React.useState(false);
  const [editError, setEditError] = React.useState({});

  const [reloadUsers, setReloadUsers] = React.useState(0);
  const [sortField, setSortField] = React.useState("name");
  const [sortDirection, setSortDirection] = React.useState("asc");
  const [openUserError, setOpenUserError] = React.useState(false);
  const [openUserSuccess, setOpenUserSuccess] = React.useState(false);

  const [statusConfirmOpen, setStatusConfirmOpen] = React.useState(false);
  const [userToChangeStatus, setUserToChangeStatus] = React.useState(null);
  const [nextUserActiveStatus, setNextUserActiveStatus] = React.useState(null);

  const [permanentDeleteOpen, setPermanentDeleteOpen] = React.useState(false);
  const [userToPermanentlyDelete, setUserToPermanentlyDelete] = React.useState(null);
  const [permanentDeleteConfirmation, setPermanentDeleteConfirmation] = React.useState("");
  const [permanentDeleteLoading, setPermanentDeleteLoading] = React.useState(false);

  const [resetMailLoadingUserId, setResetMailLoadingUserId] = React.useState(null);
  const [resetConfirmOpen, setResetConfirmOpen] = React.useState(false);
  const [userToResetPassword, setUserToResetPassword] = React.useState(null);

  const [temporaryPasswordOpen, setTemporaryPasswordOpen] = React.useState(false);
  const [userToReceiveTemporaryPassword, setUserToReceiveTemporaryPassword] = React.useState(null);
  const [temporaryPassword, setTemporaryPassword] = React.useState("");
  const [temporaryPasswordRepeat, setTemporaryPasswordRepeat] = React.useState("");
  const [temporaryPasswordError, setTemporaryPasswordError] = React.useState("");
  const [temporaryPasswordLoading, setTemporaryPasswordLoading] = React.useState(false);

  const [auditLogUserId, setAuditLogUserId] = React.useState(null);
  const [auditLogs, setAuditLogs] = React.useState([]);
  const [auditLogLoading, setAuditLogLoading] = React.useState(false);
  const [auditLogError, setAuditLogError] = React.useState("");

  const [filterText, setFilterText] = React.useState("");
  const [roleFilter, setRoleFilter] = React.useState("all");
  const [activeFilter, setActiveFilter] = React.useState("all");
  const [selectedUserId, setSelectedUserId] = React.useState(null);
  const [detailViewOpen, setDetailViewOpen] = React.useState(false);
  const [highlightedUserId, setHighlightedUserId] = React.useState(null);

  const usernameRef = React.useRef(null);
  const nameRef = React.useRef(null);
  const emailRef = React.useRef(null);

  const highlightUser = React.useCallback((id) => {
    setHighlightedUserId(id);
    window.setTimeout(() => setHighlightedUserId((current) => (current === id ? null : current)), 2200);
    window.setTimeout(() => {
      document.getElementById(`user-row-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }, 50);
  }, []);

  const orgNameById = React.useMemo(() => {
    const map = {};
    organizations.forEach((org) => {
      if (org?.id != null) map[org.id] = org.name;
    });
    return map;
  }, [organizations]);

  const loadData = React.useCallback(async () => {
    if (!isAdmin && !isSuperadmin) return;
    setUserLoading(true);
    setUserError("");
    try {
      const [userData, orgData] = await Promise.all([
        service.fetchUsers(),
        service.fetchOrganizations().catch(() => []),
      ]);
      setUsers(Array.isArray(userData) ? userData : []);
      setOrganizations(Array.isArray(orgData) ? orgData : []);
    } catch (err) {
      setUserError(service.errorToString(err));
      setOpenUserError(true);
    } finally {
      setUserLoading(false);
    }
  }, [isAdmin, isSuperadmin]);

  React.useEffect(() => {
    loadData();
  }, [loadData, reloadUsers]);

  React.useEffect(() => {
    const email = service.normalizeEmail(newUser.email);
    const emailRepeat = service.normalizeEmail(newUser.emailRepeat);
    setValidation({
      usernameValid: service.normalizeUsername(newUser.username).length >= 3,
      nameValid: service.normalizeText(newUser.name).length > 0,
      emailValid: email.length === 0 || service.validateEmail(email),
      emailMatch: emailRepeat.length === 0 || email === emailRepeat,
    });
  }, [newUser]);

  const selectedUser = React.useMemo(
    () => users.find((user) => String(user.id) === String(selectedUserId)) || null,
    [users, selectedUserId]
  );

  const editingUser = React.useMemo(
    () => users.find((user) => String(user.id) === String(editUserId)) || null,
    [users, editUserId]
  );

  const roleRequiresOrganization = (role) => ROLE_REQUIRES_ORGANIZATION.has(role);

  const disableCreate = React.useMemo(() => {
    const username = service.normalizeUsername(newUser.username);
    const name = service.normalizeText(newUser.name);
    const email = service.normalizeEmail(newUser.email);
    const emailRepeat = service.normalizeEmail(newUser.emailRepeat);
    if (!username || username.length < 3) return true;
    if (!name) return true;
    if (!email || !service.validateEmail(email)) return true;
    if (email !== emailRepeat) return true;
    if (roleRequiresOrganization(newUser.role) && !newUser.organization_id && isSuperadmin) return true;
    return false;
  }, [newUser, isSuperadmin]);

  const visibleRoles = React.useMemo(() => {
    const roles = [];
    if (isSuperadmin) roles.push("viewer");
    roles.push("bruger");
    if (isAdmin) roles.push("admin");
    if (isSuperadmin) roles.push("superadmin");
    return roles;
  }, [isAdmin, isSuperadmin]);

  const resetCreateForm = () => {
    setNewUser({
      username: "",
      name: "",
      email: "",
      emailRepeat: "",
      role: "bruger",
      organization_id: isSuperadmin ? null : me?.organization_id ?? null,
    });
  };

  React.useEffect(() => {
    if (!isSuperadmin && me?.organization_id) {
      setNewUser((prev) => ({ ...prev, organization_id: me.organization_id }));
    }
  }, [isSuperadmin, me?.organization_id]);

  const applyUpdatedUser = (updatedUser) => {
    setUsers((prev) => prev.map((user) => (user.id === updatedUser.id ? updatedUser : user)));
    setSelectedUserId(updatedUser.id);
  };

  const handleCreateUser = async (event) => {
    event.preventDefault();
    if (disableCreate || userLoading) return;
    setUserLoading(true);
    setUserError("");
    setUserSuccess("");

    const payload = {
      username: service.normalizeUsername(newUser.username),
      name: service.normalizeText(newUser.name),
      full_name: service.normalizeText(newUser.name),
      email: service.normalizeEmail(newUser.email),
      role: newUser.role,
      is_active: true,
      organization_id: newUser.role === "superadmin" ? null : Number(newUser.organization_id || me?.organization_id || 0) || null,
    };

    try {
      const created = await service.createUser(payload);
      setUsers((prev) => [...prev, created]);
      setUserSuccess(`Bruger oprettet. Aktiveringsmail sendt til ${created.email}.`);
      setOpenUserSuccess(true);
      resetCreateForm();
      setSelectedUserId(created.id);
      setDetailViewOpen(true);
      highlightUser(created.id);
    } catch (err) {
      setUserError(service.errorToString(err));
      setOpenUserError(true);
    } finally {
      setUserLoading(false);
    }
  };

  const handleEditClick = (user) => {
    if (!user) return;
    setEditUserId(user.id);
    setEditFields({
      name: displayName(user),
      email: user.email || "",
      role: user.role || "bruger",
      organization_id: user.organization_id ?? null,
      is_active: user.is_active !== false,
    });
    setEditError({});
  };

  const handleEditCancel = () => {
    setEditUserId(null);
    setEditFields({});
    setEditError({});
    setEditLoading(false);
  };

  const handleEditFieldChange = (field, value) => {
    setEditFields((prev) => {
      const next = { ...prev, [field]: value };
      if (field === "role" && value === "superadmin") next.organization_id = null;
      if (field === "role" && value !== "superadmin" && !isSuperadmin) next.organization_id = me?.organization_id ?? null;
      return next;
    });
    setEditError((prev) => ({ ...prev, [field]: "" }));
  };

  const handleEditSave = async (user) => {
    if (!user || editLoading) return;
    const errors = {};
    const name = service.normalizeText(editFields.name);
    const email = service.normalizeEmail(editFields.email);
    if (!name) errors.name = "Fulde navn skal udfyldes";
    if (!email || !service.validateEmail(email)) errors.email = "Ugyldig email";
    if (roleRequiresOrganization(editFields.role) && !editFields.organization_id && isSuperadmin) {
      errors.organization_id = "Vælg organisation";
    }
    if (Object.keys(errors).length > 0) {
      setEditError(errors);
      return;
    }

    const body = {
      name,
      full_name: name,
      email,
      role: editFields.role,
      is_active: editFields.is_active,
      organization_id: editFields.role === "superadmin" ? null : Number(editFields.organization_id || me?.organization_id || 0) || null,
    };

    setEditLoading(true);
    setUserError("");
    try {
      const updated = await service.patchUser(user.id, body);
      setUserSuccess("Bruger opdateret");
      setOpenUserSuccess(true);
      applyUpdatedUser(updated);
      handleEditCancel();
      highlightUser(updated.id);
    } catch (err) {
      setUserError(service.errorToString(err));
      setOpenUserError(true);
    } finally {
      setEditLoading(false);
    }
  };

  const openPasswordResetDialog = (user) => {
    if (!user?.id) return;
    setUserToResetPassword(user);
    setResetConfirmOpen(true);
  };

  const closePasswordResetDialog = () => {
    if (resetMailLoadingUserId) return;
    setResetConfirmOpen(false);
    setUserToResetPassword(null);
  };

  const confirmSendPasswordResetLink = async () => {
    const target = userToResetPassword;
    if (!target?.id) return;
    setResetMailLoadingUserId(target.id);
    setUserError("");
    setUserSuccess("");
    try {
      await service.sendPasswordResetLink(target.id);
      setUserSuccess(`Nulstillingslink sendt til ${target.email}.`);
      setOpenUserSuccess(true);
      setResetConfirmOpen(false);
      setUserToResetPassword(null);
      setReloadUsers((value) => value + 1);
    } catch (err) {
      setUserError(service.errorToString(err));
      setOpenUserError(true);
    } finally {
      setResetMailLoadingUserId(null);
    }
  };

  const generateTemporaryPassword = () => {
    const generated = service.generatePassword(18);
    setTemporaryPassword(generated);
    setTemporaryPasswordRepeat(generated);
    setTemporaryPasswordError("");
  };

  const copyTemporaryPassword = async () => {
    const value = temporaryPassword.trim();
    if (!value) {
      setTemporaryPasswordError("Der er ikke noget midlertidigt password at kopiere.");
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
      setTemporaryPasswordError("");
      setUserSuccess("Midlertidigt password kopieret.");
      setOpenUserSuccess(true);
    } catch {
      setTemporaryPasswordError("Kunne ikke kopiere passwordet. Markér og kopier det manuelt.");
    }
  };

  const openTemporaryPasswordDialog = (user) => {
    if (!user?.id) return;
    setUserToReceiveTemporaryPassword(user);
    setTemporaryPassword("");
    setTemporaryPasswordRepeat("");
    setTemporaryPasswordError("");
    setTemporaryPasswordOpen(true);
  };

  const closeTemporaryPasswordDialog = () => {
    if (temporaryPasswordLoading) return;
    setTemporaryPasswordOpen(false);
    setUserToReceiveTemporaryPassword(null);
    setTemporaryPassword("");
    setTemporaryPasswordRepeat("");
    setTemporaryPasswordError("");
  };

  const confirmTemporaryPassword = async () => {
    const target = userToReceiveTemporaryPassword;
    if (!target?.id) return;
    if (temporaryPassword.length < 12) {
      setTemporaryPasswordError("Midlertidigt password skal være mindst 12 tegn.");
      return;
    }
    if (temporaryPassword !== temporaryPasswordRepeat) {
      setTemporaryPasswordError("De to passwords er ikke ens.");
      return;
    }
    setTemporaryPasswordLoading(true);
    setTemporaryPasswordError("");
    try {
      await service.assignTemporaryPassword(target.id, temporaryPassword);
      setUserSuccess(`Midlertidigt password tildelt til ${target.email}. Brugeren skal skifte password ved næste login.`);
      setOpenUserSuccess(true);
      setTemporaryPasswordOpen(false);
      setUserToReceiveTemporaryPassword(null);
      setTemporaryPassword("");
      setTemporaryPasswordRepeat("");
      setReloadUsers((value) => value + 1);
    } catch (err) {
      const message = service.errorToString(err);
      setTemporaryPasswordError(message);
      setUserError(message);
      setOpenUserError(true);
    } finally {
      setTemporaryPasswordLoading(false);
    }
  };

  const handleUserStatusClick = (user, nextIsActive) => {
    setUserToChangeStatus(user);
    setNextUserActiveStatus(nextIsActive);
    setStatusConfirmOpen(true);
  };

  const confirmUserStatusChange = async () => {
    setStatusConfirmOpen(false);
    if (!userToChangeStatus || typeof nextUserActiveStatus !== "boolean") return;
    setUserError("");
    try {
      const updated = await service.patchUser(userToChangeStatus.id, { is_active: nextUserActiveStatus });
      setUserSuccess(nextUserActiveStatus ? "Bruger gendannet" : "Bruger deaktiveret");
      setOpenUserSuccess(true);
      applyUpdatedUser(updated);
      highlightUser(updated.id);
    } catch (err) {
      setUserError(service.errorToString(err));
      setOpenUserError(true);
    } finally {
      setUserToChangeStatus(null);
      setNextUserActiveStatus(null);
    }
  };

  const handlePermanentDeleteClick = (user) => {
    setUserToPermanentlyDelete(user);
    setPermanentDeleteConfirmation("");
    setPermanentDeleteOpen(true);
  };

  const closePermanentDeleteDialog = () => {
    if (permanentDeleteLoading) return;
    setPermanentDeleteOpen(false);
    setUserToPermanentlyDelete(null);
    setPermanentDeleteConfirmation("");
  };

  const confirmPermanentDeleteUser = async () => {
    if (!userToPermanentlyDelete || permanentDeleteLoading) return;
    setPermanentDeleteLoading(true);
    try {
      await service.permanentlyDeleteUser(userToPermanentlyDelete.id, permanentDeleteConfirmation);
      setUserSuccess("Bruger slettet permanent.");
      setOpenUserSuccess(true);
      setUsers((prev) => prev.filter((user) => user.id !== userToPermanentlyDelete.id));
      if (selectedUserId === userToPermanentlyDelete.id) {
        setSelectedUserId(null);
        setDetailViewOpen(false);
      }
      setPermanentDeleteOpen(false);
      setUserToPermanentlyDelete(null);
      setPermanentDeleteConfirmation("");
    } catch (err) {
      setUserError(service.errorToString(err));
      setOpenUserError(true);
    } finally {
      setPermanentDeleteLoading(false);
    }
  };

  const handleSort = (field) => {
    if (sortField === field) setSortDirection((direction) => (direction === "asc" ? "desc" : "asc"));
    else {
      setSortField(field);
      setSortDirection("asc");
    }
  };

  const displayOrgName = React.useCallback((user) => {
    if (user?.role === "superadmin") return "Global";
    return user?.organization_name || orgNameById[user?.organization_id] || "—";
  }, [orgNameById]);

  const filteredUsers = React.useMemo(() => {
    const query = filterText.trim().toLowerCase();
    const filtered = users.filter((user) => {
      if (roleFilter !== "all" && user.role !== roleFilter) return false;
      if (activeFilter === "active" && user.is_active === false) return false;
      if (activeFilter === "inactive" && user.is_active !== false) return false;
      if (query && !userSearchText(user, orgNameById).includes(query)) return false;
      return true;
    });

    const sorted = [...filtered].sort((a, b) => {
      let aVal = "";
      let bVal = "";
      if (sortField === "id") { aVal = a.id ?? 0; bVal = b.id ?? 0; }
      else if (sortField === "name") { aVal = displayName(a); bVal = displayName(b); }
      else if (sortField === "email") { aVal = a.email ?? ""; bVal = b.email ?? ""; }
      else if (sortField === "role") { aVal = ROLE_DISPLAY[a.role] || a.role || ""; bVal = ROLE_DISPLAY[b.role] || b.role || ""; }
      else if (sortField === "organization") { aVal = displayOrgName(a); bVal = displayOrgName(b); }
      else if (sortField === "is_active") { aVal = a.is_active === false ? 0 : 1; bVal = b.is_active === false ? 0 : 1; }
      else if (sortField === "must_change_password") { aVal = a.must_change_password ? 1 : 0; bVal = b.must_change_password ? 1 : 0; }
      else if (sortField === "last_login_at") { aVal = a.last_login_at || ""; bVal = b.last_login_at || ""; }
      const result = typeof aVal === "number" && typeof bVal === "number"
        ? aVal - bVal
        : String(aVal).localeCompare(String(bVal), "da", { sensitivity: "base" });
      return sortDirection === "asc" ? result : -result;
    });
    return sorted;
  }, [users, filterText, roleFilter, activeFilter, sortField, sortDirection, orgNameById, displayOrgName]);

  const closeSelectedUserAuditLog = () => {
    setAuditLogUserId(null);
    setAuditLogs([]);
    setAuditLogError("");
  };

  const openSelectedUserAuditLog = async (user) => {
    if (!user?.id || !isSuperadmin) return;
    const userId = Number(user.id);
    setAuditLogUserId(user.id);
    setAuditLogs([]);
    setAuditLogError("");
    setAuditLogLoading(true);

    try {
      // En bruger kan optræde i audit-loggen som mål, aktør eller entity.
      const [targetLogs, actorLogs, entityLogs] = await Promise.all([
        fetchAuditLogs(null, { target_user_id: userId, limit: 250 }),
        fetchAuditLogs(null, { actor_user_id: userId, limit: 250 }),
        fetchAuditLogs(null, { entity_type: "user", entity_id: userId, limit: 250 }),
      ]);

      const asAuditLogArray = (value) => {
        if (Array.isArray(value)) return value;
        if (Array.isArray(value?.items)) return value.items;
        return [];
      };

      const mergedById = new Map();
      [...asAuditLogArray(targetLogs), ...asAuditLogArray(actorLogs)].forEach((log) => {
        const key = log.id ?? `${log.created_at}-${log.action}-${Math.random()}`;
        mergedById.set(key, log);
      });

      asAuditLogArray(entityLogs).forEach((log) => {
        const isRelevant =
          Number(log.entity_id) === userId ||
          Number(log.target_user_id) === userId ||
          Number(log.actor_user_id) === userId;
        if (isRelevant) {
          const key = log.id ?? `${log.created_at}-${log.action}-${Math.random()}`;
          mergedById.set(key, log);
        }
      });

      const merged = Array.from(mergedById.values()).sort((a, b) => {
        const at = new Date(a.created_at || 0).getTime();
        const bt = new Date(b.created_at || 0).getTime();
        return bt - at;
      });
      setAuditLogs(merged);
    } catch (err) {
      setAuditLogError(service.errorToString(err));
    } finally {
      setAuditLogLoading(false);
    }
  };

  const clearFilters = () => {
    setFilterText("");
    setRoleFilter("all");
    setActiveFilter("all");
    setSortField("name");
    setSortDirection("asc");
  };

  const selectedIsEditing = selectedUser && editUserId === selectedUser.id;
  const selectedIsMe = selectedUser?.id === me?.id;
  const selectedRoleIsSuperadmin = selectedUser?.role === "superadmin";
  const editingRoleIsSuperadmin = editFields.role === "superadmin";

  const canEdit = Boolean(selectedUser) && isAdmin && (!selectedIsMe || isSuperadmin);
  const canSendLink = Boolean(selectedUser) && isAdmin && !selectedIsMe && selectedUser.is_active !== false && Boolean(selectedUser.email);
  const canTemp = Boolean(selectedUser) && isAdmin && !selectedIsMe && selectedUser.is_active !== false;
  const canStatus = Boolean(selectedUser) && isAdmin && !selectedIsMe;
  const canPermanent = Boolean(selectedUser) && isSuperadmin && !selectedIsMe && selectedUser.is_active === false && !selectedRoleIsSuperadmin;

  if (authLoading) return null;
  if (!isAdmin && !isSuperadmin) return null;

  return (
    <>
      <AppSnackbar
        open={openUserError}
        message={userError}
        severity="error"
        onClose={() => setOpenUserError(false)}
      />
      <AppSnackbar
        open={openUserSuccess}
        message={userSuccess}
        severity="success"
        onClose={() => setOpenUserSuccess(false)}
      />
      <Dialog open={statusConfirmOpen} onClose={() => setStatusConfirmOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{nextUserActiveStatus ? "Gendan bruger?" : "Deaktiver bruger?"}</DialogTitle>
        <DialogContent>
          <Alert severity={nextUserActiveStatus ? "info" : "warning"} sx={{ mb: 2 }}>
            {nextUserActiveStatus
              ? "Brugeren får igen adgang til systemet."
              : "Brugeren kan ikke logge ind, men historik bevares. Handlingen kan fortrydes."}
          </Alert>
          <DialogContentText>
            {nextUserActiveStatus ? "Gendan" : "Deaktiver"} {" "}
            <strong>{displayName(userToChangeStatus) || userToChangeStatus?.username}</strong>?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStatusConfirmOpen(false)}>Annullér</Button>
          <Button color={nextUserActiveStatus ? "success" : "warning"} variant="contained" onClick={confirmUserStatusChange}>
            {nextUserActiveStatus ? "Gendan bruger" : "Deaktiver bruger"}
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={permanentDeleteOpen} onClose={closePermanentDeleteDialog} maxWidth="sm" fullWidth>
        <DialogTitle>Slet bruger permanent?</DialogTitle>
        <DialogContent>
          <Alert severity="error" sx={{ mb: 2 }}>
            Permanent sletning kan ikke fortrydes. Brugeren skal være inaktiv først.
          </Alert>
          <DialogContentText sx={{ mb: 2 }}>
            Skriv brugerens email for at bekræfte permanent sletning af {" "}
            <strong>{displayName(userToPermanentlyDelete) || userToPermanentlyDelete?.username}</strong>.
          </DialogContentText>
          <TextField
            autoFocus
            fullWidth
            size="small"
            label="Bekræft med brugerens email"
            value={permanentDeleteConfirmation}
            onChange={(event) => setPermanentDeleteConfirmation(event.target.value)}
            placeholder={userToPermanentlyDelete?.email || "email"}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={closePermanentDeleteDialog} disabled={permanentDeleteLoading}>Annullér</Button>
          <Button
            color="error"
            variant="contained"
            onClick={confirmPermanentDeleteUser}
            disabled={
              permanentDeleteLoading ||
              permanentDeleteConfirmation.trim().toLowerCase() !== String(userToPermanentlyDelete?.email || "").trim().toLowerCase()
            }
          >
            {permanentDeleteLoading ? "Sletter…" : "Slet permanent"}
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={resetConfirmOpen} onClose={closePasswordResetDialog} maxWidth="sm" fullWidth>
        <DialogTitle>Send nulstillingslink?</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            Brugeren kan først logge ind igen, når der er valgt nyt password via reset-linket.
          </Alert>
          <DialogContentText>
            Send nulstillingslink til {" "}
            <strong>{displayName(userToResetPassword) || userToResetPassword?.username}</strong>
            {userToResetPassword?.email ? ` (${userToResetPassword.email})` : ""}?
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={closePasswordResetDialog} disabled={Boolean(resetMailLoadingUserId)}>
            Annullér
          </Button>
          <Button
            color="warning"
            variant="contained"
            onClick={confirmSendPasswordResetLink}
            disabled={Boolean(resetMailLoadingUserId)}
          >
            {resetMailLoadingUserId ? "Sender…" : "Send link"}
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={temporaryPasswordOpen} onClose={closeTemporaryPasswordDialog} maxWidth="sm" fullWidth>
        <DialogTitle>Tildel midlertidigt password</DialogTitle>
        <DialogContent>
          <Alert severity="info" sx={{ mb: 2 }}>
            Brugeren skal skifte det midlertidige password ved næste login. Administrator ser ikke brugerens permanente password.
          </Alert>
          <DialogContentText sx={{ mb: 2 }}>
            Tildel midlertidigt password til {" "}
            <strong>{displayName(userToReceiveTemporaryPassword) || userToReceiveTemporaryPassword?.username}</strong>
            {userToReceiveTemporaryPassword?.email ? ` (${userToReceiveTemporaryPassword.email})` : ""}.
          </DialogContentText>
          {temporaryPasswordError && <Alert severity="error" sx={{ mb: 2 }}>{temporaryPasswordError}</Alert>}
          <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>
            <TextField
              autoFocus
              fullWidth
              size="small"
              type="text"
              label="Midlertidigt password"
              value={temporaryPassword}
              onChange={(event) => setTemporaryPassword(event.target.value)}
              slotProps={{
                input: {
                  endAdornment: (
                    <InputAdornment position="end">
                      <Tooltip title="Kopiér">
                        <IconButton size="small" onClick={copyTemporaryPassword}>
                          <ContentCopyIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </InputAdornment>
                  ),
                }
              }}
            />
            <TextField
              fullWidth
              size="small"
              type="text"
              label="Gentag midlertidigt password"
              value={temporaryPasswordRepeat}
              onChange={(event) => setTemporaryPasswordRepeat(event.target.value)}
            />
            <Button variant="outlined" onClick={generateTemporaryPassword} sx={{ alignSelf: "flex-start" }}>
              Generér sikkert password
            </Button>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeTemporaryPasswordDialog} disabled={temporaryPasswordLoading}>Annullér</Button>
          <Button variant="contained" onClick={confirmTemporaryPassword} disabled={temporaryPasswordLoading}>
            {temporaryPasswordLoading ? "Gemmer…" : "Tildel password"}
          </Button>
        </DialogActions>
      </Dialog>
      <AuditLogDialog
        open={isSuperadmin && Boolean(auditLogUserId)}
        user={users.find((u) => String(u.id) === String(auditLogUserId)) || null}
        logs={auditLogs}
        loading={auditLogLoading}
        error={auditLogError}
        onClose={closeSelectedUserAuditLog}
      />
      <Box sx={pageShellSx}>
        <Paper sx={pagePaperSx}>
          <Typography variant="h6">Brugeradministration</Typography>
          <Divider sx={{ my: 2, borderColor: COLORS.border }} />

          <Box
            component="form"
            autoComplete="off"
            onSubmit={handleCreateUser}
            sx={{
              mb: 2,
              display: "flex",
              gap: { xs: 1.5, md: 2 },
              flexWrap: "wrap",
              alignItems: { xs: "stretch", md: "center" },
              "& > .MuiTextField-root, & > .MuiFormControl-root": {
                width: { xs: "100%", sm: "auto" },
              },
            }}
          >
            <TextField
              label="Brugernavn"
              size="small"
              value={newUser.username}
              error={!validation.usernameValid && newUser.username.length > 0}
              helperText={!validation.usernameValid && newUser.username.length > 0 ? "Brugernavn skal være mindst 3 tegn" : ""}
              onChange={(event) => setNewUser({ ...newUser, username: event.target.value })}
              slotProps={{ htmlInput: { ref: usernameRef } }}
            />
            <TextField
              label="Fulde navn"
              size="small"
              value={newUser.name}
              error={!validation.nameValid && newUser.name.length > 0}
              helperText={!validation.nameValid && newUser.name.length > 0 ? "Fulde navn skal udfyldes" : ""}
              onChange={(event) => setNewUser({ ...newUser, name: event.target.value })}
              slotProps={{ htmlInput: { ref: nameRef } }}
            />
            <TextField
              label="Email"
              size="small"
              value={newUser.email}
              error={!validation.emailValid && newUser.email.length > 0}
              helperText={!validation.emailValid && newUser.email.length > 0 ? "Ugyldig email" : ""}
              onChange={(event) => setNewUser({ ...newUser, email: event.target.value })}
              slotProps={{ htmlInput: { ref: emailRef } }}
            />
            <TextField
              label="Gentag email"
              size="small"
              value={newUser.emailRepeat}
              error={!validation.emailMatch && newUser.emailRepeat.length > 0}
              helperText={!validation.emailMatch && newUser.emailRepeat.length > 0 ? "Emails matcher ikke" : ""}
              onChange={(event) => setNewUser({ ...newUser, emailRepeat: event.target.value })}
            />

            <FormControl size="small" sx={{ minWidth: 200 }}>
              <InputLabel id="role-select-label">Rolle</InputLabel>
              <Select
                labelId="role-select-label"
                value={newUser.role}
                label="Rolle"
                onChange={(event) => {
                  const role = event.target.value;
                  setNewUser((prev) => ({
                    ...prev,
                    role,
                    organization_id: role === "superadmin" ? null : !isSuperadmin ? me?.organization_id : prev.organization_id,
                  }));
                }}
              >
                {visibleRoles.map((role) => (
                  <MenuItem key={role} value={role}>{ROLE_DISPLAY[role]}</MenuItem>
                ))}
              </Select>
            </FormControl>

            {newUser.role !== "superadmin" && isSuperadmin && (
              <FormControl size="small" sx={{ minWidth: 260 }}>
                <InputLabel id="org-select-label">Organisation</InputLabel>
                <Select
                  labelId="org-select-label"
                  value={newUser.organization_id ?? ""}
                  label="Organisation"
                  onChange={(event) => setNewUser({ ...newUser, organization_id: event.target.value === "" ? null : Number(event.target.value) })}
                >
                  <MenuItem value="">Vælg organisation</MenuItem>
                  {organizations.map((organization) => (
                    <MenuItem key={organization.id} value={organization.id}>{organization.name}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            )}

            <Box sx={{ display: "flex", gap: { xs: 1.5, md: 2 }, alignItems: { xs: "stretch", md: "center" }, justifyContent: "flex-end", flexWrap: "wrap", width: "100%" }}>
              <Button
                type="submit"
                variant="contained"
                disabled={disableCreate || userLoading}
                loading={userLoading}
                loadingPosition="start"
                sx={{ width: { xs: "100%", sm: "auto" } }}
              >
                Opret og send mail
              </Button>
            </Box>
          </Box>

          <Divider sx={{ my: 2, borderColor: COLORS.border }} />

          <Box sx={filterBarSx}>
            <TextField
              placeholder="Søg på ID, navn, brugernavn, email, rolle, organisation, status eller login…"
              size="small"
              value={filterText}
              onChange={(event) => setFilterText(event.target.value)}
              sx={{ minWidth: { xs: 0, md: 280 }, width: { xs: "100%", md: "auto" }, flex: { xs: "1 1 100%", md: "0 0 auto" } }}
              slotProps={{
                input: {
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setFilterText("")} disabled={!filterText}>
                        <ClearIcon fontSize="small" />
                      </IconButton>
                    </InputAdornment>
                  ),
                }
              }}
            />

            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, flexWrap: "wrap" }}>
              <Typography sx={filterLabelSx}>Rolle</Typography>
              <ToggleButtonGroup value={roleFilter} exclusive size="small" onChange={(_, value) => { if (value !== null) setRoleFilter(value); }} sx={toggleGroupSx}>
                <ToggleButton value="all">Alle</ToggleButton>
                {isSuperadmin && <ToggleButton value="viewer">Se adgang</ToggleButton>}
                <ToggleButton value="bruger">Bruger</ToggleButton>
                <ToggleButton value="admin">Administrator</ToggleButton>
                {isSuperadmin && <ToggleButton value="superadmin">Superadministrator</ToggleButton>}
              </ToggleButtonGroup>
            </Box>

            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, flexWrap: "wrap" }}>
              <Typography sx={filterLabelSx}>Status</Typography>
              <ToggleButtonGroup value={activeFilter} exclusive size="small" onChange={(_, value) => { if (value !== null) setActiveFilter(value); }} sx={toggleGroupSx}>
                <ToggleButton value="all">Alle</ToggleButton>
                <ToggleButton value="active">Aktive</ToggleButton>
                <ToggleButton value="inactive">Inaktive</ToggleButton>
              </ToggleButtonGroup>
            </Box>

            <Box sx={{ display: "flex", alignItems: "center", gap: 1, ml: { xs: 0, md: "auto" }, width: { xs: "100%", md: "auto" }, justifyContent: { xs: "flex-start", md: "flex-end" }, flexWrap: "wrap" }}>
              <Chip label={`${filteredUsers.length} vist`} size="small" sx={countChipSx} />
              <Button size="small" variant="outlined" startIcon={<FilterListOffIcon fontSize="small" />} onClick={clearFilters}>
                Ryd filtre
              </Button>
            </Box>
          </Box>

          {userLoading && users.length === 0 ? (
            <Box sx={{ display: "flex", gap: 1, alignItems: "center", py: 3 }}>
              <CircularProgress size={18} />
              <Typography>Henter brugere…</Typography>
            </Box>
          ) : detailViewOpen ? (
            <Box sx={{ ...viewSwitchSx, ...userAdminLayoutSx }}>
              <Box sx={userListPanelSx}>
                <Box sx={{ px: 1.5, py: 1.25, bgcolor: COLORS.panelSoft, borderBottom: `1px solid ${COLORS.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 1 }}>
                  <Box sx={{ display: "flex", alignItems: "center", gap: 1, minWidth: 0 }}>
                    <Typography sx={{ fontWeight: 850, color: COLORS.text }}>Brugere</Typography>
                    <Chip label={`${filteredUsers.length} vist`} size="small" sx={countChipSx} />
                  </Box>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={() => setDetailViewOpen(false)}
                    sx={{ textTransform: "none", fontWeight: 800, whiteSpace: "nowrap" }}
                  >
                    Tilbage til oversigt
                  </Button>
                </Box>

                {filteredUsers.length === 0 ? (
                  <Box sx={{ px: 2, py: 4, textAlign: "center", color: COLORS.muted }}>
                    Ingen brugere matcher de valgte filtre.
                  </Box>
                ) : (
                  <Box sx={{ maxHeight: { lg: "64vh" }, overflowY: "auto" }}>
                    {filteredUsers.map((user) => {
                      const selected = selectedUser?.id === user.id;
                      const inactive = user.is_active === false;
                      const roleText = ROLE_DISPLAY[user.role] ?? user.role;
                      const orgText = displayOrgName(user);
                      const isMe = user.id === me?.id;

                      return (
                        <Box
                          key={user.id}
                          id={`user-row-${user.id}`}
                          component="button"
                          type="button"
                          onClick={() => {
                            handleEditCancel();
                            setSelectedUserId(user.id);
                          }}
                          sx={userListButtonSx(selected, inactive)}
                        >
                          <Box sx={{ minWidth: 0 }}>
                            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, minWidth: 0 }}>
                              <Typography sx={{ fontWeight: 850, color: inactive ? COLORS.muted : COLORS.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>
                                {displayName(user) || user.username}
                              </Typography>
                              {isSuperadmin && <Chip label={`ID ${user.id}`} size="small" sx={idChipSx} />}
                              {isMe && <Chip label="Dig" size="small" sx={currentUserChipSx} />}
                            </Box>
                            <Box sx={{ display: "flex", alignItems: "center", gap: 0.75, minWidth: 0, overflow: "hidden" }}>
                              <Typography sx={{ fontSize: 12, color: COLORS.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", minWidth: 0 }}>
                                {[user.username, user.email, roleText, isSuperadmin ? orgText : null].filter(Boolean).join(" · ")}
                              </Typography>
                            </Box>
                          </Box>
                          <UserStatusChip active={user.is_active !== false} />
                        </Box>
                      );
                    })}
                  </Box>
                )}
              </Box>

              <Box sx={userDetailPanelSx}>
                {selectedUser ? (
                  <Box sx={userDetailAnimationSx}>
                    <Box sx={detailHeaderSx}>
                      <Box sx={{ display: "flex", alignItems: "center", gap: 1.5, minWidth: 0 }}>
                        <Box sx={{ minWidth: 0, flex: 1 }}>
                          <Typography variant="h6" sx={{ fontWeight: 850, color: selectedUser.is_active === false ? COLORS.muted : COLORS.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {[selectedUser.username, displayName(selectedUser), displayOrgName(selectedUser)].filter((value) => value && value !== "—").join(" - ") || selectedUser.email || "Bruger"}
                          </Typography>
                          <Typography sx={{ color: COLORS.muted, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {ROLE_DISPLAY[selectedUser.role] || selectedUser.role || "Rolle ikke angivet"}
                          </Typography>
                        </Box>
                        <UserStatusChip active={selectedUser.is_active !== false} />
                      </Box>
                    </Box>

                    <Box sx={detailBodySx}>
                      {editError.global && selectedIsEditing && <Alert severity="error" sx={{ mb: 2 }}>{editError.global}</Alert>}
                      <Box sx={detailContentShellSx}>
                        <Box sx={{ minWidth: 0 }}>
                          <Box sx={detailGridSx}>
                            {isSuperadmin && <DetailField label="ID">{String(selectedUser.id)}</DetailField>}
                            <DetailField label="Navn">
                              {selectedIsEditing ? (
                                <TextField fullWidth variant="standard" size="small" value={editFields.name ?? ""} error={Boolean(editError.name)} helperText={editError.name || ""} onChange={(event) => handleEditFieldChange("name", event.target.value)} sx={editableInlineFieldSx} />
                              ) : (displayName(selectedUser) || "—")}
                            </DetailField>
                            <DetailField label="Email">
                              {selectedIsEditing ? (
                                <TextField fullWidth variant="standard" size="small" value={editFields.email ?? ""} error={Boolean(editError.email)} helperText={editError.email || ""} onChange={(event) => handleEditFieldChange("email", event.target.value)} sx={editableInlineFieldSx} />
                              ) : (selectedUser.email || "—")}
                            </DetailField>
                            <DetailField label="Brugernavn">{selectedUser.username}</DetailField>
                            <DetailField label="Rolle">
                              {selectedIsEditing && !selectedIsMe ? (
                                <FormControl fullWidth size="small" variant="standard" sx={editableInlineFieldSx}>
                                  <Select value={editFields.role ?? "bruger"} onChange={(event) => handleEditFieldChange("role", event.target.value)}>
                                    {visibleRoles.map((role) => <MenuItem key={role} value={role}>{ROLE_DISPLAY[role]}</MenuItem>)}
                                  </Select>
                                </FormControl>
                              ) : (ROLE_DISPLAY[selectedUser.role] || selectedUser.role)}
                            </DetailField>
                            <DetailField label="Organisation">
                              {selectedIsEditing && isSuperadmin && !selectedIsMe && !editingRoleIsSuperadmin ? (
                                <FormControl fullWidth size="small" variant="standard" sx={editableInlineFieldSx} error={Boolean(editError.organization_id)}>
                                  <Select value={editFields.organization_id ?? ""} onChange={(event) => handleEditFieldChange("organization_id", event.target.value === "" ? null : Number(event.target.value))}>
                                    <MenuItem value=""><em>Vælg organisation</em></MenuItem>
                                    {organizations.map((organization) => <MenuItem key={organization.id} value={organization.id}>{organization.name}</MenuItem>)}
                                  </Select>
                                </FormControl>
                              ) : displayOrgName(selectedUser)}
                            </DetailField>
                            <DetailField label="Status">
                              {selectedIsEditing && !selectedIsMe ? (
                                <FormControl fullWidth size="small" variant="standard" sx={editableInlineFieldSx}>
                                  <Select value={editFields.is_active ? "true" : "false"} onChange={(event) => handleEditFieldChange("is_active", event.target.value === "true")}>
                                    <MenuItem value="true">Aktiv</MenuItem>
                                    <MenuItem value="false">Inaktiv</MenuItem>
                                  </Select>
                                </FormControl>
                              ) : (selectedUser.is_active !== false ? "Aktiv" : "Inaktiv")}
                            </DetailField>
                            <DetailField label="Password">{selectedUser.must_change_password ? "Skal skifte ved næste login" : "OK"}</DetailField>
                            <DetailField label="Sidst login">{formatLastLogin(selectedUser.last_login_at)}</DetailField>
                          </Box>
                        </Box>

                        <Box sx={actionsColumnSx}>
                          <Typography sx={{ fontWeight: 850, mb: 1, color: COLORS.text }}>Funktioner</Typography>
                          <Box sx={visibleActionsGridSx}>
                            {selectedIsEditing ? (
                              <>
                                <Button variant="contained" color="success" startIcon={<SaveIcon fontSize="small" />} loading={editLoading} loadingPosition="start" onClick={() => editingUser && handleEditSave(editingUser)} disabled={editLoading || !editingUser} sx={visibleActionButtonSx}>Gem ændringer</Button>
                                <Button variant="outlined" startIcon={<CloseIcon fontSize="small" />} onClick={handleEditCancel} sx={visibleActionButtonSx}>Annullér</Button>
                              </>
                            ) : (
                              <Button variant="contained" startIcon={<EditIcon fontSize="small" />} disabled={!canEdit} onClick={() => handleEditClick(selectedUser)} sx={visibleActionButtonSx}>Rediger bruger</Button>
                            )}
                            <Button variant="outlined" startIcon={<VpnKeyIcon fontSize="small" />} loading={resetMailLoadingUserId === selectedUser.id} loadingPosition="start" disabled={!canSendLink || resetMailLoadingUserId === selectedUser.id || selectedIsEditing} onClick={() => openPasswordResetDialog(selectedUser)} sx={visibleActionButtonSx}>Send reset-link</Button>
                            <Button variant="outlined" color="secondary" startIcon={<VpnKeyIcon fontSize="small" />} disabled={!canTemp || selectedIsEditing} onClick={() => openTemporaryPasswordDialog(selectedUser)} sx={visibleActionButtonSx}>Midlertidigt password</Button>
                            {isSuperadmin && (
                              <Button variant="outlined" startIcon={<HistoryIcon fontSize="small" />} disabled={selectedIsEditing} onClick={() => openSelectedUserAuditLog(selectedUser)} sx={visibleActionButtonSx}>Se audit-log</Button>
                            )}
                            <Button variant="outlined" color={selectedUser.is_active === false ? "success" : "warning"} startIcon={selectedUser.is_active === false ? <RestoreIcon fontSize="small" /> : <PersonOffIcon fontSize="small" />} disabled={!canStatus || selectedIsEditing} onClick={() => handleUserStatusClick(selectedUser, selectedUser.is_active === false)} sx={visibleActionButtonSx}>{selectedUser.is_active === false ? "Gendan bruger" : "Deaktiver bruger"}</Button>
                            <Button variant="outlined" color="error" startIcon={<DeleteForeverIcon fontSize="small" />} disabled={!canPermanent || selectedIsEditing} onClick={() => handlePermanentDeleteClick(selectedUser)} sx={visibleActionButtonSx}>Slet permanent</Button>
                          </Box>
                        </Box>
                      </Box>
                    </Box>
                  </Box>
                ) : (
                  <Box sx={{ px: 2, py: 4, textAlign: "center", color: COLORS.muted }}>
                    Vælg en bruger i tabellen.
                  </Box>
                )}
              </Box>
            </Box>
          ) : (
            <Box sx={viewSwitchSx}>
              <Box sx={userListPanelSx}>
                <Box sx={{ px: 1.5, py: 1.25, bgcolor: COLORS.panelSoft, borderBottom: `1px solid ${COLORS.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 1 }}>
                  <Typography sx={{ fontWeight: 850, color: COLORS.text }}>Brugere</Typography>
                  <Chip label={`${filteredUsers.length} vist`} size="small" sx={countChipSx} />
                </Box>

                {filteredUsers.length === 0 ? (
                  <Box sx={{ px: 2, py: 4, textAlign: "center", color: COLORS.muted }}>
                    Ingen brugere matcher de valgte filtre.
                  </Box>
                ) : (
                  <TableContainer sx={{ maxHeight: { lg: "64vh" }, overflowY: "auto", overflowX: "hidden" }}>
                    <Table size="small" stickyHeader sx={{ width: "100%", tableLayout: "auto" }}>
                      <TableHead>
                        <TableRow>
                          {isSuperadmin && (
                            <TableCell sx={{ ...tableHeaderCellSx, width: 72 }} sortDirection={sortField === "id" ? sortDirection : false}>
                              <TableSortLabel active={sortField === "id"} direction={sortField === "id" ? sortDirection : "asc"} onClick={() => handleSort("id")}>ID</TableSortLabel>
                            </TableCell>
                          )}
                          <TableCell sx={tableHeaderCellSx} sortDirection={sortField === "name" ? sortDirection : false}>
                            <TableSortLabel active={sortField === "name"} direction={sortField === "name" ? sortDirection : "asc"} onClick={() => handleSort("name")}>Bruger</TableSortLabel>
                          </TableCell>
                          <TableCell sx={tableHeaderCellSx} sortDirection={sortField === "email" ? sortDirection : false}>
                            <TableSortLabel active={sortField === "email"} direction={sortField === "email" ? sortDirection : "asc"} onClick={() => handleSort("email")}>Email</TableSortLabel>
                          </TableCell>
                          <TableCell sx={tableHeaderCellSx} sortDirection={sortField === "role" ? sortDirection : false}>
                            <TableSortLabel active={sortField === "role"} direction={sortField === "role" ? sortDirection : "asc"} onClick={() => handleSort("role")}>Rolle</TableSortLabel>
                          </TableCell>
                          {isSuperadmin && (
                            <TableCell sx={tableHeaderCellSx} sortDirection={sortField === "organization" ? sortDirection : false}>
                              <TableSortLabel active={sortField === "organization"} direction={sortField === "organization" ? sortDirection : "asc"} onClick={() => handleSort("organization")}>Organisation</TableSortLabel>
                            </TableCell>
                          )}
                          <TableCell sx={tableHeaderCellSx} sortDirection={sortField === "is_active" ? sortDirection : false}>
                            <TableSortLabel active={sortField === "is_active"} direction={sortField === "is_active" ? sortDirection : "asc"} onClick={() => handleSort("is_active")}>Status</TableSortLabel>
                          </TableCell>
                          <TableCell sx={tableHeaderCellSx} sortDirection={sortField === "must_change_password" ? sortDirection : false}>
                            <TableSortLabel active={sortField === "must_change_password"} direction={sortField === "must_change_password" ? sortDirection : "asc"} onClick={() => handleSort("must_change_password")}>Password</TableSortLabel>
                          </TableCell>
                          <TableCell sx={{ ...tableHeaderCellSx, cursor: "default", textAlign: "right", width: 112 }} />
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {filteredUsers.map((user) => {
                          const selected = selectedUser?.id === user.id;
                          const inactive = user.is_active === false;
                          const roleText = ROLE_DISPLAY[user.role] ?? user.role;
                          const isMe = user.id === me?.id;
                          return (
                            <TableRow
                              key={user.id}
                              id={`user-row-${user.id}`}
                              hover
                              selected={Boolean(selected)}
                              onClick={() => {
                                handleEditCancel();
                                setSelectedUserId(user.id);
                                setDetailViewOpen(true);
                              }}
                              sx={{ ...userTableRowSx(selected, inactive), ...(highlightedUserId === user.id ? highlightRowSx : {}) }}
                            >
                              {isSuperadmin && <TableCell sx={tableCellSx}>{user.id}</TableCell>}
                              <TableCell sx={tableCellSx}>
                                <Box sx={{ minWidth: 0 }}>
                                  <SingleLineText sx={{ fontWeight: 850, color: inactive ? COLORS.muted : COLORS.text }}>{displayName(user) || user.username}</SingleLineText>
                                  <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, minWidth: 0 }}>
                                    <SingleLineText sx={{ fontSize: 12, color: COLORS.muted }}>{user.username}</SingleLineText>
                                    {isMe && <Chip label="Dig" size="small" sx={currentUserChipSx} />}
                                  </Box>
                                </Box>
                              </TableCell>
                              <TableCell sx={tableCellSx}><SingleLineText>{user.email}</SingleLineText></TableCell>
                              <TableCell sx={tableCellSx}><SingleLineText>{roleText}</SingleLineText></TableCell>
                              {isSuperadmin && <TableCell sx={tableCellSx}><SingleLineText sx={{ fontWeight: 650 }}>{displayOrgName(user)}</SingleLineText></TableCell>}
                              <TableCell sx={tableCellSx}><UserStatusChip active={user.is_active !== false} /></TableCell>
                              <TableCell sx={tableCellSx}><PasswordStatusChip mustChange={Boolean(user.must_change_password)} /></TableCell>
                              <TableCell sx={{ ...tableCellSx, textAlign: "right" }}>
                                <Button
                                  size="small"
                                  variant="outlined"
                                  sx={tableMoreButtonSx}
                                  onClick={(event) => {
                                    event.stopPropagation();
                                    handleEditCancel();
                                    setSelectedUserId(user.id);
                                    setDetailViewOpen(true);
                                  }}
                                >
                                  Se mere
                                </Button>
                              </TableCell>
                            </TableRow>
                          );
                        })}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </Box>
            </Box>
          )}
        </Paper>
      </Box>
    </>
  );
}
