import AppSnackbar from "../../components/AppSnackbar";
import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Box, CircularProgress, Typography, Button } from "@mui/material";
import ClientDetailsPage from "./ClientDetailsPage";
import { getClient, getMarkedDays, getCurrentSeason } from "../../api";

/*
  ClientDetailsPageWrapper.jsx

  Ny route-wrapper til clientdetailspage_new.
  Bruger samme data-/refresh-logik som den eksisterende detaljeside,
  men renderer ./ClientDetailsPage fra den nye mappe.

  Ansvar:
  - Initial load + manuel refresh af client-data.
  - silentRefresh: opdaterer client state UDEN snackbar og UDEN refreshing=true.
    Bruges af ClientDetailsPage efter action er bekræftet — ingen blinking.
  - handleRefresh: fuld refresh MED snackbar — kun ved manuel klik på "Opdater".
    Kalder cancelActionPoll via onCancelActionPollRef FØR refresh så evt.
    kørende action-polling stoppes rent og knapper låses op korrekt.
  - Ingen hurtig poll-loop — ClientDetailsPage ejer al action-polling via lokal state.
*/

export default function ClientDetailsPageWrapper({ showSnackbar: showSnackbarProp }) {
  const { id } = useParams();
  const navigate = useNavigate();

  const [client, setClient] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const [localSnackbar, setLocalSnackbar] = useState({
    open: false,
    message: "",
    severity: "success",
  });

  const [markedDays, setMarkedDays] = useState({});
  const [calendarLoading, setCalendarLoading] = useState(false);

  const [streamKey, setStreamKey] = useState(0);

  const mountedRef = useRef(true);

  // Ref til cancelActionPoll — sættes af ClientDetailsPage via onCancelActionPollRef
  const cancelActionPollRef = useRef(null);

  const showSnackbar = useCallback((opts) => {
    const message = opts?.message ?? "";
    const severity = opts?.severity ?? "success";

    if (typeof showSnackbarProp === "function") {
      showSnackbarProp({ message, severity });
      return;
    }

    setLocalSnackbar({
      open: true,
      message,
      severity,
    });
  }, [showSnackbarProp]);

  const handleCloseSnackbar = useCallback((_event, reason) => {
    if (reason === "clickaway") return;
    setLocalSnackbar((prev) => ({ ...prev, open: false }));
  }, []);

  // ---------------------------------------------------------------------------
  // Hent klient
  // ---------------------------------------------------------------------------
  const fetchClient = useCallback(async (isRefresh = false) => {
    if (!id) return;
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    setError(null);

    try {
      const data = await getClient(id);
      if (!mountedRef.current) return;
      if (!data) { setError("Klienten blev ikke fundet."); return; }
      setClient(data);
    } catch (err) {
      if (!mountedRef.current) return;
      if (err?.response?.status === 403 || err?.status === 403)
        setError("Du har ikke adgang til denne klient.");
      else if (err?.response?.status === 404 || err?.status === 404)
        setError("Klienten blev ikke fundet.");
      else
        setError("Kunne ikke hente klientdata: " + (err?.message || String(err)));
    } finally {
      if (mountedRef.current) { setLoading(false); setRefreshing(false); }
    }
  }, [id]);

  // ---------------------------------------------------------------------------
  // Stille refresh — opdaterer client state UDEN snackbar og UDEN refreshing=true
  // Bruges af ClientDetailsPage efter action-bekræftelse (ingen blinking)
  // ---------------------------------------------------------------------------
  const silentRefresh = useCallback(async () => {
    if (!id || !mountedRef.current) return;
    try {
      const data = await getClient(id);
      if (!mountedRef.current) return;
      if (data) setClient(data);
    } catch {
      // Ignorer fejl ved stille refresh
    }
  }, [id]);

  // ---------------------------------------------------------------------------
  // Hent kalender
  // ---------------------------------------------------------------------------
  const fetchMarkedDays = useCallback(async () => {
    if (!id) return;
    setCalendarLoading(true);
    try {
      const seasonData = await getCurrentSeason();
      const season = seasonData?.id ?? seasonData?.season ?? null;
      if (!season) { setMarkedDays({}); return; }
      const data = await getMarkedDays(season, id);
      if (!mountedRef.current) return;
      const days = data?.markedDays ?? data?.marked_days ?? data ?? {};
      setMarkedDays(typeof days === "object" && !Array.isArray(days) ? days : {});
    } catch (err) {
      if (!mountedRef.current) return;
      console.warn("Kunne ikke hente kalendermarkinger:", err?.message || err);
      setMarkedDays({});
    } finally {
      if (mountedRef.current) setCalendarLoading(false);
    }
  }, [id]);

  // ---------------------------------------------------------------------------
  // Stille refresh af både klient og kalender — bruges efter konfigurationsændringer
  // hvor fx organisationsskift kan påvirke kalendergrundlaget. Ingen snackbar/blink.
  // ---------------------------------------------------------------------------
  const silentRefreshAll = useCallback(async () => {
    if (!id || !mountedRef.current) return;
    await Promise.all([silentRefresh(), fetchMarkedDays()]);
  }, [id, silentRefresh, fetchMarkedDays]);

  // ---------------------------------------------------------------------------
  // Initial load
  // ---------------------------------------------------------------------------
  useEffect(() => {
    mountedRef.current = true;
    fetchClient(false);
    fetchMarkedDays();
    return () => { mountedRef.current = false; };
  }, [fetchClient, fetchMarkedDays]);

  // ---------------------------------------------------------------------------
  // Manuel refresh — MED snackbar, MED refreshing=true (spinner i header)
  // Stopper evt. kørende action-polling FØR refresh via cancelActionPollRef
  // ---------------------------------------------------------------------------
  const handleRefresh = useCallback(async () => {
    // Stop evt. kørende action-poll rent så knapper ikke forbliver låste
    if (typeof cancelActionPollRef.current === "function") {
      cancelActionPollRef.current();
    }
    await Promise.all([fetchClient(true), fetchMarkedDays()]);
    showSnackbar({ message: "Klient opdateret", severity: "success" });
  }, [fetchClient, fetchMarkedDays, showSnackbar]);

  const handleRestartStream = useCallback(() => {
    setStreamKey((prev) => prev + 1);
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  if (loading) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: 200, flexDirection: "column", gap: 2 }}>
        <CircularProgress />
        <Typography variant="body2" sx={{
          color: "text.secondary"
        }}>Henter klientdata...</Typography>
      </Box>
    );
  }

  if (error) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: 200, flexDirection: "column", gap: 2, px: 2 }}>
        <Typography variant="h6" color="error" align="center">{error}</Typography>
        <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", justifyContent: "center" }}>
          <Button variant="outlined" onClick={() => fetchClient(false)}>Prøv igen</Button>
          <Button variant="outlined" onClick={() => navigate("/clients")}>Tilbage til klientoversigt</Button>
        </Box>
      </Box>
    );
  }

  if (!client) {
    return (
      <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", minHeight: 200, flexDirection: "column", gap: 2 }}>
        <Typography variant="body1" sx={{
          color: "text.secondary"
        }}>Ingen klientdata tilgængelig.</Typography>
        <Button variant="outlined" onClick={() => navigate("/clients")}>Tilbage til klientoversigt</Button>
      </Box>
    );
  }

  return (
    <>
      <ClientDetailsPage
        client={client}
        refreshing={refreshing}
        handleRefresh={handleRefresh}
        silentRefresh={silentRefresh}
        silentRefreshAll={silentRefreshAll}
        onCancelActionPollRef={cancelActionPollRef}
        markedDays={markedDays}
        calendarLoading={calendarLoading}
        streamKey={streamKey}
        onRestartStream={handleRestartStream}
        showSnackbar={showSnackbar}
      />

      <AppSnackbar
        open={localSnackbar.open}
        message={localSnackbar.message}
        severity={localSnackbar.severity}
        onClose={handleCloseSnackbar}
      />
    </>
  );
}
