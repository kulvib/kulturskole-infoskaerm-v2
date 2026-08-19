import React from "react";
import { useParams } from "react-router-dom";
import { Box, CircularProgress, Container, Stack, Typography } from "@mui/material";
import { getClient, getOrganizations } from "../../../api";
import ClientTerminalDialog from "./ClientTerminalDialog";

export default function ClientTerminalPage() {
  const { clientId } = useParams();
  const [client, setClient] = React.useState(null);
  const [organizations, setOrganizations] = React.useState([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let cancelled = false;

    async function loadClient() {
      if (!clientId) return;
      setLoading(true);
      setError("");
      try {
        const [data, orgs] = await Promise.all([
          getClient(clientId),
          getOrganizations().catch(() => []),
        ]);
        if (!cancelled) {
          setClient(data || { id: clientId });
          setOrganizations(Array.isArray(orgs) ? orgs : []);
        }
      } catch (err) {
        if (!cancelled) {
          setClient({ id: clientId });
          setError(err?.message || "Kunne ikke hente klientdata. Terminalen forsøger stadig at forbinde.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    loadClient();
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  const handleClose = React.useCallback(() => {
    if (window.opener) {
      window.close();
      return;
    }
    window.history.back();
  }, []);

  if (loading && !client) {
    return (
      <Container
        maxWidth={false}
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          bgcolor: "#020617",
          color: "#f8fafc",
        }}
      >
        <Stack spacing={2} sx={{
          alignItems: "center"
        }}>
          <CircularProgress color="inherit" />
          <Typography>Henter klientdata…</Typography>
        </Stack>
      </Container>
    );
  }

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "#020617", color: "#f8fafc" }}>
      {error && (
        <Typography variant="caption" sx={{ position: "fixed", left: 16, bottom: 10, zIndex: 1400, color: "rgba(248,250,252,0.55)" }}>
          {error}
        </Typography>
      )}
      <ClientTerminalDialog
        open
        onClose={handleClose}
        client={client || { id: clientId }}
        defaultFullscreen
        organizations={organizations}
      />
    </Box>
  );
}
