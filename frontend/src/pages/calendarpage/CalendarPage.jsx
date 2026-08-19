import AppSnackbar from "../../components/AppSnackbar";
import React, {
  useState,
  useEffect,
  useMemo,
  useCallback,
  useRef,
  useReducer,
} from "react";
import { useSearchParams } from "react-router-dom";
import {
  Box,
  Card,
  CardContent,
  Typography,
  Button,
  CircularProgress,
  Paper,
  Checkbox,
  TextField,
  Tooltip,
  Select,
  MenuItem,
  Stack,
  Chip,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import CalendarMonthIcon from "@mui/icons-material/CalendarMonth";
import {
  getClients,
  saveMarkedDays,
  getMarkedDays,
  getOrganizations,
  getOrganizationTimes,
  getOrganizationSeasonSummary,
} from "../../api";
import DateTimeEditDialog from "./DateTimeEditDialog";
import ClientCalendarDialog from "./ClientCalendarDialog";
import { useAuth } from "../../auth/AuthProvider";
import { compactDarkChipSx } from "../../utils/chipStyles";
import SeasonPreparationAlert from "../../season/SeasonPreparationAlert";
import { useSeasonClock, useSeasonSelection } from "../../season/SeasonProvider";
import {
  pageHeaderIconSx,
  pageHeaderPaperSx,
  pageShellSx,
} from "../../utils/layoutStyles";

function useAllOrganizationTimes(organizations, season) {
  const [organizationTimesMap, setOrganizationTimesMap] = useState({});
  useEffect(() => {
    if (!organizations || organizations.length === 0 || !season) return;
    let isCurrent = true;
    Promise.all(
      organizations.map((s) =>
        getOrganizationTimes(s.id, season)
          .then((times) => ({ id: s.id, times }))
          .catch(() => ({ id: s.id, times: null })),
      ),
    ).then((results) => {
      if (!isCurrent) return;
      const map = {};
      results.forEach(({ id, times }) => {
        map[id] = times;
      });
      setOrganizationTimesMap(map);
    });
    return () => {
      isCurrent = false;
    };
  }, [organizations, season]);
  return organizationTimesMap;
}

const monthNames = [
  "August",
  "September",
  "Oktober",
  "November",
  "December",
  "Januar",
  "Februar",
  "Marts",
  "April",
  "Maj",
  "Juni",
  "Juli",
];
const weekdayNames = ["Ma", "Ti", "On", "To", "Fr", "Lø", "Sø"];

function seasonToStartYear(season) {
  if (!season) return new Date().getFullYear();
  if (typeof season === "number") return season;
  return parseInt(season.split("/")[0], 10);
}

function getSeasonYearMonths(season) {
  const seasonStart = seasonToStartYear(season);
  return [
    ...Array.from({ length: 5 }, (_, i) => ({
      name: monthNames[i],
      month: i + 7,
      year: seasonStart,
    })),
    ...Array.from({ length: 7 }, (_, i) => ({
      name: monthNames[i + 5],
      month: i,
      year: seasonStart + 1,
    })),
  ];
}

const getDaysInMonth = (month, year) => new Date(year, month + 1, 0).getDate();
const formatDate = (year, month, day) =>
  `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
const stripTimeFromDateKey = (key) => key.split("T")[0];
const deepEqual = (obj1, obj2) => JSON.stringify(obj1) === JSON.stringify(obj2);

function getWeekNumber(date) {
  const d = new Date(
    Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()),
  );
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil(((d - yearStart) / 86400000 + 1) / 7);
}

function mapRawDays(rawDays) {
  const mapped = {};
  Object.keys(rawDays).forEach((key) => {
    mapped[stripTimeFromDateKey(key)] = rawDays[key];
  });
  return mapped;
}

function getOrganizationId(entity) {
  return (
    entity?.organization_id ??
    entity?.organizationId ??
    entity?.school_id ??
    entity?.schoolId ??
    ""
  );
}

function getOrganizationName(organizations, client) {
  const organizationId = getOrganizationId(client);
  return (
    organizations.find((s) => String(s.id) === String(organizationId))?.name ||
    "Ukendt organisation"
  );
}

function getTodayInfo() {
  const today = new Date();
  return {
    todayStr: formatDate(
      today.getFullYear(),
      today.getMonth(),
      today.getDate(),
    ),
    currentMonth: today.getMonth(),
    currentYear: today.getFullYear(),
  };
}

function useTodayInfo() {
  const [todayInfo, setTodayInfo] = useState(() => getTodayInfo());

  useEffect(() => {
    const timer = window.setInterval(() => {
      const next = getTodayInfo();
      setTodayInfo((prev) => (prev.todayStr === next.todayStr ? prev : next));
    }, 60_000);

    return () => window.clearInterval(timer);
  }, []);

  return todayInfo;
}

const ClientSelectorInline = React.memo(function ClientSelectorInline({
  clients,
  selected,
  onChange,
  organizations,
  disabled,
  selectedOrganization,
}) {
  const [search, setSearch] = useState("");
  const sortedClients = useMemo(
    () =>
      [...clients].sort((a, b) =>
        (a.locality || a.name || "")
          .toLowerCase()
          .localeCompare((b.locality || b.name || "").toLowerCase()),
      ),
    [clients],
  );
  const filteredClients = useMemo(
    () =>
      sortedClients.filter((c) =>
        (c.locality || c.name || "")
          .toLowerCase()
          .includes(search.toLowerCase()),
      ),
    [sortedClients, search],
  );
  const allVisibleIds = filteredClients.map((c) => c.id);
  const allMarked =
    allVisibleIds.length > 0 &&
    allVisibleIds.every((id) => selected.includes(id));
  const handleToggleAll = () => {
    if (disabled) return;
    if (allMarked)
      onChange(selected.filter((id) => !allVisibleIds.includes(id)));
    else onChange(Array.from(new Set([...selected, ...allVisibleIds])));
  };
  return (
    <Box>
      <Box
        sx={{
          display: "flex",
          flexDirection: { xs: "column", sm: "row" },
          alignItems: { xs: "stretch", sm: "center" },
          mb: 2,
          gap: { xs: 1, sm: 2 },
        }}
      >
        <TextField
          label="Søg klient"
          variant="outlined"
          size="small"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          disabled={disabled}
          sx={{ width: { xs: "100%", sm: 220 } }}
        />
        <Button
          sx={{ minWidth: 0, px: 2, width: { xs: "100%", sm: "auto" } }}
          variant={allMarked ? "contained" : "outlined"}
          color={allMarked ? "success" : "primary"}
          onClick={handleToggleAll}
          disabled={disabled}
        >
          {allMarked ? "Fjern alle" : "Markér alle"}
        </Button>
      </Box>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            sm: "1fr 1fr",
            md: "repeat(5, 1fr)",
          },
          gap: { xs: 1, sm: 2, md: 2 },
        }}
      >
        {filteredClients.map((client) => (
          <Box
            key={client.id}
            sx={{
              display: "flex",
              alignItems: "center",
              px: { xs: 0.5, sm: 1 },
              py: { xs: 0.5, sm: 0.5 },
              background: selected.includes(client.id)
                ? "rgba(56,189,248,0.14)"
                : "rgba(15,23,42,0.28)",
              borderRadius: 2,
              cursor: disabled ? "not-allowed" : "pointer",
              border: "1px solid rgba(148,163,184,0.12)",
              color: "rgba(226,232,240,0.92)",
              ":hover": {
                background: disabled
                  ? "rgba(15,23,42,0.28)"
                  : "rgba(56,189,248,0.10)",
              },
            }}
            onClick={() => {
              if (disabled) return;
              onChange(
                selected.includes(client.id)
                  ? selected.filter((sid) => sid !== client.id)
                  : [...selected, client.id],
              );
            }}
          >
            <Checkbox
              edge="start"
              checked={selected.includes(client.id)}
              tabIndex={-1}
              disableRipple
              sx={{ p: 0, pr: 1, minWidth: { xs: 32, sm: 28 } }}
              disabled={disabled}
            />
            {selectedOrganization ? (
              <Typography
                variant="body2"
                sx={{
                  fontWeight: 400,
                  fontSize: { xs: "1.05rem", sm: "0.98rem", md: "0.92rem" },
                  lineHeight: 1.18,
                  wordBreak: "break-word",
                }}
              >
                {client.locality || client.name || "Ingen lokalitet"}
              </Typography>
            ) : (
              <Box sx={{ width: "100%" }}>
                <Typography
                  variant="body2"
                  sx={{
                    fontWeight: 700,
                    fontSize: { xs: "1.05rem", sm: "0.98rem", md: "0.92rem" },
                    lineHeight: 1.18,
                    wordBreak: "break-word",
                  }}
                >
                  {getOrganizationName(organizations, client)}
                </Typography>
                <Typography
                  variant="body2"
                  sx={{
                    fontWeight: 400,
                    fontSize: { xs: "0.98rem", sm: "0.94rem", md: "0.88rem" },
                    lineHeight: 1.12,
                    wordBreak: "break-word",
                  }}
                >
                  {client.locality || client.name || "Ingen lokalitet"}
                </Typography>
              </Box>
            )}
          </Box>
        ))}
      </Box>
    </Box>
  );
});

function markedDaysReducer(state, action) {
  switch (action.type) {
    case "set":
      return { ...state, [action.clientId]: action.days };
    case "updateDay": {
      const existing = state[action.clientId]?.[action.date] || {};
      const merged = { ...existing, ...action.dayData };
      if (action.dayData.status === "off") {
        delete merged.onTime;
        delete merged.offTime;
      }
      return {
        ...state,
        [action.clientId]: {
          ...(state[action.clientId] || {}),
          [action.date]: merged,
        },
      };
    }
    case "reset":
      return {};
    default:
      return state;
  }
}

export default function CalendarPage() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const requestedOrganizationId =
    searchParams.get("organizationId") ||
    searchParams.get("organization_id") ||
    "";
  const requestedSeason = searchParams.get("season") || "";
  const appliedCalendarDeepLinkRef = useRef(false);
  const token = null;
  const isSuperadmin = user?.role === "superadmin";
  const isAdmin = user?.role === "admin";
  const isViewer = user?.role === "viewer";
  const isReadOnly = isViewer;
  const isRestrictedOrgRole = user?.role === "admin" || user?.role === "bruger";

  const {
    currentSeason,
    seasonOptions,
    loading: seasonClockLoading,
  } = useSeasonClock();
  const { selectedSeason, setSelectedSeason } = useSeasonSelection(
    seasonOptions,
    { preferredSeason: requestedSeason },
  );
  const todayInfo = useTodayInfo();

  const [organizations, setOrganizations] = useState([]);
  const [selectedOrganization, setSelectedOrganization] = useState("");
  const [clients, setClients] = useState([]);
  const [selectedClients, setSelectedClients] = useState([]);
  const [activeClient, setActiveClient] = useState(null);
  const [loadingClients, setLoadingClients] = useState(false);
  const [markMode, setMarkMode] = useState("on");
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [editDialogDate, setEditDialogDate] = useState(null);
  const [editDialogClient, setEditDialogClient] = useState(null);
  const [loadingDialogDate, setLoadingDialogDate] = useState(null);
  const [loadingDialogClient, setLoadingDialogClient] = useState(null);
  const [savingCalendar, setSavingCalendar] = useState(false);
  const [calendarDialogOpen, setCalendarDialogOpen] = useState(false);
  const [snackbar, setSnackbar] = useState({
    open: false,
    message: "",
    severity: "success",
  });
  const snackbarTimer = useRef(null);
  const autoSaveTimer = useRef(null);
  const lastDialogSavedMarkedDays = useRef({});
  const lastDialogSavedTimestamp = useRef(0);

  // NY: sæson-summary til filtrering (kun superadmin/admin)
  const [seasonSummary, setSeasonSummary] = useState({});
  const [loadingSeasonSummary, setLoadingSeasonSummary] = useState(false);

  useEffect(() => {
    if (!isSuperadmin && !isAdmin) return;
    setLoadingSeasonSummary(true);
    getOrganizationSeasonSummary()
      .then((data) => setSeasonSummary(data || {}))
      .catch(() => setSeasonSummary({}))
      .finally(() => setLoadingSeasonSummary(false));
  }, [isSuperadmin, isAdmin]);

  // Backendens autoritative liste indeholder altid præcis nuværende og næste sæson.
  const availableSeasons = useMemo(() => (
    (seasonOptions || [])
      .map((item) => String(item?.value ?? item?.id ?? item?.season ?? ""))
      .filter(Boolean)
  ), [seasonOptions]);

  // Organisationer i valgt sæson. Hvis sæsonen endnu ikke har data, viser vi stadig
  // de organisationer brugeren har adgang til, så nye sæsoner kan oprettes/arbejdes med.
  const availableOrganizationsForSeason = useMemo(() => {
    if (!isSuperadmin && !isAdmin) return [];
    const organizationsInSeason = seasonSummary[selectedSeason] || [];
    const source =
      organizationsInSeason.length > 0 ? organizationsInSeason : organizations;
    const allowed =
      isAdmin && getOrganizationId(user)
        ? source.filter(
            (organization) =>
              String(organization.id) === String(getOrganizationId(user)),
          )
        : source;
    return [...allowed].sort((a, b) =>
      String(a.name || "").localeCompare(String(b.name || ""), "da"),
    );
  }, [
    seasonSummary,
    selectedSeason,
    organizations,
    isSuperadmin,
    isAdmin,
    user,
  ]);

  // Når sæson ændres — reset kun organisation hvis summary faktisk har data og
  // den valgte organisation ikke er en del af sæsonen. Nye/tomme sæsoner skal stadig kunne vælges.
  useEffect(() => {
    if (!isSuperadmin && !isAdmin) return;
    if (isAdmin && getOrganizationId(user)) {
      const ownOrganizationId = String(getOrganizationId(user));
      if (String(selectedOrganization) !== ownOrganizationId) {
        setSelectedOrganization(ownOrganizationId);
        setSelectedClients([]);
        setActiveClient(null);
      }
      return;
    }
    const organizationsInSeason = seasonSummary[selectedSeason] || [];
    if (!organizationsInSeason.length) return;
    const organizationIds = organizationsInSeason.map((s) => String(s.id));
    if (
      selectedOrganization &&
      !organizationIds.includes(String(selectedOrganization))
    ) {
      setSelectedOrganization("");
      setSelectedClients([]);
      setActiveClient(null);
    }
  }, [
    selectedSeason,
    seasonSummary,
    selectedOrganization,
    isSuperadmin,
    isAdmin,
    user,
  ]);

  const [fadeIn, setFadeIn] = useState(true);
  useEffect(() => {
    let timer;
    if (selectedSeason !== currentSeason) {
      timer = setInterval(() => setFadeIn((f) => !f), 1200);
    } else {
      setFadeIn(true);
    }
    return () => timer && clearInterval(timer);
  }, [selectedSeason, currentSeason]);

  useEffect(() => {
    getOrganizations(token)
      .then(setOrganizations)
      .catch(() => setOrganizations([]));
  }, [token]);

  useEffect(() => {
    if (appliedCalendarDeepLinkRef.current) return;

    if (!requestedOrganizationId) {
      appliedCalendarDeepLinkRef.current = true;
      return;
    }

    if (!organizations.length) return;

    const isAllowedOrganization =
      isSuperadmin ||
      String(getOrganizationId(user)) === String(requestedOrganizationId);
    const exists = organizations.some(
      (organization) =>
        String(organization.id) === String(requestedOrganizationId),
    );

    if (isAllowedOrganization && exists) {
      setSelectedOrganization(requestedOrganizationId);
      setSelectedClients([]);
      setActiveClient(null);
    }

    appliedCalendarDeepLinkRef.current = true;
  }, [
    organizations,
    requestedOrganizationId,
    isSuperadmin,
    user,
  ]);

  const allOrganizationTimes = useAllOrganizationTimes(
    organizations,
    selectedSeason,
  );

  const fetchClients = useCallback(
    async (showSuccess = false) => {
      setLoadingClients(true);
      try {
        const data = await getClients(token);
        setClients(data?.filter((c) => c.status === "approved") || []);
        if (showSuccess)
          setSnackbar({
            open: true,
            message: "Opdateret!",
            severity: "success",
          });
      } catch {
        setClients([]);
        setSnackbar({
          open: true,
          message: "Kunne ikke hente klienter.",
          severity: "error",
        });
      }
      setLoadingClients(false);
    },
    [token],
  );

  useEffect(() => {
    fetchClients();
  }, [fetchClients]);

  const filteredClients = useMemo(() => {
    if (isRestrictedOrgRole && getOrganizationId(user)) {
      return clients.filter(
        (c) => String(getOrganizationId(c)) === String(getOrganizationId(user)),
      );
    }
    return selectedOrganization === ""
      ? clients
      : clients.filter(
          (c) => String(getOrganizationId(c)) === String(selectedOrganization),
        );
  }, [clients, selectedOrganization, user, isRestrictedOrgRole]);

  useEffect(() => {
    if (isRestrictedOrgRole && user?.client_id) {
      const organizationClients = filteredClients.map((c) => c.id);
      if (!organizationClients.includes(selectedClients[0])) {
        setSelectedClients([user.client_id]);
        setActiveClient(user.client_id);
      }
    }
  }, [user, filteredClients, isRestrictedOrgRole, selectedClients]);

  const [markedDays, dispatchMarkedDays] = useReducer(markedDaysReducer, {});

  useEffect(() => {
    if (!activeClient) return;
    dispatchMarkedDays({
      type: "set",
      clientId: activeClient,
      days: undefined,
    });
    let isCurrent = true;
    getMarkedDays(selectedSeason, activeClient)
      .then((data) => {
        if (!isCurrent) return;
        const mapped = mapRawDays(data.markedDays || {});
        dispatchMarkedDays({
          type: "set",
          clientId: activeClient,
          days: mapped,
        });

        // Baseline skal sættes ved load. Ellers kan autosave-effekten opfatte
        // nyindlæste backend-data som lokale ændringer og gemme unødigt igen.
        lastDialogSavedMarkedDays.current = {
          ...lastDialogSavedMarkedDays.current,
          [activeClient]: mapped,
        };
      })
      .catch(() => {
        if (isCurrent) {
          dispatchMarkedDays({ type: "set", clientId: activeClient, days: {} });
          lastDialogSavedMarkedDays.current = {
            ...lastDialogSavedMarkedDays.current,
            [activeClient]: {},
          };
          setSnackbar({
            open: true,
            message: "Kunne ikke hente kalender.",
            severity: "error",
          });
        }
      });
    return () => {
      isCurrent = false;
    };
  }, [selectedSeason, activeClient, token]);

  const getDefaultTimes = useCallback((dateStr, clientId) => {
    const client = clients.find((c) => c.id === clientId);
    const date = new Date(dateStr);
    const day = Number.isNaN(date.getTime()) ? 1 : date.getDay();
    const dayKeys = [
      "sunday",
      "monday",
      "tuesday",
      "wednesday",
      "thursday",
      "friday",
      "saturday",
    ];
    const dayKey = dayKeys[day];
    const fallback =
      day === 0 || day === 6
        ? { status: "off", onTime: "09:00", offTime: "20:00" }
        : { status: "on", onTime: "09:00", offTime: "20:00" };

    if (!client) return fallback;

    const organizationId = getOrganizationId(client);
    const organizationTimes = allOrganizationTimes[organizationId];
    const dayTimes = organizationTimes?.day_times || organizationTimes;
    const value = dayTimes?.[dayKey];
    const status = String(value?.status || value?.state || "on").toLowerCase();

    if (status === "off" || status === "closed" || value?.enabled === false) {
      // Dagen er standard-slukket. Behold fallback-tider som forslag,
      // hvis brugeren manuelt tænder datoen i kalenderen.
      return { ...fallback, status: "off" };
    }

    if (value?.onTime && value?.offTime) {
      return { status: "on", onTime: value.onTime, offTime: value.offTime };
    }

    return fallback;
  }, [clients, allOrganizationTimes]);

  const handleDayClick = useCallback(
    (clientIds, dateString, mode) => {
      if (isReadOnly) return;
      clientIds.forEach((cid) => {
        dispatchMarkedDays({
          type: "updateDay",
          clientId: cid,
          date: dateString,
          dayData: { status: mode },
        });
      });
    },
    [isReadOnly],
  );

  const handleDateShiftLeftClick = useCallback(
    (clientId, date) => {
      if (isReadOnly) return;
      if (autoSaveTimer.current) {
        clearTimeout(autoSaveTimer.current);
        autoSaveTimer.current = null;
      }
      setLoadingDialogDate(date);
      setLoadingDialogClient(clientId);
      setTimeout(() => {
        setEditDialogClient(clientId);
        setEditDialogDate(date);
        setEditDialogOpen(true);
        setLoadingDialogDate(null);
        setLoadingDialogClient(null);
      }, 1100);
    },
    [isReadOnly],
  );

  const handleSaveSingleClient = useCallback(async (clientId) => {
    if (isReadOnly || !clientId) return;
    const allDates = [];
    getSeasonYearMonths(selectedSeason).forEach(({ month, year }) => {
      for (let d = 1; d <= getDaysInMonth(month, year); d += 1) {
        allDates.push(formatDate(year, month, d));
      }
    });
    const currentClientDays = markedDays[clientId] || {};
    const payloadMarkedDays = { [String(clientId)]: {} };
    allDates.forEach((dateStr) => {
      const md = currentClientDays[dateStr];
      const defTimes = getDefaultTimes(dateStr, clientId);
      payloadMarkedDays[String(clientId)][dateStr] =
        md && md.status === "on"
          ? {
              status: "on",
              onTime: md.onTime || defTimes.onTime,
              offTime: md.offTime || defTimes.offTime,
            }
          : { status: "off" };
    });
    try {
      await saveMarkedDays({
        clients: [clientId],
        markedDays: payloadMarkedDays,
        season: selectedSeason,
      });
      lastDialogSavedMarkedDays.current = {
        ...lastDialogSavedMarkedDays.current,
        [clientId]: currentClientDays,
      };
      lastDialogSavedTimestamp.current = Date.now();
    } catch (error) {
      setSnackbar({
        open: true,
        message: error?.message || "Kunne ikke autosave!",
        severity: "error",
      });
    }
  }, [getDefaultTimes, isReadOnly, markedDays, selectedSeason]);

  const activeClientMarkedDays = activeClient ? markedDays[activeClient] : undefined;

  useEffect(() => {
    if (editDialogOpen || !activeClient || activeClientMarkedDays === undefined) {
      return undefined;
    }

    if (autoSaveTimer.current) {
      window.clearTimeout(autoSaveTimer.current);
      autoSaveTimer.current = null;
    }

    const baseline = lastDialogSavedMarkedDays.current[activeClient];
    if (baseline === undefined) {
      lastDialogSavedMarkedDays.current = {
        ...lastDialogSavedMarkedDays.current,
        [activeClient]: activeClientMarkedDays,
      };
      return undefined;
    }

    if (deepEqual(activeClientMarkedDays, baseline)) return undefined;

    const timerId = window.setTimeout(() => {
      handleSaveSingleClient(activeClient);
    }, 1000);
    autoSaveTimer.current = timerId;

    return () => {
      window.clearTimeout(timerId);
      if (autoSaveTimer.current === timerId) autoSaveTimer.current = null;
    };
  }, [activeClient, activeClientMarkedDays, editDialogOpen, handleSaveSingleClient]);

  const handleClientSelectorChange = (newSelected) => {
    if (isRestrictedOrgRole) {
      const organizationClients = filteredClients.map((c) => c.id);
      const kunEgne = newSelected.filter((id) =>
        organizationClients.includes(id),
      );
      setSelectedClients(kunEgne);
      if (!kunEgne.includes(activeClient))
        setActiveClient(
          kunEgne.length > 0 ? kunEgne[kunEgne.length - 1] : null,
        );
    } else {
      setSelectedClients(newSelected);
      if (!newSelected.includes(activeClient))
        setActiveClient(
          newSelected.length > 0 ? newSelected[newSelected.length - 1] : null,
        );
    }
  };

  const handleSaveDateTime = ({ date, clientId, day }) => {
    if (isReadOnly) return;
    if (!clientId || !date) return;
    if (day) {
      dispatchMarkedDays({ type: "updateDay", clientId, date, dayData: day });
      lastDialogSavedMarkedDays.current = {
        ...lastDialogSavedMarkedDays.current,
        [clientId]: {
          ...(lastDialogSavedMarkedDays.current[clientId] || {}),
          [date]: day,
        },
      };
      lastDialogSavedTimestamp.current = Date.now();
      setSnackbar({ open: true, message: "Gemt!", severity: "success" });
      return;
    }
    (async () => {
      try {
        const data = await getMarkedDays(selectedSeason, clientId);
        const mapped = mapRawDays(data.markedDays || {});
        dispatchMarkedDays({ type: "set", clientId, days: mapped });
        lastDialogSavedMarkedDays.current = {
          ...lastDialogSavedMarkedDays.current,
          [clientId]: mapped,
        };
        lastDialogSavedTimestamp.current = Date.now();
        setSnackbar({ open: true, message: "Gemt!", severity: "success" });
      } catch {
        setSnackbar({
          open: true,
          message: "Kunne ikke hente nyeste tider",
          severity: "error",
        });
      }
    })();
  };

  const seasonYearMonths = useMemo(
    () => getSeasonYearMonths(selectedSeason),
    [selectedSeason],
  );

  const otherClientNames = useMemo(
    () =>
      selectedClients.length > 1
        ? filteredClients
            .filter(
              (c) => selectedClients.includes(c.id) && c.id !== activeClient,
            )
            .map(
              (c) =>
                `${c.locality || c.name} – ${getOrganizationName(organizations, c)}`,
            )
            .filter(Boolean)
            .join("; ")
        : "",
    [selectedClients, filteredClients, activeClient, organizations],
  );

  const activeClientName = useMemo(
    () =>
      activeClient
        ? (() => {
            const c = filteredClients.find((c) => c.id === activeClient);
            const organizationName = getOrganizationName(
              organizations,
              c || {},
            );
            return c
              ? `${c.locality || c.name}${organizationName ? " – " + organizationName : ""}`
              : "Automatisk";
          })()
        : "Automatisk",
    [activeClient, filteredClients, organizations],
  );

  const handleSave = useCallback(
    async (showSuccessFeedback = false) => {
      if (isReadOnly) {
        setSnackbar({
          open: true,
          message: "Se adgang har kun læseadgang",
          severity: "info",
        });
        return;
      }
      if (selectedClients.length < 1) {
        setSnackbar({
          open: true,
          message: "Vælg mindst én klient",
          severity: "error",
        });
        return;
      }
      if (!activeClient) {
        setSnackbar({
          open: true,
          message: "Ingen aktiv klient valgt",
          severity: "error",
        });
        return;
      }
      setSavingCalendar(true);
      const allDates = [];
      seasonYearMonths.forEach(({ month, year }) => {
        for (let d = 1; d <= getDaysInMonth(month, year); d++)
          allDates.push(formatDate(year, month, d));
      });
      const payloadMarkedDays = {};
      selectedClients.forEach((cid) => {
        const clientKey = String(cid);
        payloadMarkedDays[clientKey] = {};
        allDates.forEach((dateStr) => {
          const sourceMd = markedDays[activeClient]?.[dateStr];
          const sourceDefTimes = getDefaultTimes(dateStr, activeClient);
          payloadMarkedDays[clientKey][dateStr] =
            sourceMd && sourceMd.status === "on"
              ? {
                  status: "on",
                  onTime: sourceMd.onTime || sourceDefTimes.onTime,
                  offTime: sourceMd.offTime || sourceDefTimes.offTime,
                }
              : { status: "off" };
        });
      });
      try {
        await saveMarkedDays({
          clients: selectedClients,
          markedDays: payloadMarkedDays,
          season: selectedSeason,
        });
        if (showSuccessFeedback)
          setSnackbar({ open: true, message: "Gemt!", severity: "success" });
        if (activeClient) {
          try {
            const data = await getMarkedDays(selectedSeason, activeClient);
            dispatchMarkedDays({
              type: "set",
              clientId: activeClient,
              days: mapRawDays(data.markedDays || {}),
            });
          } catch {
            dispatchMarkedDays({
              type: "set",
              clientId: activeClient,
              days: {},
            });
          }
        }
      } catch (e) {
        setSnackbar({
          open: true,
          message: e?.message || "Kunne ikke gemme kalender.",
          severity: "error",
        });
      } finally {
        setSavingCalendar(false);
      }
    },
    [
      isReadOnly,
      selectedClients,
      activeClient,
      markedDays,
      seasonYearMonths,
      selectedSeason,
      getDefaultTimes,
    ],
  );

  const clearSnackbarTimer = useCallback(() => {
    if (snackbarTimer.current) {
      window.clearTimeout(snackbarTimer.current);
      snackbarTimer.current = null;
    }
  }, []);

  useEffect(() => clearSnackbarTimer, [clearSnackbarTimer]);

  const clientMarkedDays = activeClientMarkedDays;
  const loadingMarkedDays = activeClient && clientMarkedDays === undefined;
  const handleCloseSnackbar = () =>
    setSnackbar({ open: false, message: "", severity: "success" });
  const isDisabled = !activeClient;
  const isEditDisabled = isDisabled || isReadOnly;
  const sortedOrganizations = useMemo(
    () => [...organizations].sort((a, b) => a.name.localeCompare(b.name)),
    [organizations],
  );
  const editDialogClientObj = clients.find((c) => c.id === editDialogClient);
  const editDialogOrganizationTimes =
    allOrganizationTimes[getOrganizationId(editDialogClientObj)] || null;

  // Sæson-selector til ikke-superadmin (bruges nedenfor)
  const seasonSelectorNonAdmin = (
    <Box
      sx={{
        flex: 1,
        display: "flex",
        justifyContent: { xs: "center", sm: "flex-end" },
        alignItems: "center",
        gap: 1,
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center" }}>
        {selectedSeason !== currentSeason && (
          <Tooltip title="Ikke indeværende sæson" arrow>
            <WarningAmberIcon
              color="warning"
              sx={{
                mr: 0.5,
                transition: "opacity 0.7s",
                opacity: fadeIn ? 1 : 0.2,
              }}
            />
          </Tooltip>
        )}
      </Box>
      <Typography
        variant="h6"
        sx={{
          fontWeight: 700,
          color: "#f8fafc",
          mr: 2,
          fontSize: { xs: "1rem", sm: "1.15rem" },
        }}
      >
        Vælg sæson:
      </Typography>
      <Select
        size="small"
        value={selectedSeason}
        onChange={(e) => setSelectedSeason(e.target.value)}
        sx={{ minWidth: 160 }}
        renderValue={(val) => (
          <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
            <span>{val}</span>
            {val === currentSeason && (
              <Chip
                label="Nuværende"
                size="small"
                sx={compactDarkChipSx("primary", {
                  height: 18,
                  fontSize: "0.7rem",
                })}
              />
            )}
          </Box>
        )}
      >
        {availableSeasons.length > 0 ? (
          availableSeasons.map((s) => (
            <MenuItem key={s} value={s}>
              <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                <span>{s}</span>
                {s === currentSeason && (
                  <Chip
                    label="Nuværende sæson"
                    size="small"
                    sx={compactDarkChipSx("primary", {
                      height: 20,
                      fontSize: "0.72rem",
                    })}
                  />
                )}
              </Box>
            </MenuItem>
          ))
        ) : (
          <MenuItem value={selectedSeason}>{selectedSeason}</MenuItem>
        )}
      </Select>
    </Box>
  );

  return (
    <Box
      sx={{
        ...pageShellSx,
        fontFamily: "inherit",
        color: "#f8fafc",
      }}
    >
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
              <CalendarMonthIcon />
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
                Kalender
              </Typography>
              <Typography sx={{ color: "rgba(203,213,225,0.68)", mt: 0.35 }}>
                Planlæg driftstid for skærme på tværs af organisationer og
                sæsoner.
              </Typography>
            </Box>
          </Stack>

          <Tooltip title="Opdater klienter">
            <span>
              <Button
                startIcon={
                  loadingClients ? (
                    <CircularProgress size={20} color="inherit" />
                  ) : (
                    <RefreshIcon />
                  )
                }
                onClick={() => fetchClients(true)}
                disabled={loadingClients}
                variant="contained"
                sx={{
                  minHeight: 42,
                  borderRadius: 2,
                  fontWeight: 900,
                  width: { xs: "100%", md: "auto" },
                }}
              >
                {loadingClients ? "Opdaterer..." : "Opdater"}
              </Button>
            </span>
          </Tooltip>
        </Stack>
      </Paper>
      <AppSnackbar
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={handleCloseSnackbar}
      />
      {/* Superadmin: sæson + organisation i samme Paper */}
      {(isSuperadmin || isAdmin) && (
        <Paper
          elevation={0}
          sx={{
            p: { xs: 1.5, sm: 2 },
            mb: 2.2,
            borderRadius: 2,
            bgcolor: "rgba(15,23,42,0.74)",
            border: "1px solid rgba(148,163,184,0.16)",
            boxShadow: "0 24px 80px rgba(0,0,0,0.22)",
          }}
        >
          {loadingSeasonSummary || seasonClockLoading ? (
            <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
              <CircularProgress size={20} />
              <Typography variant="body2">Henter sæson-data...</Typography>
            </Box>
          ) : (
            <Stack
              direction={{ xs: "column", sm: "row" }}
              sx={{
                alignItems: "center",
                gap: 3,
                flexWrap: "wrap"
              }}>
              {/* Vælg sæson */}
              <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                {selectedSeason !== currentSeason && (
                  <Tooltip title="Ikke indeværende sæson" arrow>
                    <WarningAmberIcon
                      color="warning"
                      sx={{
                        transition: "opacity 0.7s",
                        opacity: fadeIn ? 1 : 0.2,
                      }}
                    />
                  </Tooltip>
                )}
                <Typography
                  variant="h6"
                  sx={{
                    fontWeight: 700,
                    fontSize: { xs: "1rem", sm: "1.15rem" },
                    whiteSpace: "nowrap",
                  }}
                >
                  Vælg sæson:
                </Typography>
                <Select
                  size="small"
                  value={selectedSeason}
                  onChange={(e) => setSelectedSeason(e.target.value)}
                  sx={{ minWidth: 160 }}
                  renderValue={(val) => (
                    <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                      <span>{val}</span>
                      {val === currentSeason && (
                        <Chip
                          label="Nuværende"
                          size="small"
                          sx={compactDarkChipSx("primary", {
                            height: 18,
                            fontSize: "0.7rem",
                          })}
                        />
                      )}
                    </Box>
                  )}
                >
                  {availableSeasons.map((s) => (
                    <MenuItem key={s} value={s}>
                      <Box
                        sx={{ display: "flex", alignItems: "center", gap: 1 }}
                      >
                        <span>{s}</span>
                        {s === currentSeason && (
                          <Chip
                            label="Nuværende sæson"
                            size="small"
                            sx={compactDarkChipSx("primary", {
                              height: 20,
                              fontSize: "0.72rem",
                            })}
                          />
                        )}
                      </Box>
                    </MenuItem>
                  ))}
                </Select>
              </Box>

              {/* Vælg organisation */}
              <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
                <Typography
                  variant="h6"
                  sx={{
                    fontWeight: 700,
                    fontSize: { xs: "1rem", sm: "1.15rem" },
                    whiteSpace: "nowrap",
                  }}
                >
                  Vælg organisation:
                </Typography>
                <Select
                  size="small"
                  value={selectedOrganization}
                  displayEmpty
                  onChange={(e) => {
                    if (isAdmin) return;
                    setSelectedOrganization(e.target.value);
                    setSelectedClients([]);
                    setActiveClient(null);
                  }}
                  sx={{ minWidth: 160 }}
                  disabled={
                    isAdmin || availableOrganizationsForSeason.length === 0
                  }
                >
                  {isSuperadmin && (
                    <MenuItem value="">Alle organisationer</MenuItem>
                  )}
                  {availableOrganizationsForSeason.map((organization) => (
                    <MenuItem key={organization.id} value={organization.id}>
                      {organization.name}
                    </MenuItem>
                  ))}
                </Select>
              </Box>
            </Stack>
          )}
        </Paper>
      )}
      {(isSuperadmin || isAdmin) && selectedOrganization && (
        <Box sx={{ mb: 2.2 }}>
          <SeasonPreparationAlert organizationId={selectedOrganization} />
        </Box>
      )}
      <Paper
        elevation={0}
        sx={{
          p: { xs: 1.5, sm: 2 },
          mb: 2.2,
          position: "relative",
          borderRadius: 2,
          bgcolor: "rgba(15,23,42,0.74)",
          border: "1px solid rgba(148,163,184,0.16)",
          boxShadow: "0 24px 80px rgba(0,0,0,0.22)",
        }}
      >
        {loadingClients && (
          <Box
            sx={{
              position: "absolute",
              left: 0,
              top: 0,
              right: 0,
              bottom: 0,
              background: "rgba(2,6,23,0.68)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              zIndex: 10,
            }}
          >
            <CircularProgress />
          </Box>
        )}
        <ClientSelectorInline
          clients={filteredClients}
          selected={selectedClients}
          onChange={handleClientSelectorChange}
          organizations={organizations}
          disabled={false}
          selectedOrganization={selectedOrganization}
        />
        {selectedClients.length >= 1 && (
          <Box
            sx={{
              mt: 2,
              display: "flex",
              flexDirection: { xs: "column", sm: "row" },
              alignItems: { xs: "stretch", sm: "center" },
              justifyContent: "space-between",
              gap: { xs: 1.5, sm: 0 },
            }}
          >
            <Box>
              <Typography
                variant="body2"
                sx={{ fontSize: { xs: "1rem", sm: "1.1rem" }, fontWeight: 700 }}
              >
                Viser kalender for: {activeClientName}
              </Typography>
              {selectedClients.length > 1 && (
                <Typography
                  variant="body2"
                  sx={{
                    fontSize: { xs: "0.9rem", sm: "0.8rem" },
                    color: "rgba(203,213,225,0.62)",
                  }}
                >
                  ændringerne slår også igennem på klienterne:{" "}
                  {otherClientNames}
                </Typography>
              )}
            </Box>
            <Button
              variant="contained"
              color="primary"
              onClick={() => handleSave(true)}
              disabled={
                savingCalendar || selectedClients.length < 1 || isReadOnly
              }
              startIcon={
                savingCalendar ? (
                  <CircularProgress color="inherit" size={20} />
                ) : null
              }
              sx={{
                minWidth: { xs: "100%", sm: 180 },
                width: { xs: "100%", sm: 220 },
                mt: { xs: 1, sm: 0 },
              }}
            >
              {savingCalendar
                ? "Gemmer..."
                : "Gem kalender for valgte klienter"}
            </Button>
          </Box>
        )}
      </Paper>
      <Box
        sx={{
          display: "flex",
          alignItems: { xs: "stretch", sm: "center" },
          mb: 3,
          flexDirection: { xs: "column", sm: "row" },
          gap: { xs: 1.5, sm: 0 },
          width: "100%",
        }}
      >
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 2,
            flex: 1,
            justifyContent: { xs: "center", sm: "flex-start" },
          }}
        >
          <Typography
            variant="h6"
            sx={{
              mr: 1,
              fontWeight: 700,
              fontSize: { xs: "1rem", sm: "1.15rem" },
            }}
          >
            Markering:
          </Typography>
          <Button
            variant={markMode === "on" ? "contained" : "outlined"}
            color="success"
            size="medium"
            disabled={isEditDisabled}
            sx={{ fontWeight: markMode === "on" ? 700 : 400, minWidth: 90 }}
            onClick={() => setMarkMode("on")}
          >
            TÆNDT
          </Button>
          <Button
            variant={markMode === "off" ? "contained" : "outlined"}
            color="error"
            size="medium"
            disabled={isEditDisabled}
            sx={{ fontWeight: markMode === "off" ? 700 : 400, minWidth: 90 }}
            onClick={() => setMarkMode("off")}
          >
            SLUKKET
          </Button>
        </Box>
        <Box
          sx={{
            flex: 1,
            display: "flex",
            justifyContent: { xs: "center", sm: "center" },
            mb: { xs: 1, sm: 0 },
          }}
        >
          <Button
            variant="outlined"
            color="primary"
            size="medium"
            sx={{
              minWidth: 120,
              fontWeight: 700,
              width: { xs: "100%", sm: 120 },
            }}
            onClick={() => setCalendarDialogOpen(true)}
            disabled={isDisabled}
          >
            Vis liste
          </Button>
        </Box>
        {/* Sæson-selector kun for roller uden organisationsvælger */}
        {!isSuperadmin && !isAdmin && seasonSelectorNonAdmin}
      </Box>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            sm: "1fr 1fr",
            md: "repeat(4, 1fr)",
          },
          columnGap: { xs: 1, sm: 1.2, md: 1.4 },
          rowGap: { xs: 1, sm: 1.2, md: 1.4 },
        }}
      >
        {!activeClient && (
          <Typography sx={{ mt: 4, textAlign: "center", gridColumn: "1/-1" }}>
            Vælg en klient for at se kalenderen.
          </Typography>
        )}
        {activeClient &&
          !loadingMarkedDays &&
          seasonYearMonths.map(({ name, month, year }) => (
            <MemoizedMonthCalendar
              key={name + year}
              name={name}
              month={month}
              year={year}
              clientId={activeClient}
              markedDays={markedDays}
              markMode={markMode}
              onDayClick={handleDayClick}
              onDateShiftLeftClick={handleDateShiftLeftClick}
              loadingDialogDate={loadingDialogDate}
              loadingDialogClient={loadingDialogClient}
              todayStr={todayInfo.todayStr}
              currentMonth={todayInfo.currentMonth}
              currentYear={todayInfo.currentYear}
              readOnly={isReadOnly}
            />
          ))}
        {activeClient && loadingMarkedDays && (
          <Box sx={{ textAlign: "center", mt: 6, gridColumn: "1/-1" }}>
            <CircularProgress />
            <Typography variant="body2" sx={{ mt: 2 }}>
              Henter kalender...
            </Typography>
          </Box>
        )}
      </Box>
      <DateTimeEditDialog
        open={editDialogOpen}
        onClose={() => setEditDialogOpen(false)}
        date={editDialogDate}
        clientId={editDialogClient}
        onSaved={handleSaveDateTime}
        localMarkedDays={markedDays[editDialogClient]}
        schoolId={getOrganizationId(editDialogClientObj)}
        schoolTimes={editDialogOrganizationTimes}
        season={selectedSeason}
      />
      <ClientCalendarDialog
        open={calendarDialogOpen}
        onClose={() => setCalendarDialogOpen(false)}
        clientId={activeClient}
        season={selectedSeason}
      />
    </Box>
  );
}

const MonthCalendar = React.memo(function MonthCalendar({
  name,
  month,
  year,
  clientId,
  markedDays,
  markMode,
  onDayClick,
  onDateShiftLeftClick,
  loadingDialogDate,
  loadingDialogClient,
  todayStr,
  currentMonth,
  currentYear,
  readOnly = false,
}) {
  const [isDragging, setIsDragging] = useState(false);
  const draggedDates = useRef(new Set());
  const daysInMonth = getDaysInMonth(month, year);
  const firstDayOfWeek = new Date(year, month, 1).getDay();
  const offset = firstDayOfWeek === 0 ? 6 : firstDayOfWeek - 1;
  const cells = useMemo(() => {
    const monthCells = [
      ...Array(offset).fill(null),
      ...Array.from({ length: daysInMonth }, (_, d) => d + 1),
    ];
    while (monthCells.length % 7 !== 0) monthCells.push(null);
    return monthCells;
  }, [daysInMonth, offset]);

  const isCurrentMonth = month === currentMonth && year === currentYear;

  const weekRows = useMemo(() => {
    const rows = [];
    let weekStartIdx = 0;
    while (weekStartIdx < cells.length) {
      const weekDays = cells.slice(weekStartIdx, weekStartIdx + 7);
      const firstDay = weekDays.find((d) => !!d);
      const dateObj = firstDay
        ? new Date(year, month, firstDay)
        : new Date(year, month, 1 + weekStartIdx - offset);
      rows.push({ weekNum: getWeekNumber(dateObj), weekDays });
      weekStartIdx += 7;
    }
    return rows;
  }, [cells, year, month, offset]);

  const circleSize = 36;
  const innerCircleSize = 32;

  useEffect(() => {
    if (!isDragging) return;
    const handleUp = () => setIsDragging(false);
    window.addEventListener("mouseup", handleUp);
    return () => window.removeEventListener("mouseup", handleUp);
  }, [isDragging]);

  const handleMouseDown = (e, dateString) => {
    if (readOnly) return;
    if (e.shiftKey && e.button === 0) {
      e.preventDefault();
      if (
        clientId &&
        markedDays?.[clientId]?.[dateString]?.status === "on" &&
        !loadingDialogDate
      ) {
        onDateShiftLeftClick(clientId, dateString);
        return;
      }
    }
    setIsDragging(true);
    draggedDates.current = new Set([dateString]);
    if (clientId) onDayClick([clientId], dateString, markMode, markedDays);
  };

  const handleMouseEnter = (e, dateString) => {
    if (readOnly) return;
    if (isDragging && clientId && !draggedDates.current.has(dateString)) {
      draggedDates.current.add(dateString);
      onDayClick([clientId], dateString, markMode, markedDays);
    }
  };

  return (
    <Card
      sx={{
        borderRadius: 2,
        boxShadow: isCurrentMonth
          ? "0 0 0 1px rgba(56,189,248,0.35), 0 24px 80px rgba(0,0,0,0.24)"
          : "0 18px 60px rgba(0,0,0,0.18)",
        minWidth: 0,
        background: isCurrentMonth
          ? "linear-gradient(135deg, rgba(56,189,248,0.16), rgba(15,23,42,0.78))"
          : "rgba(15,23,42,0.72)",
        border: "1px solid rgba(148,163,184,0.16)",
        p: { xs: 0.75, sm: 1 },
        userSelect: "none",
      }}
    >
      <CardContent sx={{ p: { xs: 1, sm: 2 } }}>
        <Typography
          variant="h6"
          sx={{
            color: isCurrentMonth ? "#bae6fd" : "#f8fafc",
            fontWeight: 700,
            textAlign: "center",
            fontSize: { xs: "1rem", sm: "1.08rem" },
            mb: 1,
          }}
        >
          {name} {year}
          {isCurrentMonth && (
            <Chip
              label="Denne måned"
              size="small"
              sx={compactDarkChipSx("primary", {
                ml: 1,
                height: 18,
                fontSize: "0.68rem",
                verticalAlign: "middle",
              })}
            />
          )}
        </Typography>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: "repeat(8, 1fr)",
            columnGap: "0.08rem",
            rowGap: "0.5rem",
            mb: 0.5,
          }}
        >
          <Box />
          {weekdayNames.map((wd) => (
            <Typography
              key={wd}
              variant="caption"
              sx={{
                fontWeight: 700,
                color: "rgba(203,213,225,0.62)",
                textAlign: "center",
                fontSize: { xs: "0.82rem", sm: "0.90rem" },
                letterSpacing: "0.03em",
              }}
            >
              {wd}
            </Typography>
          ))}
        </Box>
        <Box
          sx={{
            display: "grid",
            gridTemplateRows: `repeat(${weekRows.length}, 1fr)`,
            rowGap: "0.5rem",
          }}
        >
          {weekRows.map((row, rowIdx) => (
            <Box
              key={rowIdx}
              sx={{
                display: "grid",
                gridTemplateColumns: "repeat(8, 1fr)",
                columnGap: "0.08rem",
              }}
            >
              <Box
                sx={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontWeight: 700,
                  fontSize: { xs: "0.65rem", sm: "0.75rem" },
                  color: "rgba(203,213,225,0.46)",
                }}
              >
                {row.weekNum}
              </Box>
              {row.weekDays.map((day, idx) => {
                if (!day) return <Box key={idx + "-empty"} />;
                const dateString = formatDate(year, month, day);
                const isToday = dateString === todayStr;
                const cellStatus =
                  markedDays?.[clientId]?.[dateString]?.status || "off";
                let bg = "rgba(148,163,184,0.13)";
                if (cellStatus === "on") bg = "rgba(34,197,94,0.74)";
                if (cellStatus === "off") bg = "rgba(239,68,68,0.60)";
                const isLoading =
                  loadingDialogDate === dateString &&
                  loadingDialogClient === clientId;
                return (
                  <Box
                    key={idx}
                    sx={{
                      display: "flex",
                      justifyContent: "center",
                      alignItems: "center",
                      p: 0.2,
                      position: "relative",
                    }}
                  >
                    <Box
                      sx={{
                        position: "relative",
                        width: circleSize,
                        height: circleSize,
                        cursor: clientId ? "pointer" : "default",
                        opacity: clientId ? 1 : 0.55,
                        userSelect: "none",
                        borderRadius: "50%",
                        boxShadow: isToday
                          ? "0 0 0 2.5px rgba(56,189,248,0.95), 0 0 0 7px rgba(56,189,248,0.10)"
                          : "none",
                      }}
                      onMouseDown={(e) => handleMouseDown(e, dateString)}
                      onMouseEnter={(e) => handleMouseEnter(e, dateString)}
                      title={
                        isToday
                          ? "I dag"
                          : cellStatus === "on"
                            ? "Tændt (shift+klik for tid)"
                            : "Slukket"
                      }
                    >
                      {isLoading && (
                        <CircularProgress
                          size={circleSize}
                          sx={{
                            position: "absolute",
                            top: 0,
                            left: 0,
                            zIndex: 1,
                            color: "#1976d2",
                          }}
                        />
                      )}
                      <Box
                        sx={{
                          position: "absolute",
                          top: 2,
                          left: 2,
                          width: innerCircleSize,
                          height: innerCircleSize,
                          borderRadius: "50%",
                          background: bg,
                          border: "1px solid rgba(255,255,255,0.14)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: "#f8fafc",
                          fontWeight: isToday ? 800 : 500,
                          fontSize: "1.15rem",
                          zIndex: 2,
                          boxShadow: "0 8px 22px rgba(0,0,0,0.24)",
                          userSelect: "none",
                        }}
                      >
                        {day}
                      </Box>
                    </Box>
                  </Box>
                );
              })}
            </Box>
          ))}
        </Box>
      </CardContent>
    </Card>
  );
});

const MemoizedMonthCalendar = MonthCalendar;
