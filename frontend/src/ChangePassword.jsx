import * as React from "react";
import {
  Box,
  Paper,
  Typography,
  TextField,
  Button,
  Alert,
  LinearProgress,
  CircularProgress,
  IconButton,
  InputAdornment,
} from "@mui/material";
import { useAuth } from "./auth/AuthProvider";
import { useNavigate } from "react-router-dom";
import Visibility from "@mui/icons-material/Visibility";
import VisibilityOff from "@mui/icons-material/VisibilityOff";
import { errorToString, patchUser } from "./pages/adminpages/userAdminService";

const DISPLAY_LOGO_SRC = "/brand/planiq-display/planiq-display-logo-on-dark.png";

const PASSWORD_MIN_LENGTH = 12;
const PASSWORD_MAX_UTF8_BYTES = 72;
const PASSWORD_HELPER_TEXT =
  "Mindst 12 tegn.";
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

export default function ChangePassword() {
  const { me, logout } = useAuth();
  const navigate = useNavigate();

  const [currentPassword, setCurrentPassword] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [passwordRepeat, setPasswordRepeat] = React.useState("");
  const [showCurrentPassword, setShowCurrentPassword] = React.useState(false);
  const [showPassword, setShowPassword] = React.useState(false);
  const [showPasswordRepeat, setShowPasswordRepeat] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState(false);
  const [loading, setLoading] = React.useState(false);
  const [progress, setProgress] = React.useState(0);

  const isForcedChange = Boolean(me?.must_change_password || me?.mustChangePassword);

  React.useEffect(() => {
    if (!success) return undefined;
    setProgress(0);
    const timer = setInterval(() => {
      setProgress((p) => Math.min(p + 5, 100));
    }, 100);
    const timeout = setTimeout(() => {
      logout();
      navigate("/login", { replace: true });
    }, 2000);
    return () => {
      clearInterval(timer);
      clearTimeout(timeout);
    };
  }, [success, logout, navigate]);

  const handleCancel = () => {
    if (isForcedChange || loading || success) return;
    navigate(-1);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (!me?.id) {
      setError("Bruger er ikke indlæst endnu");
      return;
    }

    if (!isForcedChange && !currentPassword) {
      setError("Indtast din nuværende adgangskode");
      return;
    }

    if (password !== passwordRepeat) {
      setError("Adgangskoder matcher ikke");
      return;
    }

    if (!isValidPassword(password)) {
      setError(
        "Adgangskoden skal være mindst 12 tegn, må ikke indeholde linjeskift og må ikke være for almindelig."
      );
      return;
    }

    const body = {
      password,
    };

    if (!isForcedChange) {
      body.current_password = currentPassword;
    }

    setLoading(true);
    try {
      await patchUser(me.id, body);
      setSuccess(true);
    } catch (err) {
      setError(errorToString(err) || "Kunne ikke skifte adgangskode");
    } finally {
      setLoading(false);
    }
  };

  if (!me) {
    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background:
          "radial-gradient(circle at 16% 12%, rgba(56,189,248,0.18), transparent 34%), radial-gradient(circle at 82% 16%, rgba(20,184,166,0.13), transparent 30%), linear-gradient(135deg, #020617 0%, #07111f 45%, #0f172a 100%)",
        }}
      >
        <CircularProgress />
      </Box>
    );
  }

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
          Skift adgangskode
        </Typography>

        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Brugernavn: {me.username}
        </Typography>

        <Typography
          variant="body2"
          sx={{
            color: "text.secondary",
            mb: 2
          }}>
          {isForcedChange
            ? "Du skal vælge en ny personlig adgangskode, før du kan fortsætte."
            : "Indtast din nuværende adgangskode og vælg en ny adgangskode."}
        </Typography>

        <form onSubmit={handleSubmit} autoComplete="on">
          {!isForcedChange && (
            <TextField
              label="Nuværende adgangskode"
              name="currentPassword"
              type={showCurrentPassword ? "text" : "password"}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              fullWidth
              margin="normal"
              required
              autoFocus
              autoComplete="current-password"
              slotProps={{
                input: {
                  endAdornment: (
                    <InputAdornment position="end">
                      <IconButton
                        aria-label={
                          showCurrentPassword ? "Skjul adgangskode" : "Vis adgangskode"
                        }
                        onClick={() => setShowCurrentPassword((s) => !s)}
                        edge="end"
                      >
                        {showCurrentPassword ? <VisibilityOff /> : <Visibility />}
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
          )}

          <TextField
            label="Ny adgangskode"
            name="newPassword"
            type={showPassword ? "text" : "password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            fullWidth
            margin="normal"
            required
            autoFocus={isForcedChange}
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

              inputLabel: { shrink: true }
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
              <Alert severity="success">
                Adgangskode skiftet. Du bliver logget ud og skal logge ind igen.
              </Alert>
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
            disabled={loading || success}
          >
            {loading ? "Skifter..." : "Skift adgangskode"}
          </Button>

          {!isForcedChange && (
            <Button
              type="button"
              variant="text"
              fullWidth
              sx={{ mt: 1 }}
              onClick={handleCancel}
              disabled={loading || success}
            >
              Annuller
            </Button>
          )}
        </form>
      </Paper>
    </Box>
  );
}
