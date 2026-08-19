import AppSnackbar from "../../components/AppSnackbar";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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
  Grid,
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddBusinessIcon from "@mui/icons-material/AddBusiness";
import AddPhotoAlternateIcon from "@mui/icons-material/AddPhotoAlternate";
import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import CalendarMonthIcon from "@mui/icons-material/CalendarMonth";
import CheckIcon from "@mui/icons-material/Check";
import ClearIcon from "@mui/icons-material/Clear";
import CloseIcon from "@mui/icons-material/Close";
import DeleteIcon from "@mui/icons-material/Delete";
import DeleteOutlinedIcon from "@mui/icons-material/DeleteOutlined";
import EditIcon from "@mui/icons-material/Edit";
import FilterListOffIcon from "@mui/icons-material/FilterListOff";
import ImageIcon from "@mui/icons-material/Image";
import SearchIcon from "@mui/icons-material/Search";
import SettingsSuggestIcon from "@mui/icons-material/SettingsSuggest";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";

import {
  addOrganization,
  applyOrganizationSeasonTimes,
  deleteOrganization,
  deleteOrganizationLogo,
  getOrganizationClients,
  getOrganizationLogoBlob,
  getOrganizations,
  getOrganizationTimes,
  replaceOrganizationSeasonCalendars,
  updateOrganizationName,
  updateOrganizationTimes,
  uploadOrganizationLogo,
} from "../../api";
import { useAuth } from "../../auth/AuthProvider";
import { compactDarkChipSx } from "../../utils/chipStyles";
import { useSeasonClock, useSeasonSelection } from "../../season/SeasonProvider";
import { embeddedPageShellSx } from "../../utils/layoutStyles";

const DEFAULT_WEEKDAY = { status: "on", onTime: "09:00", offTime: "20:00" };
const DEFAULT_WEEKEND = { status: "off", onTime: "09:00", offTime: "20:00" };

const DAY_CONFIG = [
  { key: "monday", label: "Mandag", fallback: DEFAULT_WEEKDAY },
  { key: "tuesday", label: "Tirsdag", fallback: DEFAULT_WEEKDAY },
  { key: "wednesday", label: "Onsdag", fallback: DEFAULT_WEEKDAY },
  { key: "thursday", label: "Torsdag", fallback: DEFAULT_WEEKDAY },
  { key: "friday", label: "Fredag", fallback: DEFAULT_WEEKDAY },
  { key: "saturday", label: "Lørdag", fallback: DEFAULT_WEEKEND },
  { key: "sunday", label: "Søndag", fallback: DEFAULT_WEEKEND },
];

const COLORS = {
  text: "#f8fafc",
  muted: "rgba(203,213,225,0.72)",
  border: "rgba(148,163,184,0.16)",
  borderStrong: "rgba(148,163,184,0.28)",
  panel: "rgba(15,23,42,0.74)",
  panelSoft: "rgba(15,23,42,0.52)",
  panelHover: "rgba(30,41,59,0.64)",
  field: "rgba(15,23,42,0.46)",
};

const LOGO_MAX_BYTES = 1_000_000;
const LOGO_ACCEPT = ".png,image/png";

const pageShellSx = embeddedPageShellSx;

const pagePaperSx = {
  p: { xs: 1.5, md: 2 },
  mb: 2,
  borderRadius: 2,
  border: `1px solid ${COLORS.border}`,
  background: COLORS.panel,
  color: COLORS.text,
  boxShadow: "0 24px 80px rgba(0,0,0,0.22)",
};

const filterBarSx = {
  display: "flex",
  flexWrap: "wrap",
  gap: 1.5,
  alignItems: "center",
  bgcolor: "rgba(15,23,42,0.46)",
  border: `1px solid ${COLORS.border}`,
  borderRadius: 2,
  px: 2,
  py: 1.25,
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

function normalizeText(value) {
  return String(value ?? "").trim().replace(/\s+/g, " ");
}

function sortByName(arr, direction = "asc") {
  const sorted = [...arr].sort((a, b) =>
    normalizeText(a.name).localeCompare(normalizeText(b.name), "da", { sensitivity: "base" }),
  );
  return direction === "desc" ? sorted.reverse() : sorted;
}

function normalizeOrg(raw) {
  return {
    ...raw,
    id: raw?.id ?? raw?.organization_id,
    name: normalizeText(raw?.name),
    has_logo: Boolean(raw?.has_logo || raw?.logo_url || raw?.logo_updated_at),
    logo_updated_at: raw?.logo_updated_at || null,
  };
}

function createDefaultDayTimes() {
  return DAY_CONFIG.reduce((acc, day) => {
    acc[day.key] = { ...day.fallback };
    return acc;
  }, {});
}

function isOffDay(value) {
  const status = String(value?.status || "on").toLowerCase();
  return status === "off" || status === "closed" || value?.enabled === false;
}

function normalizeDayTimes(data) {
  const source = data?.day_times && typeof data.day_times === "object" ? data.day_times : data || {};
  return DAY_CONFIG.reduce((acc, day) => {
    const raw = source?.[day.key] || day.fallback;
    const off = isOffDay(raw);
    acc[day.key] = {
      status: off ? "off" : "on",
      onTime: raw?.onTime || day.fallback.onTime,
      offTime: raw?.offTime || day.fallback.offTime,
    };
    return acc;
  }, {});
}

function serializeDayTimes(dayTimes) {
  return DAY_CONFIG.reduce((acc, day) => {
    const value = dayTimes?.[day.key] || day.fallback;
    if (isOffDay(value)) {
      acc[day.key] = { status: "off" };
    } else {
      acc[day.key] = {
        status: "on",
        onTime: value.onTime || day.fallback.onTime,
        offTime: value.offTime || day.fallback.offTime,
      };
    }
    return acc;
  }, {});
}

function isValidTime(value) {
  return /^\d{2}:\d{2}$/.test(String(value || ""));
}

function validateTimes(dayTimes) {
  for (const day of DAY_CONFIG) {
    const pair = dayTimes?.[day.key] || day.fallback;
    if (isOffDay(pair)) continue;
    if (!isValidTime(pair.onTime) || !isValidTime(pair.offTime)) {
      return `${day.label}: tider skal være på formatet hh:mm.`;
    }
    if (pair.onTime > pair.offTime) {
      return `${day.label}: tænd-tid skal være før sluk-tid.`;
    }
  }
  return "";
}

function TimeField({ label, value, onChange, disabled }) {
  return (
    <TextField
      label={label}
      type="time"
      size="small"
      fullWidth
      value={value}
      onChange={(event) => onChange(event.target.value)}
      disabled={disabled}
      slotProps={{
        htmlInput: { step: 300 }
      }}
    />
  );
}

function DayTimeCard({ day, value, disabled, onStatusChange, onTimeChange }) {
  const off = isOffDay(value);
  const isWeekend = day.key === "saturday" || day.key === "sunday";

  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.25,
        borderRadius: 2,
        border: `1px solid ${COLORS.border}`,
        background: off ? "rgba(127,29,29,0.20)" : isWeekend ? "rgba(88,28,135,0.18)" : COLORS.field,
        color: COLORS.text,
      }}
    >
      <Stack spacing={1}>
        <Stack
          direction="row"
          spacing={1}
          sx={{
            alignItems: "center",
            justifyContent: "space-between"
          }}>
          <Typography sx={{ fontWeight: 900 }}>{day.label}</Typography>
          <Chip size="small" label={off ? "Slukket" : "Tændt"} sx={compactDarkChipSx(off ? "error" : "success")} />
        </Stack>

        <FormControl size="small" fullWidth>
          <InputLabel id={`${day.key}-status-label`}>Status</InputLabel>
          <Select
            labelId={`${day.key}-status-label`}
            value={off ? "off" : "on"}
            label="Status"
            onChange={(event) => onStatusChange(event.target.value)}
            disabled={disabled}
          >
            <MenuItem value="on">Tændt denne dag</MenuItem>
            <MenuItem value="off">Slukket denne dag</MenuItem>
          </Select>
        </FormControl>

        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TimeField label="Tænd" value={value.onTime || day.fallback.onTime} onChange={(next) => onTimeChange("onTime", next)} disabled={disabled || off} />
          <TimeField label="Sluk" value={value.offTime || day.fallback.offTime} onChange={(next) => onTimeChange("offTime", next)} disabled={disabled || off} />
        </Stack>
      </Stack>
    </Paper>
  );
}

function DarkDialogPaper() {
  return {
    sx: {
      borderRadius: 2,
      background: "rgba(15,23,42,0.98)",
      color: COLORS.text,
      border: `1px solid ${COLORS.border}`,
      boxShadow: "0 28px 110px rgba(0,0,0,0.48)",
    },
  };
}

export default function OrganizationAdministration() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isSuperadmin = user?.role === "superadmin";
  const isViewer = user?.role === "viewer";
  const isAdmin = user?.role === "admin";
  const canCreateOrganizations = isSuperadmin;
  const canEditOrganizations = isSuperadmin;
  const canDeleteOrganizations = isSuperadmin;
  const canEditOwnLogo = isAdmin;
  const isReadOnly = isViewer;
  const { seasonOptions } = useSeasonClock();
  const { selectedSeason, setSelectedSeason } = useSeasonSelection(seasonOptions);

  const [organizations, setOrganizations] = useState([]);
  const [initialLoading, setInitialLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [snackbar, setSnackbar] = useState({ open: false, message: "", severity: "success" });

  const [name, setName] = useState("");
  const [searchText, setSearchText] = useState("");
  const [sortDirection, setSortDirection] = useState("asc");

  const [editingId, setEditingId] = useState(null);
  const [editingName, setEditingName] = useState("");
  const [highlightedId, setHighlightedId] = useState(null);

  const [logoUrls, setLogoUrls] = useState({});
  const [logoBusyIds, setLogoBusyIds] = useState(() => new Set());
  const [clientCounts, setClientCounts] = useState({});
  const [clientCountsLoading, setClientCountsLoading] = useState(false);

  const [timesDialogOpen, setTimesDialogOpen] = useState(false);
  const [timesOrganization, setTimesOrganization] = useState(null);
  const [dayTimes, setDayTimes] = useState(() => createDefaultDayTimes());
  const [timesLoading, setTimesLoading] = useState(false);
  const [timesSaving, setTimesSaving] = useState(false);
  const [applyLoading, setApplyLoading] = useState(false);
  const [overwriteLoading, setOverwriteLoading] = useState(false);
  const [overwriteDialogOpen, setOverwriteDialogOpen] = useState(false);
  const [overwriteConfirmText, setOverwriteConfirmText] = useState("");
  const [timesApprovedClientCount, setTimesApprovedClientCount] = useState(null);

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [organizationToDelete, setOrganizationToDelete] = useState(null);
  const [clientsToDelete, setClientsToDelete] = useState([]);
  const [loadingDeleteClients, setLoadingDeleteClients] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);

  const timesBusy = timesSaving || applyLoading || overwriteLoading;

  const showSnackbar = useCallback((message, severity = "success") => {
    setSnackbar({ open: true, message, severity });
  }, []);

  const closeSnackbar = () => setSnackbar({ open: false, message: "", severity: "success" });

  const fetchOrganizations = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getOrganizations();
      setOrganizations(Array.isArray(data) ? data.map(normalizeOrg) : []);
    } catch (err) {
      setOrganizations([]);
      setError(err?.message || "Kunne ikke hente organisationer.");
    } finally {
      setLoading(false);
      setInitialLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOrganizations();
  }, [fetchOrganizations]);

  useEffect(() => {
    const objectUrls = [];
    let cancelled = false;

    async function loadLogos() {
      const withLogo = organizations.filter((org) => org?.id && org.has_logo);
      if (!withLogo.length) {
        setLogoUrls({});
        return;
      }

      const next = {};
      await Promise.all(
        withLogo.map(async (org) => {
          try {
            const blob = await getOrganizationLogoBlob(org.id);
            if (cancelled) return;
            const url = URL.createObjectURL(blob);
            objectUrls.push(url);
            next[org.id] = url;
          } catch {
            // Logo må ikke blokere listen.
          }
        })
      );
      if (!cancelled) setLogoUrls(next);
    }

    loadLogos();
    return () => {
      cancelled = true;
      objectUrls.forEach((url) => URL.revokeObjectURL(url));
    };
  }, [organizations]);

  useEffect(() => {
    let cancelled = false;

    async function loadCounts() {
      if (!organizations.length) {
        setClientCounts({});
        return;
      }
      setClientCountsLoading(true);
      const next = {};
      await Promise.all(
        organizations.map(async (org) => {
          try {
            const clients = await getOrganizationClients(org.id);
            next[org.id] = Array.isArray(clients) ? clients.length : 0;
          } catch {
            next[org.id] = null;
          }
        })
      );
      if (!cancelled) {
        setClientCounts(next);
        setClientCountsLoading(false);
      }
    }

    loadCounts();
    return () => { cancelled = true; };
  }, [organizations]);

  const displayedOrganizations = useMemo(() => {
    const search = searchText.trim().toLowerCase();
    const filtered = organizations.filter((org) => {
      if (!search) return true;
      return String(org.name || "").toLowerCase().includes(search) || String(org.id || "").includes(search);
    });
    return sortByName(filtered, sortDirection);
  }, [organizations, searchText, sortDirection]);

  const anyFilterActive = searchText.trim() !== "";

  const highlightOrganization = (id) => {
    setHighlightedId(id);
    setTimeout(() => setHighlightedId(null), 5000);
    setTimeout(() => {
      const el = document.getElementById(`organization-item-${id}`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 200);
  };

  const handleCreate = async () => {
    setError("");
    const cleanName = normalizeText(name);
    if (!cleanName) {
      setError("Navn på organisation skal udfyldes.");
      return;
    }
    if (organizations.some((org) => normalizeText(org.name).toLowerCase() === cleanName.toLowerCase())) {
      setError("Der findes allerede en organisation med dette navn.");
      return;
    }

    setLoading(true);
    try {
      const created = normalizeOrg(await addOrganization(cleanName));
      setOrganizations((prev) => sortByName([...prev, created], sortDirection));
      setName("");
      showSnackbar("Organisation oprettet.", "success");
      highlightOrganization(created.id);
    } catch (err) {
      setError(err?.message || "Kunne ikke oprette organisation.");
    } finally {
      setLoading(false);
    }
  };

  const startEdit = (org) => {
    setEditingId(org.id);
    setEditingName(org.name || "");
    setError("");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditingName("");
  };

  const saveEdit = async (org) => {
    const cleanName = normalizeText(editingName);
    if (!cleanName) {
      setError("Navnet kan ikke være tomt.");
      return;
    }
    if (organizations.some((item) => Number(item.id) !== Number(org.id) && normalizeText(item.name).toLowerCase() === cleanName.toLowerCase())) {
      setError("Der findes allerede en organisation med dette navn.");
      return;
    }

    setLoading(true);
    try {
      const updated = normalizeOrg(await updateOrganizationName(org.id, cleanName));
      setOrganizations((prev) => prev.map((item) => (Number(item.id) === Number(org.id) ? updated : item)));
      cancelEdit();
      showSnackbar("Organisation opdateret.", "success");
      highlightOrganization(org.id);
    } catch (err) {
      setError(err?.message || "Kunne ikke opdatere organisation.");
    } finally {
      setLoading(false);
    }
  };

  const setLogoBusy = (orgId, busy) => {
    setLogoBusyIds((prev) => {
      const next = new Set(prev);
      if (busy) next.add(orgId);
      else next.delete(orgId);
      return next;
    });
  };

  const updateOrganizationLocal = (updated) => {
    if (!updated?.id) return;
    setOrganizations((prev) => prev.map((org) => (Number(org.id) === Number(updated.id) ? normalizeOrg(updated) : org)));
  };

  const validateLogoFile = (file) => {
    if (!file) return "Vælg en logo-fil.";
    const nameLower = String(file.name || "").toLowerCase();
    const typeLower = String(file.type || "").toLowerCase();
    if (!nameLower.endsWith(".png")) return "Logo skal være en .png-fil.";
    if (typeLower && typeLower !== "image/png") return "Logo skal være PNG.";
    if (file.size > LOGO_MAX_BYTES) return "Logo må højst være 1 MB.";
    return "";
  };

  const handleLogoUpload = async (org, event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !org?.id) return;

    const validationError = validateLogoFile(file);
    if (validationError) {
      showSnackbar(validationError, "error");
      return;
    }

    setLogoBusy(org.id, true);
    setError("");
    try {
      const updated = await uploadOrganizationLogo(org.id, file);
      updateOrganizationLocal(updated);
      showSnackbar("Logo opdateret.", "success");
    } catch (err) {
      const message = err?.message || "Kunne ikke uploade logo.";
      showSnackbar(message, "error");
    } finally {
      setLogoBusy(org.id, false);
    }
  };

  const handleLogoDelete = async (org) => {
    if (!org?.id) return;
    setLogoBusy(org.id, true);
    setError("");
    try {
      const updated = await deleteOrganizationLogo(org.id);
      updateOrganizationLocal(updated);
      showSnackbar("Logo fjernet.", "success");
    } catch (err) {
      const message = err?.message || "Kunne ikke fjerne logo.";
      showSnackbar(message, "error");
    } finally {
      setLogoBusy(org.id, false);
    }
  };

  const openOrganizationCalendar = (org) => {
    const params = new URLSearchParams();
    if (org?.id) params.set("organizationId", String(org.id));
    if (selectedSeason) params.set("season", String(selectedSeason));
    navigate(`/calendar?${params.toString()}`);
  };

  const openTimesDialog = async (org) => {
    setTimesOrganization(org);
    setTimesDialogOpen(true);
    setDayTimes(createDefaultDayTimes());
    setTimesApprovedClientCount(null);
    setOverwriteConfirmText("");
    setTimesLoading(true);
    const [timesResult, clientsResult] = await Promise.allSettled([
      getOrganizationTimes(org.id, selectedSeason),
      getOrganizationClients(org.id),
    ]);
    if (timesResult.status === "fulfilled") {
      setDayTimes(normalizeDayTimes(timesResult.value));
    } else {
      setDayTimes(createDefaultDayTimes());
      showSnackbar("Kunne ikke hente standardtider — viser standardværdier.", "warning");
    }
    if (clientsResult.status === "fulfilled") {
      const clients = Array.isArray(clientsResult.value) ? clientsResult.value : [];
      setTimesApprovedClientCount(clients.filter((client) => client?.status === "approved").length);
    }
    setTimesLoading(false);
  };

  const closeTimesDialog = () => {
    if (timesBusy) return;
    setTimesDialogOpen(false);
    setTimesOrganization(null);
    setDayTimes(createDefaultDayTimes());
    setTimesApprovedClientCount(null);
    setOverwriteDialogOpen(false);
    setOverwriteConfirmText("");
  };

  const closeTimesDialogAfterSuccess = () => {
    setTimesDialogOpen(false);
    setTimesOrganization(null);
    setDayTimes(createDefaultDayTimes());
    setTimesApprovedClientCount(null);
    setOverwriteDialogOpen(false);
    setOverwriteConfirmText("");
  };

  const setDayTimeValue = (dayKey, field, value) => {
    const day = DAY_CONFIG.find((item) => item.key === dayKey);
    setDayTimes((prev) => ({
      ...prev,
      [dayKey]: {
        ...(prev?.[dayKey] || day?.fallback || DEFAULT_WEEKDAY),
        [field]: value,
      },
    }));
  };

  const setDayStatus = (dayKey, status) => {
    const day = DAY_CONFIG.find((item) => item.key === dayKey);
    setDayTimes((prev) => ({
      ...prev,
      [dayKey]: {
        ...(prev?.[dayKey] || day?.fallback || DEFAULT_WEEKDAY),
        status,
      },
    }));
  };

  const validateStandardTimes = () => {
    const validationError = validateTimes(dayTimes);
    if (validationError) {
      showSnackbar(validationError, "error");
      return false;
    }
    return true;
  };

  const saveStandardTimesOnly = async () => {
    if (!timesOrganization?.id || !selectedSeason) return;
    if (!validateStandardTimes()) return;

    setTimesSaving(true);
    try {
      const updated = await updateOrganizationTimes(timesOrganization.id, selectedSeason, { day_times: serializeDayTimes(dayTimes) });
      setDayTimes(normalizeDayTimes(updated));
      showSnackbar("Standardtiderne er gemt. Klientkalenderne er ikke ændret.", "success");
      closeTimesDialogAfterSuccess();
    } catch (err) {
      showSnackbar(err?.message || "Kunne ikke gemme standardtiderne.", "error");
    } finally {
      setTimesSaving(false);
    }
  };

  const saveAndApplySafely = async () => {
    if (!timesOrganization?.id || !selectedSeason) return;
    if (!validateStandardTimes()) return;

    setApplyLoading(true);
    try {
      const result = await applyOrganizationSeasonTimes(
        timesOrganization.id,
        selectedSeason,
        { day_times: serializeDayTimes(dayTimes) }
      );
      const clientCount = Array.isArray(result?.updated_clients) ? result.updated_clients.length : 0;
      const changedDays = Number(result?.changed_days || 0);
      const preservedDays = Number(result?.preserved_manual_days || 0);
      showSnackbar(
        `Standardtider gemt og anvendt sikkert på ${clientCount} klient(er): ${changedDays} dag(e) opdateret, ${preservedDays} manuel(le) afvigelse(r) bevaret.`,
        "success"
      );
      closeTimesDialogAfterSuccess();
    } catch (err) {
      showSnackbar(err?.message || "Kunne ikke gemme og anvende tiderne sikkert.", "error");
    } finally {
      setApplyLoading(false);
    }
  };

  const openOverwriteDialog = () => {
    if (!timesOrganization?.id || !selectedSeason) return;
    if (!validateStandardTimes()) return;
    setOverwriteConfirmText("");
    setOverwriteDialogOpen(true);
  };

  const closeOverwriteDialog = () => {
    if (overwriteLoading) return;
    setOverwriteDialogOpen(false);
    setOverwriteConfirmText("");
  };

  const overwriteAllCalendars = async () => {
    if (!timesOrganization?.id || !selectedSeason || overwriteConfirmText.trim().toUpperCase() !== "OVERSKRIV") return;
    setOverwriteLoading(true);
    try {
      const result = await replaceOrganizationSeasonCalendars(
        timesOrganization.id,
        selectedSeason,
        {
          day_times: serializeDayTimes(dayTimes),
          confirmation: "OVERSKRIV",
        }
      );
      const clientCount = Array.isArray(result?.updated_clients) ? result.updated_clients.length : 0;
      showSnackbar(`Alle kalenderdata er overskrevet for ${clientCount} klient(er) i ${selectedSeason}.`, "success");
      closeTimesDialogAfterSuccess();
    } catch (err) {
      showSnackbar(err?.message || "Kunne ikke overskrive klientkalenderne.", "error");
    } finally {
      setOverwriteLoading(false);
    }
  };

  const openDeleteDialog = async (org) => {
    setOrganizationToDelete(org);
    setDeleteConfirmText("");
    setClientsToDelete([]);
    setDeleteDialogOpen(true);
    setLoadingDeleteClients(true);
    try {
      const clients = await getOrganizationClients(org.id);
      setClientsToDelete(Array.isArray(clients) ? clients : []);
    } catch {
      setClientsToDelete([]);
      showSnackbar("Kunne ikke hente tilknyttede klienter.", "warning");
    } finally {
      setLoadingDeleteClients(false);
    }
  };

  const closeDeleteDialog = () => {
    if (deleting) return;
    setDeleteDialogOpen(false);
    setOrganizationToDelete(null);
    setClientsToDelete([]);
    setDeleteConfirmText("");
  };

  const confirmDeleteOrganization = async () => {
    if (!organizationToDelete?.id) return;
    if (normalizeText(deleteConfirmText) !== normalizeText(organizationToDelete.name)) return;

    setDeleting(true);
    try {
      await deleteOrganization(organizationToDelete.id);
      setOrganizations((prev) => prev.filter((org) => Number(org.id) !== Number(organizationToDelete.id)));
      showSnackbar("Organisation slettet.", "success");
      closeDeleteDialog();
    } catch (err) {
      showSnackbar(err?.message || "Kunne ikke slette organisation.", "error");
    } finally {
      setDeleting(false);
    }
  };

  const canConfirmDelete = normalizeText(deleteConfirmText) === normalizeText(organizationToDelete?.name);

  return (
    <Box sx={pageShellSx}>
      <Paper elevation={0} sx={pagePaperSx}>
        <Stack spacing={2}>
          <Stack
            direction={{ xs: "column", md: "row" }}
            spacing={1.5}
            sx={{
              alignItems: { xs: "stretch", md: "flex-start" },
              justifyContent: "space-between"
            }}>
            <Box>
              <Typography variant="h5" sx={{ fontWeight: 950, letterSpacing: -0.3 }}>
                Organisationsadministration
              </Typography>
              <Typography variant="body2" sx={{ color: COLORS.muted, mt: 0.35 }}>
                Administrér organisationer, logo og adgang til kalenderen.
              </Typography>
            </Box>
            <Stack
              direction="row"
              spacing={1}
              useFlexGap
              sx={{
                alignItems: "center",
                flexWrap: "wrap",
                justifyContent: { xs: "flex-start", md: "flex-end" }
              }}>
              <Chip label={`${displayedOrganizations.length} vist`} size="small" sx={compactDarkChipSx("primary")} />
              <Chip label={`${organizations.length} i alt`} size="small" sx={compactDarkChipSx("neutral")} />
              <FormControl size="small" sx={{ minWidth: 160 }}>
                <InputLabel id="organization-season-label">Sæson</InputLabel>
                <Select labelId="organization-season-label" value={selectedSeason} label="Sæson" onChange={(event) => setSelectedSeason(event.target.value)}>
                  {seasonOptions.map((season) => (
                    <MenuItem key={season.value} value={season.value}>
                      {season.label}{season.isCurrent ? " · nu" : ""}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
              <Button size="small" variant="outlined" onClick={fetchOrganizations} disabled={loading} loading={loading} sx={{ borderRadius: 2, fontWeight: 850 }}>
                Opdater
              </Button>
            </Stack>
          </Stack>

          {canCreateOrganizations && (
            <Box sx={{ display: "flex", gap: { xs: 1.2, md: 1.5 }, alignItems: "flex-start", flexWrap: "wrap" }}>
              <TextField
                label="Navn"
                size="small"
                value={name}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => event.key === "Enter" && handleCreate()}
                sx={{ minWidth: { xs: 0, md: 280 }, width: { xs: "100%", sm: "auto" }, flex: { xs: "1 1 100%", sm: "1 1 280px" } }}
              />
              <Button
                variant="contained"
                onClick={handleCreate}
                disabled={loading || !name.trim()}
                loading={loading}
                loadingPosition="start"
                startIcon={<AddBusinessIcon />}
                sx={{ width: { xs: "100%", sm: "auto" }, borderRadius: 2, fontWeight: 900 }}
              >
                Opret organisation
              </Button>
            </Box>
          )}

          <Divider sx={{ borderColor: "rgba(148,163,184,0.12)" }} />

          <Box sx={filterBarSx}>
            <TextField
              size="small"
              placeholder="Søg navn eller ID…"
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              sx={{ minWidth: { xs: 0, md: 280 }, width: { xs: "100%", md: "auto" }, flex: { xs: "1 1 100%", md: "0 0 auto" } }}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" sx={{ color: "text.secondary" }} />
                    </InputAdornment>
                  ),
                  endAdornment: searchText ? (
                    <InputAdornment position="end">
                      <IconButton size="small" onClick={() => setSearchText("")}>
                        <ClearIcon fontSize="small" />
                      </IconButton>
                    </InputAdornment>
                  ) : null,
                }
              }}
            />

            <Stack
              direction="row"
              spacing={0.75}
              sx={{
                alignItems: "center",
                flexWrap: "wrap"
              }}>
              <Typography sx={filterLabelSx}>Sortering</Typography>
              <Tooltip title={sortDirection === "asc" ? "Sorter faldende" : "Sorter stigende"}>
                <Button
                  size="small"
                  variant="outlined"
                  startIcon={sortDirection === "asc" ? <ArrowDownwardIcon /> : <ArrowUpwardIcon />}
                  onClick={() => setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"))}
                  sx={{ borderRadius: 2, fontWeight: 850 }}
                >
                  Navn {sortDirection === "asc" ? "A-Å" : "Å-A"}
                </Button>
              </Tooltip>
            </Stack>

            <Box sx={{ ml: { xs: 0, md: "auto" }, width: { xs: "100%", md: "auto" }, display: "flex", justifyContent: { xs: "space-between", md: "flex-start" }, alignItems: "center", gap: 1 }}>
              <Typography variant="body2" sx={{ color: COLORS.muted, whiteSpace: "nowrap" }}>
                {displayedOrganizations.length} / {organizations.length} organisation{organizations.length !== 1 ? "er" : ""}
              </Typography>
              <Tooltip title="Nulstil filtre">
                <span>
                  <IconButton size="small" onClick={() => setSearchText("")} disabled={!anyFilterActive} color={anyFilterActive ? "primary" : "default"}>
                    <FilterListOffIcon fontSize="small" />
                  </IconButton>
                </span>
              </Tooltip>
            </Box>
          </Box>

          {initialLoading ? (
            <Stack direction="row" spacing={1.2} sx={{
              alignItems: "center"
            }}>
              <CircularProgress size={20} />
              <Typography>Henter organisationer…</Typography>
            </Stack>
          ) : displayedOrganizations.length === 0 ? (
            <Typography sx={{ color: COLORS.muted, py: 2 }}>Ingen organisationer matcher filtrene.</Typography>
          ) : (
            <Grid container spacing={1.5}>
              {displayedOrganizations.map((org) => {
                const isEditing = Number(editingId) === Number(org.id);
                const isHighlighted = Number(highlightedId) === Number(org.id);
                const logoBusy = logoBusyIds.has(org.id);
                const logoUrl = logoUrls[org.id];
                const canManageLogo = !isReadOnly && (isSuperadmin || (canEditOwnLogo && String(user?.organization_id) === String(org.id)));
                const clientCount = clientCounts[org.id];

                return (
                  <Grid
                    key={org.id}
                    size={{
                      xs: 12,
                      md: 6
                    }}>
                    <Paper
                      id={`organization-item-${org.id}`}
                      elevation={0}
                      sx={{
                        p: 1.5,
                        borderRadius: 2,
                        border: isHighlighted ? "2px solid rgba(56,189,248,0.86)" : `1px solid ${COLORS.border}`,
                        background: "rgba(15,23,42,0.52)",
                        color: COLORS.text,
                        boxShadow: isHighlighted ? "0 6px 24px rgba(56,189,248,0.22)" : "none",
                        transition: "box-shadow 250ms ease, border-color 250ms ease, background 250ms ease",
                        height: "100%",
                        "&:hover": { borderColor: COLORS.borderStrong, background: COLORS.panelHover },
                      }}
                    >
                      <Stack spacing={1.4} sx={{ height: "100%" }}>
                        <Stack direction="row" spacing={1.25} sx={{
                          alignItems: "flex-start"
                        }}>
                          <Box sx={{ width: 46, height: 46, borderRadius: 1.6, bgcolor: "rgba(248,250,252,0.08)", border: `1px solid ${COLORS.border}`, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden", flexShrink: 0 }}>
                            {logoUrl ? (
                              <Box component="img" src={logoUrl} alt={`${org.name} logo`} sx={{ width: "100%", height: "100%", objectFit: "contain", p: 0.45 }} />
                            ) : (
                              <Typography sx={{ color: "#94a3b8", fontWeight: 950, fontSize: 17 }}>
                                {(org.name || "?").trim().charAt(0).toUpperCase()}
                              </Typography>
                            )}
                          </Box>

                          <Box sx={{ minWidth: 0, flex: 1 }}>
                            {isEditing ? (
                              <Stack spacing={1}>
                                <TextField size="small" label="Navn" value={editingName} onChange={(event) => setEditingName(event.target.value)} fullWidth autoFocus />
                                <Stack direction="row" spacing={0.75} sx={{
                                  justifyContent: "flex-end"
                                }}>
                                  <IconButton color="success" onClick={() => saveEdit(org)} disabled={loading || !editingName.trim()}>
                                    <CheckIcon />
                                  </IconButton>
                                  <IconButton color="inherit" onClick={cancelEdit}>
                                    <CloseIcon />
                                  </IconButton>
                                </Stack>
                              </Stack>
                            ) : (
                              <>
                                <Typography sx={{ fontWeight: 950, fontSize: 15.5, lineHeight: 1.25, overflow: "hidden", textOverflow: "ellipsis" }}>
                                  {org.name}
                                </Typography>
                                <Stack
                                  direction="row"
                                  spacing={0.75}
                                  useFlexGap
                                  sx={{
                                    alignItems: "center",
                                    flexWrap: "wrap",
                                    mt: 0.75
                                  }}>
                                  <Chip size="small" label={`ID ${org.id}`} sx={compactDarkChipSx("neutral")} />
                                  <Chip
                                    size="small"
                                    label={clientCountsLoading ? "Henter klienter…" : `${clientCount ?? "?"} klient${Number(clientCount) === 1 ? "" : "er"}`}
                                    sx={compactDarkChipSx("info")}
                                  />
                                </Stack>
                              </>
                            )}
                          </Box>
                        </Stack>

                        {!isEditing && (
                          <Stack
                            direction="row"
                            spacing={0.75}
                            useFlexGap
                            sx={{
                              flexWrap: "wrap",
                              mt: "auto"
                            }}>
                            <Button size="small" variant="contained" startIcon={<CalendarMonthIcon />} onClick={() => openOrganizationCalendar(org)} sx={{ borderRadius: 2, fontWeight: 900 }}>
                              Åbn kalender
                            </Button>
                            <Button size="small" variant="outlined" startIcon={<SettingsSuggestIcon />} onClick={() => openTimesDialog(org)} disabled={isReadOnly} sx={{ borderRadius: 2, fontWeight: 850 }}>
                              Standardtider
                            </Button>

                            {canManageLogo && (
                              <>
                                <input id={`organization-logo-input-${org.id}`} type="file" accept={LOGO_ACCEPT} style={{ display: "none" }} onChange={(event) => handleLogoUpload(org, event)} />
                                <label htmlFor={`organization-logo-input-${org.id}`}>
                                  <Button component="span" size="small" variant="outlined" startIcon={<AddPhotoAlternateIcon fontSize="small" />} loading={logoBusy} loadingPosition="start" disabled={logoBusy} sx={{ borderRadius: 2, fontWeight: 850 }}>
                                    {org.has_logo ? "Skift logo" : "Upload logo"}
                                  </Button>
                                </label>
                                {org.has_logo && (
                                  <Button size="small" color="inherit" variant="outlined" startIcon={<DeleteOutlinedIcon fontSize="small" />} onClick={() => handleLogoDelete(org)} disabled={logoBusy} sx={{ borderRadius: 2, fontWeight: 850 }}>
                                    Fjern
                                  </Button>
                                )}
                              </>
                            )}

                            {canEditOrganizations && (
                              <Tooltip title="Rediger navn">
                                <span>
                                  <IconButton size="small" color="primary" onClick={() => startEdit(org)}>
                                    <EditIcon fontSize="small" />
                                  </IconButton>
                                </span>
                              </Tooltip>
                            )}
                            {canDeleteOrganizations && (
                              <Tooltip title="Slet organisation">
                                <span>
                                  <IconButton size="small" color="error" onClick={() => openDeleteDialog(org)}>
                                    <DeleteIcon fontSize="small" />
                                  </IconButton>
                                </span>
                              </Tooltip>
                            )}
                          </Stack>
                        )}
                      </Stack>
                    </Paper>
                  </Grid>
                );
              })}
            </Grid>
          )}
        </Stack>
      </Paper>
      <Dialog open={timesDialogOpen} onClose={closeTimesDialog} maxWidth="md" fullWidth slotProps={{
        paper: DarkDialogPaper()
      }}>
        <DialogTitle>
          <Stack direction="row" spacing={1.2} sx={{
            alignItems: "center"
          }}>
            <SettingsSuggestIcon color="primary" />
            <Box>
              <Typography sx={{ fontWeight: 950 }}>Standardtider</Typography>
              <Typography variant="body2" sx={{ color: COLORS.muted }}>{timesOrganization?.name} · {selectedSeason}</Typography>
            </Box>
          </Stack>
        </DialogTitle>
        <DialogContent>
          {timesLoading ? (
            <Stack
              direction="row"
              spacing={1.2}
              sx={{
                alignItems: "center",
                py: 2
              }}>
              <CircularProgress size={22} />
              <Typography>Henter standardtider…</Typography>
            </Stack>
          ) : (
            <Stack spacing={2} sx={{ mt: 0.5 }}>
              <Alert severity="info">
                Gem kun ændrer organisationens standardtider. Gem og anvend sikkert opdaterer almindelige standarddage, men bevarer manuelle afvigelser. Fuld overskrivning er en særskilt handling.
              </Alert>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "repeat(2, minmax(0, 1fr))" }, gap: 1 }}>
                {DAY_CONFIG.map((day) => {
                  const value = dayTimes?.[day.key] || day.fallback;
                  return (
                    <DayTimeCard
                      key={day.key}
                      day={day}
                      value={value}
                      disabled={timesBusy}
                      onStatusChange={(status) => setDayStatus(day.key, status)}
                      onTimeChange={(field, nextValue) => setDayTimeValue(day.key, field, nextValue)}
                    />
                  );
                })}
              </Box>
            </Stack>
          )}
        </DialogContent>
        <DialogActions sx={{ flexWrap: "wrap", gap: 1 }}>
          <Button onClick={() => setDayTimes(createDefaultDayTimes())} color="warning" disabled={timesLoading || timesBusy}>
            Nulstil
          </Button>
          <Button color="error" variant="outlined" onClick={openOverwriteDialog} disabled={timesLoading || timesBusy} startIcon={<DeleteOutlinedIcon />}>
            Overskriv alle kalendere
          </Button>
          <Box sx={{ flex: 1 }} />
          <Button onClick={closeTimesDialog} disabled={timesBusy}>Annullér</Button>
          <Button variant="outlined" onClick={saveStandardTimesOnly} disabled={timesLoading || timesBusy} startIcon={<CheckIcon />} loading={timesSaving} loadingPosition="start">
            Gem standardtider
          </Button>
          <Button variant="contained" onClick={saveAndApplySafely} disabled={timesLoading || timesBusy} startIcon={<CheckIcon />} loading={applyLoading} loadingPosition="start">
            Gem og anvend sikkert
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={overwriteDialogOpen} onClose={closeOverwriteDialog} maxWidth="sm" fullWidth slotProps={{
        paper: DarkDialogPaper()
      }}>
        <DialogTitle>
          <Stack direction="row" spacing={1.2} sx={{
            alignItems: "center"
          }}>
            <WarningAmberIcon color="error" />
            <Box>
              <Typography sx={{ fontWeight: 950 }}>Overskriv alle klientkalendere</Typography>
              <Typography variant="body2" sx={{ color: COLORS.muted }}>
                {timesOrganization?.name} · {selectedSeason}
              </Typography>
            </Box>
          </Stack>
        </DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 0.5 }}>
            <Alert severity="error">
              Alle manuelle tider, slukkede dage, ferier og øvrige undtagelser i den valgte sæson bliver slettet og erstattet med standardtiderne ovenfor.
            </Alert>
            <Typography>
              Handlingen berører {timesApprovedClientCount == null ? "alle godkendte klienter" : `${timesApprovedClientCount} godkendte klient${timesApprovedClientCount === 1 ? "" : "er"}`} og kan ikke fortrydes.
            </Typography>
            <TextField
              label="Skriv OVERSKRIV for at bekræfte"
              value={overwriteConfirmText}
              onChange={(event) => setOverwriteConfirmText(event.target.value)}
              fullWidth
              autoFocus
              disabled={overwriteLoading}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeOverwriteDialog} disabled={overwriteLoading}>Annullér</Button>
          <Button
            color="error"
            variant="contained"
            onClick={overwriteAllCalendars}
            disabled={overwriteLoading || overwriteConfirmText.trim().toUpperCase() !== "OVERSKRIV"}
            loading={overwriteLoading}
            loadingPosition="start"
            startIcon={<DeleteOutlinedIcon />}
          >
            {timesApprovedClientCount == null
              ? "Overskriv alle kalendere"
              : `Overskriv ${timesApprovedClientCount} kalender${timesApprovedClientCount === 1 ? "" : "e"}`}
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog open={deleteDialogOpen} onClose={closeDeleteDialog} maxWidth="sm" fullWidth slotProps={{
        paper: DarkDialogPaper()
      }}>
        <DialogTitle>
          <Stack direction="row" spacing={1.2} sx={{
            alignItems: "center"
          }}>
            <WarningAmberIcon color="error" />
            <Box>
              <Typography sx={{ fontWeight: 950 }}>Slet organisation</Typography>
              <Typography variant="body2" sx={{ color: COLORS.muted }}>{organizationToDelete?.name}</Typography>
            </Box>
          </Stack>
        </DialogTitle>
        <DialogContent>
          <Stack spacing={1.5} sx={{ mt: 0.5 }}>
            <Alert severity="error">
              Denne handling kan ikke fortrydes. Organisationen og tilknyttede kalender-/standardtider fjernes.
            </Alert>
            {loadingDeleteClients ? (
              <Stack direction="row" spacing={1.2} sx={{
                alignItems: "center"
              }}>
                <CircularProgress size={22} />
                <Typography>Henter tilknyttede klienter…</Typography>
              </Stack>
            ) : clientsToDelete.length > 0 ? (
              <Paper elevation={0} sx={{ p: 1.4, maxHeight: 220, overflowY: "auto", borderRadius: 2, border: `1px solid ${COLORS.border}`, background: COLORS.panelSoft }}>
                <Typography sx={{ fontWeight: 900, mb: 1 }}>Tilknyttede klienter</Typography>
                <Stack spacing={0.6}>
                  {clientsToDelete.map((client) => (
                    <Typography key={client.id} variant="body2" sx={{ color: COLORS.muted }}>
                      #{client.id} · {client.locality || client.name || "Ingen lokation"}
                    </Typography>
                  ))}
                </Stack>
              </Paper>
            ) : (
              <Alert severity="info">Ingen klienter er tilknyttet denne organisation.</Alert>
            )}
            <DialogContentText sx={{ color: COLORS.muted }}>
              Skriv organisationsnavnet for at bekræfte sletning.
            </DialogContentText>
            <TextField
              size="small"
              fullWidth
              label={`Skriv: ${organizationToDelete?.name || ""}`}
              value={deleteConfirmText}
              onChange={(event) => setDeleteConfirmText(event.target.value)}
              disabled={deleting}
              error={!!deleteConfirmText && !canConfirmDelete}
              helperText={canConfirmDelete ? " " : "Navnet matcher ikke."}
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={closeDeleteDialog} disabled={deleting}>Annullér</Button>
          <Button color="error" variant="contained" onClick={confirmDeleteOrganization} disabled={deleting || !canConfirmDelete} loading={deleting} loadingPosition="start" startIcon={<DeleteIcon />}>
            Slet endeligt
          </Button>
        </DialogActions>
      </Dialog>
      <AppSnackbar
        open={Boolean(error)}
        message={error}
        severity="error"
        onClose={() => setError("")}
      />
      <AppSnackbar
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={closeSnackbar}
      />
    </Box>
  );
}
