import React, { useState, useEffect, useMemo } from "react";
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
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import CalendarMonthIcon from "@mui/icons-material/CalendarMonth";
import { LocalizationProvider, DatePicker } from "@mui/x-date-pickers";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import { da as daLocale } from "date-fns/locale/da";
import { getMarkedDays, getCurrentSeason } from "../../api";
import { compactDarkChipSx } from "../../utils/chipStyles";

function pad2(value) {
  return String(value).padStart(2, "0");
}

function formatDateKey(dt) {
  if (!(dt instanceof Date) || Number.isNaN(dt.getTime())) return "";
  return `${dt.getFullYear()}-${pad2(dt.getMonth() + 1)}-${pad2(dt.getDate())}`;
}

function formatDateLong(dt) {
  if (!(dt instanceof Date) || Number.isNaN(dt.getTime())) return "Ukendt dato";
  const weekdays = ["Søndag", "Mandag", "Tirsdag", "Onsdag", "Torsdag", "Fredag", "Lørdag"];
  return `${weekdays[dt.getDay()]} ${pad2(dt.getDate())}.${pad2(dt.getMonth() + 1)} ${dt.getFullYear()}`;
}

function normalizeDateOnly(value) {
  if (!value) return null;
  if (value instanceof Date) {
    if (Number.isNaN(value.getTime())) return null;
    const d = new Date(value);
    d.setHours(12, 0, 0, 0);
    return d;
  }

  const str = String(value).trim();
  if (!str) return null;

  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) {
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), 12, 0, 0, 0);
  }

  const d = new Date(str);
  if (Number.isNaN(d.getTime())) return null;
  d.setHours(12, 0, 0, 0);
  return d;
}

function getSeasonValue(season) {
  return season?.id ?? season?.season ?? season;
}

function getSeasonMetaFromValue(seasonValue) {
  const value = getSeasonValue(seasonValue);
  if (!value || typeof value !== "string" || !value.includes("/")) return null;
  const startYear = Number(value.split("/")[0]);
  if (!Number.isFinite(startYear)) return null;
  return {
    id: value,
    label: value,
    start_date: `${startYear}-08-01`,
    end_date: `${startYear + 1}-07-31`,
  };
}

function getStatusAndTimesFromRaw(markedDays = {}, dt) {
  const dateKeyShort = formatDateKey(dt);
  if (!dateKeyShort || !markedDays || typeof markedDays !== "object") {
    return { status: "off", powerOn: "", powerOff: "" };
  }

  const dateKeyFull = `${dateKeyShort}T00:00:00`;
  const data = markedDays[dateKeyFull]
    || markedDays[dateKeyShort]
    || Object.entries(markedDays).find(([k]) => String(k).startsWith(dateKeyShort))?.[1];

  const status = String(data?.status || "").toLowerCase();
  if (!data || !status || status === "off") {
    return { status: "off", powerOn: "", powerOff: "" };
  }

  return {
    status: "on",
    powerOn: data.onTime || data.powerOn || data.power_on || "",
    powerOff: data.offTime || data.powerOff || data.power_off || "",
  };
}

function getDaysInRange(start, end) {
  const startD = normalizeDateOnly(start);
  const endD = normalizeDateOnly(end);
  if (!startD || !endD || startD > endD) return [];

  const days = [];
  const d = new Date(startD);

  while (d <= endD) {
    days.push(new Date(d));
    d.setDate(d.getDate() + 1);
  }

  return days;
}

function addMonths(date, num) {
  const d = normalizeDateOnly(date) || new Date();
  d.setMonth(d.getMonth() + num);
  return d;
}

function clampDate(date, minDate, maxDate) {
  const d = normalizeDateOnly(date);
  if (!d) return null;
  const min = normalizeDateOnly(minDate);
  const max = normalizeDateOnly(maxDate);

  if (min && d < min) return min;
  if (max && d > max) return max;
  return d;
}

function StatusPill({ status }) {
  const isOn = status === "on";
  return (
    <Chip
      size="small"
      label={isOn ? "Tændt" : "Slukket"}
      sx={compactDarkChipSx(isOn ? "success" : "error")}
    />
  );
}

function ClientPowerPeriodTable({ markedDays, days }) {
  const onCount = days.filter((dt) => getStatusAndTimesFromRaw(markedDays, dt).status === "on").length;

  return (
    <Stack spacing={1.5} sx={{ mt: 2.5 }}>
      <Stack direction="row" spacing={1} useFlexGap sx={{
        flexWrap: "wrap"
      }}>
        <Chip size="small" label={`${days.length} dage`} sx={compactDarkChipSx("neutral")} />
        <Chip size="small" label={`${onCount} tændte`} sx={compactDarkChipSx("success")} />
      </Stack>
      <TableContainer sx={{ maxHeight: 380, overflowY: "auto", borderRadius: 2, border: "1px solid rgba(148,163,184,0.14)" }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 900, bgcolor: "rgba(15,23,42,0.98)", color: "#f8fafc" }}>Dato</TableCell>
              <TableCell sx={{ fontWeight: 900, bgcolor: "rgba(15,23,42,0.98)", color: "#f8fafc" }}>Status</TableCell>
              <TableCell sx={{ fontWeight: 900, bgcolor: "rgba(15,23,42,0.98)", color: "#f8fafc" }}>Tænd</TableCell>
              <TableCell sx={{ fontWeight: 900, bgcolor: "rgba(15,23,42,0.98)", color: "#f8fafc" }}>Sluk</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {days.map((dt) => {
              const { status, powerOn, powerOff } = getStatusAndTimesFromRaw(markedDays, dt);
              const key = formatDateKey(dt);
              return (
                <TableRow key={key} hover>
                  <TableCell sx={{ color: "rgba(226,232,240,0.92)", borderColor: "rgba(148,163,184,0.12)" }}>{formatDateLong(dt)}</TableCell>
                  <TableCell sx={{ borderColor: "rgba(148,163,184,0.12)" }}><StatusPill status={status} /></TableCell>
                  <TableCell sx={{ color: "rgba(226,232,240,0.92)", borderColor: "rgba(148,163,184,0.12)" }}>{status === "on" ? powerOn : ""}</TableCell>
                  <TableCell sx={{ color: "rgba(226,232,240,0.92)", borderColor: "rgba(148,163,184,0.12)" }}>{status === "on" ? powerOff : ""}</TableCell>
                </TableRow>
              );
            })}

            {days.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} sx={{ color: "rgba(203,213,225,0.68)" }}>
                  Ingen datoer i den valgte periode.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>
    </Stack>
  );
}

export default function ClientCalendarDialog({ open, onClose, clientId, season }) {
  const [seasonMeta, setSeasonMeta] = useState(null);
  const [startDate, setStartDate] = useState(() => normalizeDateOnly(new Date()));
  const [endDate, setEndDate] = useState(() => addMonths(new Date(), 1));
  const [markedDays, setMarkedDays] = useState({});
  const [loading, setLoading] = useState(false);
  const [loadingSeason, setLoadingSeason] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return undefined;

    let cancelled = false;

    async function loadSeason() {
      setLoadingSeason(true);
      setError("");

      try {
        const incomingSeason = getSeasonMetaFromValue(season);
        const s = incomingSeason || (await getCurrentSeason());
        if (cancelled) return;

        setSeasonMeta(s);

        const today = normalizeDateOnly(new Date());
        const seasonStart = normalizeDateOnly(s?.start_date);
        const seasonEnd = normalizeDateOnly(s?.end_date);

        const start = clampDate(today, seasonStart, seasonEnd) || seasonStart || today;
        const end = clampDate(addMonths(start, 1), seasonStart, seasonEnd) || addMonths(start, 1);

        setStartDate(start);
        setEndDate(end);
        setMarkedDays({});
        setShowTable(false);
      } catch (err) {
        if (cancelled) return;

        setSeasonMeta(getSeasonMetaFromValue(season));
        setStartDate(normalizeDateOnly(new Date()));
        setEndDate(addMonths(new Date(), 1));
        setMarkedDays({});
        setShowTable(false);
        setError(err?.message || "Kunne ikke hente aktuel sæson.");
      } finally {
        if (!cancelled) setLoadingSeason(false);
      }
    }

    loadSeason();

    return () => {
      cancelled = true;
    };
  }, [open, season]);

  const seasonStartDate = useMemo(
    () => normalizeDateOnly(seasonMeta?.start_date) || undefined,
    [seasonMeta?.start_date]
  );

  const seasonEndDate = useMemo(
    () => normalizeDateOnly(seasonMeta?.end_date) || undefined,
    [seasonMeta?.end_date]
  );

  const selectedDays = useMemo(
    () => getDaysInRange(startDate, endDate),
    [startDate, endDate]
  );

  const dateRangeInvalid = !startDate || !endDate || startDate > endDate;
  const seasonValue = getSeasonValue(seasonMeta) || getSeasonValue(season);

  const handleFetch = async () => {
    if (!startDate || !endDate || !clientId || !seasonValue || dateRangeInvalid) return;

    setLoading(true);
    setError("");

    try {
      const startStr = formatDateKey(startDate);
      const endStr = formatDateKey(endDate);
      const res = await getMarkedDays(seasonValue, clientId, startStr, endStr);
      setMarkedDays(res?.markedDays || res?.marked_days || {});
      setShowTable(true);
    } catch (err) {
      setMarkedDays({});
      setShowTable(true);
      setError(err?.message || "Kunne ikke hente kalender for perioden.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="md"
      fullWidth
      slotProps={{
        paper: {
          sx: {
            borderRadius: 2,
            background: "rgba(15,23,42,0.97)",
            color: "#f8fafc",
            border: "1px solid rgba(148,163,184,0.18)",
            boxShadow: "0 28px 110px rgba(0,0,0,0.48)",
          },
        }
      }}
    >
      <DialogTitle sx={{ pb: 1.2 }}>
        <Stack direction="row" spacing={1.2} sx={{
          alignItems: "center"
        }}>
          <Box
            sx={{
              width: 40,
              height: 40,
              borderRadius: 2,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#020617",
              background: "linear-gradient(135deg, #38bdf8, #14b8a6)",
            }}
          >
            <CalendarMonthIcon />
          </Box>
          <Box>
            <Typography sx={{ fontWeight: 950, lineHeight: 1.15 }}>Vis kalender for periode</Typography>
            <Typography variant="body2" sx={{ color: "rgba(203,213,225,0.68)", mt: 0.25 }}>
              {seasonValue ? `Sæson ${seasonValue}` : "Vælg periode"}
            </Typography>
          </Box>
        </Stack>
      </DialogTitle>
      <DialogContent sx={{ pt: 1.5 }}>
        <Stack spacing={2.2}>
          {error && <Alert severity="warning">{error}</Alert>}

          <LocalizationProvider dateAdapter={AdapterDateFns} adapterLocale={daLocale}>
            <Stack
              direction={{ xs: "column", md: "row" }}
              spacing={1.4}
              sx={{
                alignItems: { xs: "stretch", md: "flex-start" }
              }}
            >
              <DatePicker
                label="Startdato"
                value={startDate}
                onChange={(value) => {
                  const next = normalizeDateOnly(value);
                  setStartDate(next);
                  setShowTable(false);
                  if (next && endDate && next > endDate) setEndDate(next);
                }}
                minDate={seasonStartDate}
                maxDate={seasonEndDate}
                format="dd/MM/yyyy"
                slotProps={{
                  textField: {
                    variant: "outlined",
                    fullWidth: true,
                    size: "medium",
                    error: !startDate,
                    helperText: !startDate ? "Vælg startdato" : " ",
                  },
                }}
              />

              <DatePicker
                label="Slutdato"
                value={endDate}
                onChange={(value) => {
                  setEndDate(normalizeDateOnly(value));
                  setShowTable(false);
                }}
                minDate={startDate || seasonStartDate}
                maxDate={seasonEndDate}
                format="dd/MM/yyyy"
                slotProps={{
                  textField: {
                    variant: "outlined",
                    fullWidth: true,
                    size: "medium",
                    error: !endDate || dateRangeInvalid,
                    helperText: !endDate
                      ? "Vælg slutdato"
                      : dateRangeInvalid
                        ? "Slutdato skal være efter startdato"
                        : " ",
                  },
                }}
              />

              <Button
                variant="contained"
                size="large"
                sx={{ minWidth: 150, minHeight: 56, borderRadius: 2, fontWeight: 950 }}
                onClick={handleFetch}
                disabled={loading || loadingSeason || !startDate || !endDate || !seasonValue || dateRangeInvalid}
                loading={loading}
              >
                Vis periode
              </Button>
            </Stack>
          </LocalizationProvider>

          {loadingSeason && (
            <Box sx={{ textAlign: "center", py: 2 }}>
              <CircularProgress size={24} />
              <Typography sx={{ mt: 1, color: "rgba(203,213,225,0.74)" }}>Henter sæson...</Typography>
            </Box>
          )}

          {loading && (
            <Box sx={{ textAlign: "center", py: 2 }}>
              <CircularProgress size={28} />
              <Typography sx={{ mt: 1, color: "rgba(203,213,225,0.74)" }}>Indlæser kalender...</Typography>
            </Box>
          )}

          {showTable && !loading && (
            <ClientPowerPeriodTable markedDays={markedDays} days={selectedDays} />
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5, pt: 1 }}>
        <Button onClick={onClose} color="inherit" sx={{ borderRadius: 2, fontWeight: 850 }}>Luk</Button>
      </DialogActions>
    </Dialog>
  );
}
