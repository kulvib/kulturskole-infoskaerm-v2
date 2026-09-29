import * as React from "react";
import { Alert, Box, Button, CircularProgress, Paper, Stack, Typography } from "@mui/material";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "./AuthProvider";
import { getMaintenanceStatus } from "./maintenanceApi";
import { requireMaintenanceStatus } from "./maintenanceIntegrity";
import { formatMaintenanceExpectedAt } from "./maintenanceFormatting";
import { hasSuperadminRole } from "../utils/roleUtils";

const POLL_MS = 15_000;

function MaintenanceScreen({ state, canStopImpersonation, onStopImpersonation, stopping, stopError }) {
  const navigate = useNavigate();
  const expected = formatMaintenanceExpectedAt(state?.expected_end_at);
  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", p: 2, bgcolor: "#020617" }}>
      <Paper elevation={0} sx={{ width: "100%", maxWidth: 640, p: { xs: 3, sm: 5 }, bgcolor: "#0f172a", color: "#f8fafc", border: "1px solid rgba(148,163,184,0.18)" }}>
        <Stack spacing={2}>
          <Typography variant="h4" component="h1" sx={{ fontWeight: 900 }}>PlanIQ Display er midlertidigt lukket</Typography>
          <Alert severity="info">{state?.message || "PlanIQ Display er midlertidigt utilgængelig på grund af vedligeholdelse."}</Alert>
          {expected && <Typography>Forventet åbning: <strong>{expected}</strong></Typography>}
          <Typography sx={{ color: "rgba(226,232,240,0.72)" }}>
            Infoskærmenes ClientFlow-drift fortsætter. Siden kontrollerer automatisk, når brugeradgangen åbnes igen.
          </Typography>
          {stopError && <Alert severity="error">{stopError}</Alert>}
          {canStopImpersonation && (
            <Button variant="contained" onClick={onStopImpersonation} disabled={stopping}>
              {stopping ? "Skifter tilbage…" : "Tilbage til min bruger"}
            </Button>
          )}
          <Button variant="outlined" onClick={() => navigate("/login?maintenance_admin=1")}>
            Superadministratorlogin
          </Button>
        </Stack>
      </Paper>
    </Box>
  );
}

function StatusError({ retry, checking }) {
  return (
    <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center", p: 2, bgcolor: "#020617" }}>
      <Paper elevation={0} sx={{ width: "100%", maxWidth: 640, p: { xs: 3, sm: 5 }, bgcolor: "#0f172a", color: "#f8fafc" }}>
        <Stack spacing={2}>
          <Typography variant="h4" component="h1">Driftsstatus kunne ikke bekræftes</Typography>
          <Alert severity="error">PlanIQ Display kan ikke afgøre, om brugeradgangen er åben eller under vedligeholdelse. Adgangen forbliver lukket, indtil status kan bekræftes.</Alert>
          <Button variant="contained" onClick={retry} disabled={checking}>{checking ? "Kontrollerer…" : "Prøv igen"}</Button>
        </Stack>
      </Paper>
    </Box>
  );
}

export default function MaintenanceGate({ children }) {
  const { user, loading, stopImpersonation } = useAuth();
  const location = useLocation();
  const [state, setState] = React.useState(null);
  const [checking, setChecking] = React.useState(true);
  const [statusError, setStatusError] = React.useState("");
  const [stopping, setStopping] = React.useState(false);
  const [stopError, setStopError] = React.useState("");
  const seqRef = React.useRef(0);
  const controllerRef = React.useRef(null);
  const stateRef = React.useRef(null);

  const refresh = React.useCallback(async () => {
    const seq = ++seqRef.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    if (!stateRef.current) setChecking(true);
    try {
      const next = requireMaintenanceStatus(await getMaintenanceStatus(controller.signal));
      if (controller.signal.aborted || seqRef.current !== seq) return;
      stateRef.current = next;
      setState(next);
      setStatusError("");
    } catch (error) {
      if (controller.signal.aborted || error?.name === "AbortError") return;
      if (seqRef.current === seq) setStatusError(error?.message || "Vedligeholdelsesstatus kunne ikke hentes");
    } finally {
      if (!controller.signal.aborted && seqRef.current === seq) setChecking(false);
    }
  }, []);

  React.useEffect(() => {
    void refresh();
    return () => controllerRef.current?.abort();
  }, [refresh]);

  React.useEffect(() => {
    if (!state?.enabled) return undefined;
    const timer = window.setInterval(() => void refresh(), POLL_MS);
    return () => window.clearInterval(timer);
  }, [refresh, state?.enabled]);

  React.useEffect(() => {
    const onFocus = () => void refresh();
    const onChanged = () => void refresh();
    window.addEventListener("focus", onFocus);
    globalThis.addEventListener?.("planiq:maintenance", onChanged);
    return () => {
      window.removeEventListener("focus", onFocus);
      globalThis.removeEventListener?.("planiq:maintenance", onChanged);
    };
  }, [refresh]);

  const stop = React.useCallback(async () => {
    if (stopping || typeof stopImpersonation !== "function") return;
    setStopping(true);
    setStopError("");
    try {
      await stopImpersonation();
      await refresh();
    } catch (error) {
      setStopError(error?.message || "Kunne ikke skifte tilbage til din bruger");
    } finally {
      setStopping(false);
    }
  }, [refresh, stopImpersonation, stopping]);

  const adminLogin = location.pathname === "/login" && new URLSearchParams(location.search).get("maintenance_admin") === "1";
  if (checking && !state) {
    return <Box sx={{ minHeight: "100vh", display: "grid", placeItems: "center" }}><CircularProgress aria-label="Kontrollerer driftsstatus" /></Box>;
  }
  if (!state && statusError) return <StatusError retry={() => void refresh()} checking={checking} />;

  const actorIsSuperadmin = user?.impersonation_active === true && user?.actor_role === "superadmin";
  const superadmin = !loading && (hasSuperadminRole(user) || actorIsSuperadmin);
  if (state?.enabled && !superadmin && !adminLogin) {
    return (
      <MaintenanceScreen
        state={state}
        canStopImpersonation={user?.impersonation_active === true}
        onStopImpersonation={stop}
        stopping={stopping}
        stopError={stopError}
      />
    );
  }
  return children;
}
