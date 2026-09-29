import * as React from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getMaintenanceStatus, updateMaintenanceStatus } from "../../auth/maintenanceApi";
import { requireMaintenanceStatus } from "../../auth/maintenanceIntegrity";

function toLocalInput(value) {
  if (!value) return "";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "";
  const offset = date.getTimezoneOffset();
  return new Date(date.getTime() - offset * 60_000).toISOString().slice(0, 16);
}

function ConfirmDialog({ open, enabling, pending, error, onCancel, onConfirm }) {
  const [password, setPassword] = React.useState("");
  React.useEffect(() => { if (!open) setPassword(""); }, [open]);
  const submit = (event) => {
    event.preventDefault();
    if (!password || pending) return;
    onConfirm(password);
  };
  return (
    <Dialog open={open} onClose={pending ? undefined : onCancel} fullWidth maxWidth="xs">
      <Box component="form" onSubmit={submit}>
        <DialogTitle>{enabling ? "Aktivér vedligeholdelse" : "Åbn PlanIQ Display igen"}</DialogTitle>
        <DialogContent>
          <DialogContentText sx={{ mb: 2 }}>
            Bekræft din adgangskode. Ændringen påvirker al menneskelig brugeradgang og registreres i auditloggen.
          </DialogContentText>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <TextField autoFocus fullWidth type="password" label="Adgangskode" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </DialogContent>
        <DialogActions>
          <Button onClick={onCancel} disabled={pending}>Annuller</Button>
          <Button type="submit" variant="contained" color={enabling ? "warning" : "success"} disabled={!password || pending}>
            {pending ? "Gemmer…" : "Bekræft"}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}

export default function MaintenanceAdministration() {
  const [state, setState] = React.useState(null);
  const [message, setMessage] = React.useState("");
  const [expectedEnd, setExpectedEnd] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");
  const [pendingEnabled, setPendingEnabled] = React.useState(null);
  const [confirmError, setConfirmError] = React.useState("");
  const controllerRef = React.useRef(null);
  const seqRef = React.useRef(0);

  const apply = React.useCallback((value) => {
    const valid = requireMaintenanceStatus(value);
    setState(valid);
    setMessage(valid.message || "");
    setExpectedEnd(toLocalInput(valid.expected_end_at));
    return valid;
  }, []);

  const load = React.useCallback(async ({ preserveError = false } = {}) => {
    const seq = ++seqRef.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    if (!preserveError) setError("");
    try {
      const next = await getMaintenanceStatus(controller.signal);
      if (controller.signal.aborted || seqRef.current !== seq) return;
      apply(next);
    } catch (err) {
      if (controller.signal.aborted || err?.name === "AbortError") return;
      if (!preserveError && seqRef.current === seq) setError(err?.message || "Kunne ikke hente vedligeholdelsesstatus");
    } finally {
      if (!controller.signal.aborted && seqRef.current === seq) setLoading(false);
    }
  }, [apply]);

  React.useEffect(() => {
    void load();
    return () => controllerRef.current?.abort();
  }, [load]);

  const performUpdate = React.useCallback(async (enabled, password) => {
    setSaving(true);
    setConfirmError("");
    setError("");
    setSuccess("");
    try {
      const next = await updateMaintenanceStatus({
        enabled,
        password,
        message: enabled ? (message.trim() || null) : null,
        expected_end_at: enabled && expectedEnd ? new Date(expectedEnd).toISOString() : null,
      });
      apply(next);
      setPendingEnabled(null);
      setSuccess(enabled ? "Vedligeholdelsestilstand er aktiveret." : "PlanIQ Display er åbnet igen.");
      globalThis.dispatchEvent?.(new CustomEvent("planiq:maintenance"));
    } catch (err) {
      if (err?.status === 403 || err?.status === 429) {
        setConfirmError(err?.message || "Adgangskoden kunne ikke bekræftes");
      } else {
        setPendingEnabled(null);
        setError(err?.message || "Kunne ikke ændre vedligeholdelsestilstand");
        await load({ preserveError: true });
      }
    } finally {
      setSaving(false);
    }
  }, [apply, expectedEnd, load, message]);

  const statusKnown = state !== null;
  return (
    <Stack spacing={2.2}>
      <Box>
        <Typography variant="h5" sx={{ fontWeight: 900 }}>Vedligeholdelse</Typography>
        <Typography sx={{ color: "rgba(203,213,225,0.72)", mt: 0.5 }}>
          Luk menneskelig brugeradgang kontrolleret under release- eller databasearbejde. ClientFlow-klienter, health-endpoints og superadministratoradgang fortsætter.
        </Typography>
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      {success && <Alert severity="success">{success}</Alert>}
      {!statusKnown && loading ? (
        <Box sx={{ py: 4, display: "flex", justifyContent: "center" }}><CircularProgress aria-label="Henter vedligeholdelsesstatus" /></Box>
      ) : !statusKnown ? (
        <Alert severity="error">Vedligeholdelsesstatus kunne ikke bekræftes. Genindlæs status, før du foretager ændringer.</Alert>
      ) : (
        <Alert severity={state.enabled ? "warning" : "success"}>
          {state.enabled ? "Vedligeholdelse er AKTIV for menneskelige brugere." : "PlanIQ Display er åbent for normal brugeradgang."}
        </Alert>
      )}
      <Paper elevation={0} sx={{ p: { xs: 2, md: 3 }, bgcolor: "rgba(15,23,42,0.74)", border: "1px solid rgba(148,163,184,0.16)" }}>
        <Stack spacing={2}>
          <TextField label="Besked til brugerne" value={message} onChange={(e) => setMessage(e.target.value)} disabled={!statusKnown || saving} slotProps={{ htmlInput: { maxLength: 500 } }} />
          <TextField type="datetime-local" label="Forventet åbning" value={expectedEnd} onChange={(e) => setExpectedEnd(e.target.value)} disabled={!statusKnown || saving} slotProps={{ inputLabel: { shrink: true } }} />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
            {statusKnown && (state.enabled ? (
              <Button variant="contained" color="success" disabled={saving || loading} onClick={() => { setConfirmError(""); setPendingEnabled(false); }}>Åbn PlanIQ Display igen</Button>
            ) : (
              <Button variant="contained" color="warning" disabled={saving || loading} onClick={() => { setConfirmError(""); setPendingEnabled(true); }}>Aktivér vedligeholdelse</Button>
            ))}
            <Button variant="outlined" disabled={saving || loading} onClick={() => void load()}>{loading ? "Henter…" : "Genindlæs status"}</Button>
          </Stack>
          <Typography variant="caption" sx={{ color: "rgba(203,213,225,0.68)" }}>
            Aktivering og deaktivering kræver ny adgangskodebekræftelse og registreres i auditloggen.
          </Typography>
        </Stack>
      </Paper>
      <ConfirmDialog
        open={typeof pendingEnabled === "boolean"}
        enabling={pendingEnabled === true}
        pending={saving}
        error={confirmError}
        onCancel={() => { if (!saving) { setPendingEnabled(null); setConfirmError(""); } }}
        onConfirm={(password) => void performUpdate(Boolean(pendingEnabled), password)}
      />
    </Stack>
  );
}
