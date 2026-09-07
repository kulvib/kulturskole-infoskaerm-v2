import * as React from "react";
import {
  Alert,
  Box,
  Button,
  IconButton,
  InputAdornment,
  Paper,
  TextField,
  Typography,
} from "@mui/material";
import Visibility from "@mui/icons-material/Visibility";
import VisibilityOff from "@mui/icons-material/VisibilityOff";
import { Link as RouterLink, useNavigate, useSearchParams } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { login as apiLogin, apiUrl, readJsonResponse } from "./api";
import { PRODUCT_BRAND } from "./branding";
import { consumeSessionEndMessage } from "./auth/sessionPolicy";
import { formatApiError, formatRateLimitMessage } from "./api/apiError";

const DISPLAY_LOGO_SRC = PRODUCT_BRAND.logo.dark;
const API_BASE = apiUrl || "";

// ─── Opmuntrende beskeder mens server vågner ────────────────────────────────
const SERVER_MESSAGES = [
  { after: 0, msg: "Venter på server..." },
  { after: 7, msg: "Venter stadig... serveren starter op 🔄" },
  { after: 14, msg: "Det tager lidt tid... serveren vågner langsomt ☕" },
  { after: 21, msg: "Næsten der... serveren er ved at komme sig 💤" },
  { after: 28, msg: "Serveren strækker sig og gaber... 🥱" },
  { after: 35, msg: "Den er ved at vågne ⏳" },
  { after: 42, msg: "Hænger lidt i bremsen... hav tålmodighed 😃" },
  { after: 49, msg: "Stadig i gang... du er tålmodig, vi er taknemmelige 🙏" },
  { after: 56, msg: "Det tager lidt længere end normalt... 💪" },
  { after: 63, msg: "Vi er stadig på sagen... giv ikke op! 🚀" },
  { after: 70, msg: "Snart... vi lover! ⚡" },
  { after: 77, msg: "Sidste stræk! Serveren er næsten klar 🏁" },
  { after: 84, msg: "Øjeblik endnu... du er næsten i mål! 🎯" },
];

const BACKGROUND_WARMUP_TIMEOUT_MS = 90_000;
const RETRY_MS = 3_000;

function fetchWithTimeout(url, options = {}, timeoutMs = 10_000) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);

  return fetch(url, {
    ...options,
    signal: controller.signal,
  }).finally(() => {
    window.clearTimeout(timeoutId);
  });
}

function destinationAfterLogin() {
  return "/";
}

async function waitForOk(url, timeoutMs, retryMs) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    try {
      const remaining = deadline - Date.now();
      const res = await fetchWithTimeout(url, {}, Math.min(10_000, remaining));
      if (res.ok) {
        await readJsonResponse(res, "Health-endpoint returnerede ikke JSON");
        return true;
      }
    } catch {
      // timeout, netværksfejl eller HTML fra frontend fallback → prøv igen
    }

    const remaining = deadline - Date.now();
    if (remaining <= 0) break;
    await new Promise((r) => setTimeout(r, Math.min(retryMs, remaining)));
  }

  return false;
}

async function warmServerAndDatabase() {
  const serverOk = await waitForOk(`${API_BASE}/health`, BACKGROUND_WARMUP_TIMEOUT_MS, RETRY_MS);
  if (!serverOk) return false;
  return waitForOk(`${API_BASE}/health/db`, BACKGROUND_WARMUP_TIMEOUT_MS, RETRY_MS);
}

export default function LoginPage() {
  const [credentials, setCredentials] = React.useState({ username: "", password: "" });
  const [showPassword, setShowPassword] = React.useState(false);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [statusMsg, setStatusMsg] = React.useState("");
  const [warmupMsg, setWarmupMsg] = React.useState("");
  const [sessionEndMessage, setSessionEndMessage] = React.useState(() => consumeSessionEndMessage());
  const warmupPromiseRef = React.useRef(null);
  const [searchParams] = useSearchParams();

  const { loginUser } = useAuth();
  const navigate = useNavigate();

  React.useEffect(() => {
    let cancelled = false;
    const showWarmupTimer = window.setTimeout(() => {
      if (!cancelled) {
        setWarmupMsg("Forbereder server og database i baggrunden. Du kan udfylde login med det samme.");
      }
    }, 2_500);

    warmupPromiseRef.current = warmServerAndDatabase()
      .catch(() => false)
      .finally(() => {
        window.clearTimeout(showWarmupTimer);
        if (!cancelled) setWarmupMsg("");
      });

    return () => {
      cancelled = true;
      window.clearTimeout(showWarmupTimer);
    };
  }, []);

  const handleChange = (e) => {
    setCredentials((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setStatusMsg("");
    setSessionEndMessage("");
    setLoading(true);

    const startedAt = Date.now();

    const msgInterval = setInterval(() => {
      const elapsed = (Date.now() - startedAt) / 1000;
      const current = [...SERVER_MESSAGES]
        .reverse()
        .find((m) => m.after <= elapsed);
      if (current) setStatusMsg(current.msg);
    }, 1000);

    try {
      setStatusMsg("Venter på server og database...");

      // Loginvinduet vises med det samme. Server/database vækkes allerede i
      // baggrunden fra useEffect ovenfor. Når brugeren trykker Log ind,
      // genbruger vi den igangværende warmup, så selve login-kaldet ikke får
      // Render's HTML-opstartsside i stedet for backend-JSON.
      const warmupOk = warmupPromiseRef.current
        ? await warmupPromiseRef.current
        : await warmServerAndDatabase();

      if (!warmupOk) {
        throw new Error("Serveren eller databasen svarer ikke — prøv at genindlæse siden.");
      }

      setStatusMsg("Forbinder...");

      const data = await apiLogin(credentials.username.trim(), credentials.password);
      const user = data?.user;
      if (!user) throw new Error("Uventet svar fra serveren.");
      loginUser(user, data?.session_expires_at || null);

      setStatusMsg("");

      if (user.must_change_password) {
        navigate("/skift-adgangskode", { replace: true });
      } else {
        const next = searchParams.get("next");
        navigate(next || destinationAfterLogin(), { replace: true });
      }
    } catch (err) {
      if (err?.name === "AbortError" || err?.name === "TimeoutError") {
        setError("Serveren svarer ikke — prøv at genindlæse siden.");
      } else {
        const status = err?.status ?? err?.response?.status;
        if (status === 401 || status === 403) {
          setError("Forkert brugernavn eller adgangskode.");
        } else if (status === 429) {
          setError(formatRateLimitMessage(err, "For mange login-forsøg. Prøv igen senere."));
        } else {
          setError(formatApiError(err, "Kunne ikke logge ind."));
        }
      }
    } finally {
      clearInterval(msgInterval);
      setLoading(false);
      setStatusMsg("");
    }
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background:
          "radial-gradient(circle at 16% 12%, rgba(56,189,248,0.18), transparent 34%), radial-gradient(circle at 82% 16%, rgba(20,184,166,0.13), transparent 30%), linear-gradient(135deg, #020617 0%, #07111f 45%, #0f172a 100%)",
        px: 2,
      }}
    >
      <Paper
        elevation={0}
        sx={{
          p: { xs: 3, sm: 5 },
          width: "100%",
          maxWidth: 420,
          color: "#f8fafc",
          background: "rgba(15,23,42,0.78)",
          border: "1px solid rgba(148,163,184,0.18)",
          boxShadow: "0 28px 110px rgba(0,0,0,0.42)",
          backdropFilter: "blur(18px)",
        }}
      >
        <Box sx={{ display: "flex", justifyContent: "center", mb: 3 }}>
          <Box
            component="img"
            src={DISPLAY_LOGO_SRC}
            alt={PRODUCT_BRAND.productName}
            sx={{ width: "min(280px, 100%)", height: "auto", display: "block" }}
          />
        </Box>

        <Typography variant="h5" gutterBottom>
          Log ind
        </Typography>

        <Typography
          variant="body2"
          sx={{
            color: "text.secondary",
            mb: 2,
            fontSize: "0.875rem"
          }}>
          Log ind med dit brugernavn eller din e-mailadresse.
        </Typography>

        <form onSubmit={handleSubmit} autoComplete="on">
          <TextField
            label="Brugernavn eller e-mail"
            name="username"
            value={credentials.username}
            onChange={handleChange}
            fullWidth
            margin="normal"
            required
            autoFocus
            autoComplete="username"
            slotProps={{
              htmlInput: {
                autoCapitalize: "none",
                autoCorrect: "off",
                spellCheck: "false",
              },

              inputLabel: { shrink: true }
            }} />

          <TextField
            label="Adgangskode"
            name="password"
            type={showPassword ? "text" : "password"}
            value={credentials.password}
            onChange={handleChange}
            fullWidth
            margin="normal"
            required
            autoComplete="current-password"
            slotProps={{
              input: {
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      aria-label={showPassword ? "Skjul adgangskode" : "Vis adgangskode"}
                      onClick={() => setShowPassword((s) => !s)}
                      edge="end"
                    >
                      {showPassword ? <VisibilityOff /> : <Visibility />}
                    </IconButton>
                  </InputAdornment>
                ),
              },

              htmlInput: {
                autoCapitalize: "none",
                autoCorrect: "off",
                spellCheck: "false",
              },

              inputLabel: { shrink: true }
            }} />

          {sessionEndMessage && !error && (
            <Alert severity="info" sx={{ mt: 2 }}>
              {sessionEndMessage}
            </Alert>
          )}

          {warmupMsg && !loading && !error && (
            <Alert severity="info" sx={{ mt: 2 }}>
              {warmupMsg}
            </Alert>
          )}

          {error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          )}

          {statusMsg && (
            <Alert severity="info" sx={{ mt: 2 }}>
              {statusMsg}
            </Alert>
          )}

          <Button
            type="submit"
            variant="contained"
            color="primary"
            fullWidth
            sx={{ mt: 3 }}
            disabled={loading}
            loading={loading}
            loadingPosition="start"
          >
            Log ind
          </Button>
        </form>

        <Button
          component={RouterLink}
          to="/glemt-adgangskode"
          type="button"
          variant="text"
          fullWidth
          sx={{ mt: 1, fontSize: "0.8125rem", textTransform: "none" }}
          disabled={loading}
        >
          Glemt adgangskode?
        </Button>
      </Paper>
    </Box>
  );
}
