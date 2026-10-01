import React from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import DevicesIcon from "@mui/icons-material/Devices";
import { useAuth } from "./auth/AuthProvider";
import {
  listActiveSessions,
  revokeOtherSessions,
  revokeSession,
} from "./auth/sessionSecurityApi";
import {
  expectActiveSessionsPayload,
  expectSessionRevokePayload,
} from "./auth/sessionSecurityIntegrity";

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "—";
  return date.toLocaleString("da-DK", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function ReauthenticationDialog({ open, action, pending, error, onClose, onSubmit }) {
  const [password, setPassword] = React.useState("");

  React.useEffect(() => {
    if (!open) setPassword("");
  }, [open]);

  const title = action?.type === "others" ? "Log ud af alle andre sessioner" : "Afslut session";
  const description = action?.type === "others"
    ? "Bekræft din adgangskode for at afslutte alle andre aktive sessioner. Denne session forbliver aktiv."
    : "Bekræft din adgangskode for at afslutte den valgte session med det samme.";

  const submit = (event) => {
    event.preventDefault();
    if (!password || pending) return;
    onSubmit(password);
  };

  return (
    <Dialog
      open={open}
      onClose={pending ? undefined : onClose}
      fullWidth
      maxWidth="xs"
      aria-labelledby="session-reauth-title"
      aria-describedby="session-reauth-description"
    >
      <Box component="form" onSubmit={submit}>
        <DialogTitle id="session-reauth-title">{title}</DialogTitle>
        <DialogContent>
          <DialogContentText id="session-reauth-description" sx={{ mb: 2 }}>
            {description}
          </DialogContentText>
          {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
          <TextField
            autoFocus
            fullWidth
            type="password"
            label="Din adgangskode"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
            disabled={pending}
            slotProps={{ htmlInput: { maxLength: 256 } }}
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2.5 }}>
          <Button onClick={onClose} disabled={pending}>Annuller</Button>
          <Button type="submit" variant="contained" color="error" disabled={pending || !password}>
            {pending ? <CircularProgress size={20} color="inherit" /> : "Bekræft og afslut"}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}

export default function SessionSecurityPage() {
  const { isImpersonating } = useAuth();
  const [sessions, setSessions] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");
  const [reauthAction, setReauthAction] = React.useState(null);
  const [reauthPending, setReauthPending] = React.useState(false);
  const [reauthError, setReauthError] = React.useState("");
  const revokeInFlightRef = React.useRef(false);
  const requestRef = React.useRef({ id: 0, controller: null });

  const load = React.useCallback(async ({ preserveMessages = false } = {}) => {
    if (isImpersonating) {
      setSessions([]);
      setLoading(false);
      return;
    }
    const id = requestRef.current.id + 1;
    requestRef.current.controller?.abort();
    const controller = new AbortController();
    requestRef.current = { id, controller };
    setLoading(true);
    if (!preserveMessages) {
      setError("");
      setSuccess("");
    }
    try {
      const data = expectActiveSessionsPayload(await listActiveSessions(controller.signal));
      if (requestRef.current.id === id) setSessions(data);
    } catch (err) {
      if (requestRef.current.id === id && !controller.signal.aborted) {
        setError(err?.message || "Kunne ikke hente aktive sessioner");
      }
    } finally {
      if (requestRef.current.id === id) setLoading(false);
    }
  }, [isImpersonating]);

  React.useEffect(() => {
    void load();
    return () => requestRef.current.controller?.abort();
  }, [load]);

  const openReauthentication = (action) => {
    setError("");
    setSuccess("");
    setReauthError("");
    setReauthAction(action);
  };

  const closeReauthentication = () => {
    if (revokeInFlightRef.current) return;
    setReauthAction(null);
    setReauthError("");
  };

  const submitReauthentication = async (password) => {
    if (!reauthAction || revokeInFlightRef.current) return;
    const action = reauthAction;
    revokeInFlightRef.current = true;
    setReauthPending(true);
    setReauthError("");
    try {
      if (action.type === "others") {
        const result = expectSessionRevokePayload(await revokeOtherSessions(password));
        setSuccess(`${result.revoked_count} andre sessioner er afsluttet.`);
      } else {
        expectSessionRevokePayload(await revokeSession(action.sessionId, password));
        setSuccess("Sessionen er afsluttet.");
      }
      setReauthAction(null);
      await load({ preserveMessages: true });
    } catch (err) {
      setReauthError(err?.message || "Handlingen kunne ikke gennemføres.");
    } finally {
      revokeInFlightRef.current = false;
      setReauthPending(false);
    }
  };

  if (isImpersonating) {
    return (
      <Box sx={{ maxWidth: 900, mx: "auto", p: { xs: 2, md: 3 } }}>
        <Alert severity="warning">
          Afslut Skift bruger, før du administrerer sessionerne for din egen konto.
        </Alert>
      </Box>
    );
  }

  const otherSessions = sessions.filter((session) => !session.current);

  return (
    <Box sx={{ maxWidth: 900, mx: "auto", p: { xs: 2, md: 3 } }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        justifyContent="space-between"
        alignItems={{ xs: "stretch", sm: "flex-start" }}
        gap={2}
        sx={{ mb: 3 }}
      >
        <Box>
          <Typography variant="h4" component="h1">Sessioner og sikkerhed</Typography>
          <Typography color="text.secondary">
            Se hvor din konto er logget ind, og afslut sessioner du ikke genkender.
          </Typography>
        </Box>
        <Button
          variant="outlined"
          onClick={() => openReauthentication({ type: "others" })}
          disabled={loading || otherSessions.length === 0}
          sx={{ ml: { sm: "auto" }, alignSelf: { xs: "stretch", sm: "flex-start" }, flexShrink: 0 }}
        >
          Log ud på alle andre enheder
        </Button>
      </Stack>

      {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
      {success && <Alert severity="success" sx={{ mb: 2 }}>{success}</Alert>}

      {loading && sessions.length === 0 ? (
        <Box role="status" aria-live="polite" sx={{ display: "flex", justifyContent: "center", py: 6 }}>
          <CircularProgress />
        </Box>
      ) : (
        <Stack spacing={2}>
          {sessions.map((session) => (
            <Card key={session.session_id} variant="outlined">
              <CardContent>
                <Stack
                  direction={{ xs: "column", sm: "row" }}
                  justifyContent="space-between"
                  alignItems={{ xs: "stretch", sm: "flex-start" }}
                  gap={2}
                >
                  <Stack direction="row" spacing={1.5} alignItems="flex-start" sx={{ minWidth: 0 }}>
                    <DevicesIcon sx={{ mt: 0.25, flexShrink: 0 }} />
                    <Box sx={{ minWidth: 0 }}>
                      <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap" sx={{ mb: 0.75 }}>
                        <Typography fontWeight={700}>{session.user_agent || "Ukendt browser/enhed"}</Typography>
                        {session.current && <Chip size="small" color="success" label="Denne session" />}
                        {session.impersonation_active && <Chip size="small" color="warning" label="Skift bruger aktivt" />}
                      </Stack>
                      <Typography variant="body2" color="text.secondary">
                        Senest fornyet: {formatDateTime(session.refreshed_at)}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Udløber senest: {formatDateTime(session.session_expires_at)}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        IP ved seneste fornyelse: {session.ip_address || "—"}
                      </Typography>
                    </Box>
                  </Stack>
                  {!session.current && (
                    <Button color="error" onClick={() => openReauthentication({ type: "single", sessionId: session.session_id })}>
                      Afslut
                    </Button>
                  )}
                </Stack>
              </CardContent>
            </Card>
          ))}
          {!loading && !error && sessions.length === 0 && (
            <>
              <Divider />
              <Typography color="text.secondary">Ingen aktive sessioner fundet.</Typography>
            </>
          )}
        </Stack>
      )}

      <ReauthenticationDialog
        open={Boolean(reauthAction)}
        action={reauthAction}
        pending={reauthPending}
        error={reauthError}
        onClose={closeReauthentication}
        onSubmit={submitReauthentication}
      />
    </Box>
  );
}
