import * as React from "react";
import {
  Alert,
  Box,
  Button,
  Paper,
  TextField,
  Typography,
} from "@mui/material";
import { Link as RouterLink } from "react-router-dom";
import { apiUrl } from "./api";
import { formatApiError } from "./api/apiError";

const DISPLAY_LOGO_SRC = "/brand/planiq-display/planiq-display-logo-on-dark.png";

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

export default function ForgotPassword() {
  const [email, setEmail] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const [success, setSuccess] = React.useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setSuccess("");

    const identifier = email.trim();
    if (!identifier) {
      setError("Indtast din e-mailadresse.");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${apiUrl}/api/users/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ identifier }),
      });
      const data = await readResponseBody(res);
      if (!res.ok) {
        throw new Error(getErrorMessage(data, "Kunne ikke sende nulstillingslink."));
      }
      setSuccess(data?.detail || "Hvis kontoen findes, sender vi en mail med et link til nulstilling af adgangskoden.");
    } catch (err) {
      setError(formatApiError(err, "Kunne ikke sende nulstillingslink."));
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
          Glemt adgangskode
        </Typography>

        <Typography
          variant="body2"
          sx={{
            color: "text.secondary",
            mb: 2,
            fontSize: "0.875rem"
          }}>
          Indtast din e-mailadresse. Hvis kontoen findes, sender vi
          et link, hvor du kan vælge en ny adgangskode.
        </Typography>

        <form onSubmit={handleSubmit} autoComplete="on">
          <TextField
            label="E-mail"
            name="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            fullWidth
            margin="normal"
            required
            autoFocus
            autoComplete="email"
            slotProps={{
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
            <Alert severity="success" sx={{ mt: 2 }}>
              {success}
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
            Send nulstillingslink
          </Button>
        </form>

        <Button
          component={RouterLink}
          to="/login"
          type="button"
          variant="text"
          fullWidth
          sx={{ mt: 1, fontSize: "0.8125rem", textTransform: "none" }}
          disabled={loading}
        >
          Tilbage til login
        </Button>
      </Paper>
    </Box>
  );
}
