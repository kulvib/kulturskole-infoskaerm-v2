import * as React from "react";
import {
  Alert,
  Box,
  Button,
  LinearProgress,
  IconButton,
  InputAdornment,
  Paper,
  TextField,
  Typography,
} from "@mui/material";
import Visibility from "@mui/icons-material/Visibility";
import VisibilityOff from "@mui/icons-material/VisibilityOff";
import {
  Link as RouterLink,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { apiUrl } from "./api";
import { formatApiError } from "./api/apiError";

const DISPLAY_LOGO_SRC = "/brand/planiq-display/planiq-display-logo-on-dark.png";

const PASSWORD_MIN_LENGTH = 12;
const PASSWORD_MAX_UTF8_BYTES = 72;
const PASSWORD_HELPER_TEXT =
  "Mindst 12 tegn.";
const REDIRECT_DELAY_MS = 2500;
const COMMON_PASSWORDS = new Set([
  "password",
  "password1",
  "password12",
  "password123",
  "password123!",
  "qwerty123",
  "qwerty1234",
  "admin1234",
  "velkommen123",
  "adgangskode",
  "adgangskode123",
  "sommer2025",
  "sommer2026",
  "planiq123",
  "123456789012",
]);

function isValidPassword(value) {
  if (typeof value !== "string") return false;
  if (value.length < PASSWORD_MIN_LENGTH) return false;
  if (new TextEncoder().encode(value).length > PASSWORD_MAX_UTF8_BYTES) return false;
  if (/[\u0000-\u001F\u007F]/.test(value)) return false;
  return !COMMON_PASSWORDS.has(value.trim().toLowerCase());
}

function getErrorMessage(payload, fallback = "Der opstod en fejl") {
  if (!payload) return fallback;
  if (typeof payload === "string") return payload || fallback;
  if (typeof payload.detail === "string") return payload.detail;
  if (typeof payload.message === "string") return payload.message;
  if (Array.isArray(payload.detail)) {
    const msg = payload.detail
      .map((item) => item?.msg || item?.message || item)
      .filter(Boolean)
      .join(". ");
    return msg || fallback;
  }
  return fallback;
}

async function readResponseBody(res) {
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }
  try {
    return await res.text();
  } catch {
    return null;
  }
}

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { logout } = useAuth();
  const token = (searchParams.get("token") || "").trim();

  const [password, setPassword] = React.useState("");
  const [passwordRepeat, setPasswordRepeat] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [showPasswordRepeat, setShowPasswordRepeat] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");
  const [progress, setProgress] = React.useState(0);

  React.useEffect(() => {
    if (!success) return undefined;
    setProgress(0);
    const interval = window.setInterval(
      () => setProgress((value) => Math.min(value + 4, 100)),
      REDIRECT_DELAY_MS / 25
    );
    const timeout = window.setTimeout(() => {
      logout();
      navigate("/login", { replace: true });
    }, REDIRECT_DELAY_MS);
    return () => {
      window.clearInterval(interval);
      window.clearTimeout(timeout);
    };
  }, [success, logout, navigate]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");

    if (!token) {
      setError("Nulstillingslinket mangler token. Bed om et nyt link.");
      return;
    }
    if (password !== passwordRepeat) {
      setError("Adgangskoder matcher ikke.");
      return;
    }
    if (!isValidPassword(password)) {
      setError(
        "Adgangskoden skal være mindst 12 tegn, må ikke indeholde linjeskift og må ikke være for almindelig."
      );
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/users/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ token, password }),
      });
      const data = await readResponseBody(res);
      if (!res.ok) {
        throw new Error(getErrorMessage(data, "Kunne ikke nulstille adgangskode. Prøv med et nyt link."));
      }
      setSuccess("Adgangskoden er ændret. Du sendes nu til login.");
      setPassword("");
      setPasswordRepeat("");
    } catch (err) {
      setError(formatApiError(err, "Kunne ikke nulstille adgangskode."));
    } finally {
      setLoading(false);
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
          maxWidth: 520,
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
            alt="PlanIQ Display"
            sx={{ width: "min(280px, 100%)", height: "auto", display: "block" }}
          />
        </Box>
        <Typography variant="h5" gutterBottom>
          Vælg ny adgangskode
        </Typography>

        {!token && (
          <Alert severity="error" sx={{ mb: 2 }}>
            Linket mangler token. Bed om et nyt nulstillingslink.
          </Alert>
        )}

        <Typography
          variant="body2"
          sx={{
            color: "text.secondary",
            mb: 2,
            fontSize: "0.875rem"
          }}>
          Vælg en ny adgangskode til din PlanIQ Display-konto.
        </Typography>

        <form onSubmit={handleSubmit} autoComplete="on">
          <TextField
            label="Ny adgangskode"
            name="newPassword"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            fullWidth
            margin="normal"
            required
            autoFocus
            autoComplete="new-password"
            helperText={PASSWORD_HELPER_TEXT}
            slotProps={{
              input: {
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      aria-label={
                        showPassword ? "Skjul adgangskode" : "Vis adgangskode"
                      }
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

              inputLabel: { shrink: true },
              formHelperText: { sx: { fontSize: "0.75rem" } }
            }} />

          <TextField
            label="Gentag adgangskode"
            name="newPasswordRepeat"
            type={showPasswordRepeat ? "text" : "password"}
            value={passwordRepeat}
            onChange={(e) => setPasswordRepeat(e.target.value)}
            fullWidth
            margin="normal"
            required
            autoComplete="new-password"
            slotProps={{
              input: {
                endAdornment: (
                  <InputAdornment position="end">
                    <IconButton
                      aria-label={
                        showPasswordRepeat
                          ? "Skjul adgangskode"
                          : "Vis adgangskode"
                      }
                      onClick={() => setShowPasswordRepeat((s) => !s)}
                      edge="end"
                    >
                      {showPasswordRepeat ? <VisibilityOff /> : <Visibility />}
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

          {error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          )}

          {success && (
            <Box sx={{ mt: 2 }}>
              <Alert severity="success">{success}</Alert>
              <LinearProgress
                variant="determinate"
                value={progress}
                sx={{ mt: 2, height: 8, borderRadius: 5 }}
              />
            </Box>
          )}

          <Button
            type="submit"
            variant="contained"
            color="primary"
            fullWidth
            sx={{ mt: 3 }}
            disabled={loading || !token || Boolean(success)}
            loading={loading}
            loadingPosition="start"
          >
            Gem ny adgangskode
          </Button>
        </form>

        {success ? (
          <Button
            type="button"
            variant="text"
            fullWidth
            sx={{ mt: 1, fontSize: "0.8125rem", textTransform: "none" }}
            onClick={() => {
              logout();
              navigate("/login", { replace: true });
            }}
          >
            Gå til login nu
          </Button>
        ) : (
          <Button
            component={RouterLink}
            to="/glemt-adgangskode"
            type="button"
            variant="text"
            fullWidth
            sx={{ mt: 1, fontSize: "0.8125rem", textTransform: "none" }}
          >
            Bed om nyt link
          </Button>
        )}
      </Paper>
    </Box>
  );
}
