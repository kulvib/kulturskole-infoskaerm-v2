import AppSnackbar from "../../components/AppSnackbar";
import React, { useEffect, useState, useRef, useCallback } from "react";
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import AccessTimeIcon from "@mui/icons-material/AccessTime";
import WbSunnyIcon from "@mui/icons-material/WbSunny";
import NightsStayIcon from "@mui/icons-material/NightsStay";
import { client } from "../../api";
import { compactDarkChipSx } from "../../utils/chipStyles";

const WEEKDAYS = ["søndag", "mandag", "tirsdag", "onsdag", "torsdag", "fredag", "lørdag"];
const MONTHS = [
  "januar", "februar", "marts", "april", "maj", "juni",
  "juli", "august", "september", "oktober", "november", "december"
];

const EARLIEST = "00:00";
const LATEST = "23:59";

function normalizeDateString(dateStr) {
  if (!dateStr) return "";
  return String(dateStr).split("T")[0];
}

function formatFullDate(dateStr) {
  const norm = normalizeDateString(dateStr);
  if (!norm) return "";

  const [yyyy, mm, dd] = norm.split("-");
  if (!yyyy || !mm || !dd) return "";

  const d = new Date(Number(yyyy), Number(mm) - 1, Number(dd), 12, 0, 0, 0);
  if (Number.isNaN(d.getTime())) return "";

  return `${WEEKDAYS[d.getDay()]} d. ${d.getDate()}. ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

function getSeasonFromDate(dateStr) {
  const normDate = normalizeDateString(dateStr);
  const year = parseInt(normDate.substring(0, 4), 10);
  const month = parseInt(normDate.substring(5, 7), 10);
  if (!Number.isFinite(year) || !Number.isFinite(month)) return "";
  const startYear = month >= 8 ? year : year - 1;
  return `${startYear}/${startYear + 1}`;
}

function getDefaultTimes(dateStr, schoolTimes) {
  const norm = normalizeDateString(dateStr);
  const [yyyy, mm, dd] = norm.split("-");
  const date = new Date(Number(yyyy), Number(mm) - 1, Number(dd), 12, 0, 0, 0);
  const day = Number.isNaN(date.getTime()) ? 1 : date.getDay();
  const dayKeys = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
  const dayKey = dayKeys[day];

  const fallback = (day === 0 || day === 6)
    ? { status: "off", onTime: "09:00", offTime: "20:00" }
    : { status: "on", onTime: "09:00", offTime: "20:00" };

  const dayTimes = schoolTimes?.day_times || schoolTimes;
  const value = dayTimes?.[dayKey];
  const status = String(value?.status || value?.state || "on").toLowerCase();

  if (status === "off" || status === "closed" || value?.enabled === false) {
    // Standarden er slukket denne ugedag. Dialogen kan stadig bruges til
    // manuelt at tænde en konkret dato, derfor returneres fallback-tider.
    return { ...fallback, status: "off" };
  }

  if (value?.onTime && value?.offTime) {
    return { status: "on", onTime: value.onTime, offTime: value.offTime };
  }

  return fallback;
}

function findDayObj(markedDays = {}, normDate) {
  if (!markedDays || typeof markedDays !== "object") return {};
  if (markedDays[normDate]) return markedDays[normDate];

  const key = Object.keys(markedDays).find((k) => String(k).startsWith(normDate));
  return key ? markedDays[key] : {};
}

function isValidTimeFormat(t) {
  return /^\d{2}:\d{2}$/.test(String(t || ""));
}

function isOnBeforeOff(on, off) {
  return isValidTimeFormat(on) && isValidTimeFormat(off) && on <= off;
}

export default function DateTimeEditDialog({
  open,
  onClose,
  date,
  clientId,
  onSaved,
  schoolTimes,
  season,
}) {
  const [onTime, setOnTime] = useState("");
  const [offTime, setOffTime] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [snackbar, setSnackbar] = useState({ open: false, message: "", severity: "success" });

  const closeTimer = useRef(null);
  const abortRef = useRef(null);

  const normDate = normalizeDateString(date);
  const seasonStr = season || getSeasonFromDate(normDate);
  const defaultTimes = getDefaultTimes(normDate, schoolTimes);

  const handleCloseSnackbar = useCallback(() => {
    setSnackbar((prev) => ({ ...prev, open: false }));
  }, []);

  useEffect(() => {
    if (!open || !date || !clientId) return undefined;

    if (abortRef.current) {
      try { abortRef.current.abort(); } catch {}
    }

    const controller = new AbortController();
    abortRef.current = controller;
    let cancelled = false;

    setLoading(true);
    setOnTime("");
    setOffTime("");

    const activeDate = normalizeDateString(date);
    const activeSeason = season || getSeasonFromDate(activeDate);

    async function loadTimes() {
      try {
        const { data } = await client.get("/api/calendar/marked-days", {
          params: { client_id: clientId, season: activeSeason },
          signal: controller.signal,
        });
        if (cancelled) return;

        const dayObj = findDayObj(data.markedDays || data.marked_days || {}, activeDate);

        if (dayObj.onTime && dayObj.offTime) {
          setOnTime(dayObj.onTime);
          setOffTime(dayObj.offTime);
        } else {
          const def = getDefaultTimes(activeDate, schoolTimes);
          setOnTime(def.onTime);
          setOffTime(def.offTime);
        }
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;

        setSnackbar({ open: true, message: "Fejl ved hentning — viser standardtider.", severity: "warning" });
        const def = getDefaultTimes(activeDate, schoolTimes);
        setOnTime(def.onTime);
        setOffTime(def.offTime);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadTimes();

    return () => {
      cancelled = true;
      try { controller.abort(); } catch {}
    };
  }, [open, date, clientId, schoolTimes, season]);

  useEffect(() => {
    return () => {
      if (closeTimer.current) clearTimeout(closeTimer.current);
      if (abortRef.current) {
        try { abortRef.current.abort(); } catch {}
      }
    };
  }, []);

  const validate = () => {
    if (!onTime || !offTime) {
      setSnackbar({ open: true, message: "Begge tider skal udfyldes.", severity: "error" });
      return false;
    }

    if (!isValidTimeFormat(onTime) || !isValidTimeFormat(offTime)) {
      setSnackbar({ open: true, message: "Tid skal være på formatet hh:mm.", severity: "error" });
      return false;
    }

    if (onTime < EARLIEST || onTime > LATEST || offTime < EARLIEST || offTime > LATEST) {
      setSnackbar({ open: true, message: "Tid skal være indenfor datoens interval.", severity: "error" });
      return false;
    }

    if (!isOnBeforeOff(onTime, offTime)) {
      setSnackbar({ open: true, message: "Tænd tid skal være før sluk tid.", severity: "error" });
      return false;
    }

    return true;
  };

  const onTimeMax = offTime && isValidTimeFormat(offTime) ? offTime : LATEST;
  const offTimeMin = onTime && isValidTimeFormat(onTime) ? onTime : EARLIEST;

  const handleSave = async () => {
    if (!validate()) return;

    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }

    setSaving(true);

    try {
      const activeDate = normalizeDateString(date);
      const activeSeason = season || getSeasonFromDate(activeDate);

      let serverData = {};
      try {
        const { data } = await client.get("/api/calendar/marked-days", {
          params: { client_id: clientId, season: activeSeason },
        });
        serverData = data?.markedDays || data?.marked_days || {};
      } catch (err) {
        if (err?.status === 401 || err?.name === "AbortError") throw err;
        // Bevar den eksisterende lokale merge-fallback ved en ikke-auth GET-fejl.
      }

      let updateKey = activeDate;
      const existingKey = Object.keys(serverData).find((k) => String(k).startsWith(activeDate));
      if (existingKey) updateKey = existingKey;

      const updatedDays = { ...serverData };
      updatedDays[updateKey] = { status: "on", onTime, offTime };

      const payload = {
        markedDays: { [String(clientId)]: updatedDays },
        clients: [clientId],
        season: activeSeason,
      };

      try {
        await client.post("/api/calendar/marked-days", payload, {
          headers: { accept: "application/json" },
        });
      } catch (err) {
        if (err?.status === 401 || err?.status === 429) throw err;
        const saveError = new Error("Gemning fejlede");
        saveError.cause = err;
        throw saveError;
      }

      let returnedDay = updatedDays[updateKey];

      try {
        const { data: data2 } = await client.get("/api/calendar/marked-days", {
          params: { client_id: clientId, season: activeSeason },
        });
        const dayObj2 = findDayObj(data2?.markedDays || data2?.marked_days || {}, activeDate);
        if (dayObj2 && (dayObj2.onTime || dayObj2.offTime || dayObj2.status)) {
          returnedDay = dayObj2;
          setOnTime(dayObj2.onTime || "");
          setOffTime(dayObj2.offTime || "");
        }
      } catch {
        // Fallback til lokal merge.
      }

      if (onSaved) onSaved({ date: activeDate, clientId, day: returnedDay });

      setSnackbar({ open: true, message: "Gemt", severity: "success" });
      closeTimer.current = setTimeout(() => {
        setSnackbar({ open: false, message: "", severity: "success" });
        if (onClose) onClose();
      }, 900);
    } catch (err) {
      setSnackbar({
        open: true,
        message: err?.message || "Fejl ved gemning.",
        severity: "error",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleDialogClose = () => {
    if (saving) return;
    if (onClose) onClose();
  };

  return (
    <Dialog
      open={open}
      onClose={handleDialogClose}
      maxWidth="xs"
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
              flex: "0 0 auto",
            }}
          >
            <AccessTimeIcon />
          </Box>
          <Box sx={{
            minWidth: 0
          }}>
            <Typography sx={{ fontWeight: 950, lineHeight: 1.15 }}>
              Rediger driftstid
            </Typography>
            <Typography variant="body2" sx={{ color: "rgba(203,213,225,0.68)", mt: 0.25 }}>
              {date ? formatFullDate(date) : "Vælg tænd- og sluktid"}
            </Typography>
          </Box>
        </Stack>
      </DialogTitle>
      <DialogContent sx={{ pt: 1.2 }}>
        <Stack spacing={2}>
          <Stack direction="row" spacing={1} useFlexGap sx={{
            flexWrap: "wrap"
          }}>
            <Chip size="small" label={`Sæson ${seasonStr || "ukendt"}`} sx={compactDarkChipSx("info")} />
            <Chip
              size="small"
              label={defaultTimes.status === "off" ? "Standard: slukket" : `Standard ${defaultTimes.onTime}–${defaultTimes.offTime}`}
              sx={compactDarkChipSx("neutral")}
            />
          </Stack>

          {loading ? (
            <Box sx={{ minHeight: 130, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Stack spacing={1.2} sx={{
                alignItems: "center"
              }}>
                <CircularProgress />
                <Typography sx={{ color: "rgba(203,213,225,0.74)" }}>Henter tider...</Typography>
              </Stack>
            </Box>
          ) : (
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1.4}>
              <Box sx={{ flex: 1 }}>
                <Typography variant="subtitle2" sx={{ mb: 0.75, fontWeight: 900, color: "rgba(226,232,240,0.90)", display: "flex", alignItems: "center", gap: 0.6 }}>
                  <WbSunnyIcon sx={{ fontSize: 17, color: "#fde68a" }} /> Tænd
                </Typography>
                <TextField
                  type="time"
                  fullWidth
                  value={onTime}
                  onChange={(event) => setOnTime(event.target.value)}
                  slotProps={{
                    htmlInput: { min: EARLIEST, max: onTimeMax, step: 300 }
                  }}
                />
              </Box>

              <Box sx={{ flex: 1 }}>
                <Typography variant="subtitle2" sx={{ mb: 0.75, fontWeight: 900, color: "rgba(226,232,240,0.90)", display: "flex", alignItems: "center", gap: 0.6 }}>
                  <NightsStayIcon sx={{ fontSize: 17, color: "#bfdbfe" }} /> Sluk
                </Typography>
                <TextField
                  type="time"
                  fullWidth
                  value={offTime}
                  onChange={(event) => setOffTime(event.target.value)}
                  slotProps={{
                    htmlInput: { min: offTimeMin, max: LATEST, step: 300 }
                  }}
                />
              </Box>
            </Stack>
          )}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2.5, pt: 1 }}>
        <Button onClick={handleDialogClose} color="inherit" disabled={saving || loading} sx={{ borderRadius: 2, fontWeight: 850 }}>
          Annullér
        </Button>
        <Button
          onClick={handleSave}
          variant="contained"
          disabled={saving || loading}
          loading={saving}
          sx={{ borderRadius: 2, fontWeight: 950, minWidth: 92 }}
        >
          Gem
        </Button>
      </DialogActions>
      <AppSnackbar
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={handleCloseSnackbar}
      />
    </Dialog>
  );
}
