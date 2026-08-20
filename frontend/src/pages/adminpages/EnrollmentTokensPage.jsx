import AppSnackbar from "../../components/AppSnackbar";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Collapse,
  Divider,
  IconButton,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import AddCircleOutlinedIcon from "@mui/icons-material/AddCircleOutlined";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import RefreshIcon from "@mui/icons-material/Refresh";
import BlockIcon from "@mui/icons-material/Block";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import VpnKeyIcon from "@mui/icons-material/VpnKey";
import DevicesIcon from "@mui/icons-material/Devices";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import { useAuth } from "../../auth/AuthProvider";
import {
  createEnrollmentToken,
  getEnrollmentTokens,
  revokeEnrollmentToken,
} from "../../api";
import { buildFreshInstallDownloadCommand } from "../../utils/clientflowFreshInstall";
import { compactDarkChipSx } from "../../utils/chipStyles";
import { embeddedPageShellSx } from "../../utils/layoutStyles";

function formatDateTime(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("da-DK", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isExpired(token, nowMs = Date.now()) {
  if (token?.used_at || token?.revoked_at) return false;
  if (!token?.expires_at) return false;
  const d = new Date(token.expires_at);
  if (Number.isNaN(d.getTime())) return false;
  return d.getTime() < nowMs;
}

function getTokenStatus(token, nowMs = Date.now()) {
  if (token?.revoked_at || token?.is_revoked) {
    return { key: "revoked", label: "Tilbagekaldt", color: "default", icon: <BlockIcon fontSize="small" /> };
  }
  if (token?.used_at || token?.is_used) {
    return { key: "used", label: "Brugt", color: "success", icon: <CheckCircleIcon fontSize="small" /> };
  }
  if (token?.is_expired || isExpired(token, nowMs)) {
    return { key: "expired", label: "Udløbet", color: "warning", icon: null };
  }
  return { key: "active", label: "Aktiv", color: "primary", icon: <VpnKeyIcon fontSize="small" /> };
}

function getClientLabel(token) {
  const id = token?.used_by_client_id ?? token?.client_id ?? null;
  const name = token?.used_by_client_name || null;
  const locality = token?.used_by_client_locality || null;
  if (!id) return "Ikke tilknyttet klient";
  if (name && locality) return `${name} · ${locality} · ID ${id}`;
  if (name) return `${name} · ID ${id}`;
  if (locality) return `${locality} · ID ${id}`;
  return `Klient ID ${id}`;
}

function tokenSearchText(token) {
  return [
    token?.id,
    token?.note,
    token?.code_preview,
    token?.used_by_client_id,
    token?.used_by_client_name,
    token?.used_by_client_locality,
    token?.used_by_client_status,
    token?.created_at,
    token?.expires_at,
    token?.used_at,
  ].join(" ").toLowerCase();
}

function TokenRow({ token, nowMs, revokingId, onRevoke, canManage = true }) {
  const status = getTokenStatus(token, nowMs);
  const canRevoke = canManage && status.key === "active";
  const isUsed = status.key === "used";

  return (
    <Box
      sx={{
        p: 2,
        display: "grid",
        gap: 1.5,
        gridTemplateColumns: {
          xs: "1fr",
          lg: "150px minmax(220px, 1fr) minmax(220px, 1fr) 128px",
        },
        alignItems: "center",
        bgcolor: status.key === "active" ? "rgba(56,189,248,0.055)" : "rgba(34,197,94,0.05)",
      }}
    >
      <Stack spacing={0.75} sx={{ alignItems: "flex-start" }}>
        <Chip size="small" icon={status.icon} label={status.label} sx={compactDarkChipSx(status.color)} />
        <Typography variant="caption" sx={{ color: "text.secondary", fontWeight: 800 }}>
          ID {token.id}
        </Typography>
      </Stack>
      <Box sx={{ minWidth: 0 }}>
        <Typography sx={{ fontWeight: 850, overflow: "hidden", textOverflow: "ellipsis" }}>
          {token.note || "Ingen note"}
        </Typography>
        <Typography variant="body2" sx={{ color: "text.secondary" }}>
          Oprettet: {formatDateTime(token.created_at)}
        </Typography>
        {!isUsed && (
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            Udløber: {formatDateTime(token.expires_at)}
          </Typography>
        )}
      </Box>
      <Stack spacing={0.45} sx={{ minWidth: 0 }}>
        <Stack direction="row" spacing={0.75} sx={{ alignItems: "center" }}>
          <DevicesIcon sx={{ fontSize: 18, color: isUsed ? "success.light" : "text.secondary" }} />
          <Typography variant="caption" sx={{ color: "text.secondary", fontWeight: 900, textTransform: "uppercase" }}>
            Klient
          </Typography>
        </Stack>
        <Typography variant="body2" sx={{ fontWeight: 750 }}>
          {isUsed ? getClientLabel(token) : "Ikke brugt endnu"}
        </Typography>
        {isUsed && (
          <Typography variant="caption" sx={{ color: "text.secondary" }}>
            Brugt: {formatDateTime(token.used_at)}
            {token.used_by_client_status ? ` · Status: ${token.used_by_client_status}` : ""}
          </Typography>
        )}
      </Stack>
      <Box sx={{ display: "flex", justifyContent: { lg: "flex-end" } }}>
        <Tooltip title={canRevoke ? "Tilbagekald kode" : "Brugte koder kan ikke tilbagekaldes"}>
          <span>
            <Button
              size="small"
              color="error"
              variant="outlined"
              startIcon={<BlockIcon />}
              disabled={!canRevoke || revokingId === token.id}
              onClick={() => onRevoke(token)}
            >
              Tilbagekald
            </Button>
          </span>
        </Tooltip>
      </Box>
    </Box>
  );
}

function TokenSection({ title, count, emptyText, children, collapsible = false, expanded = true, onToggle }) {
  const content = count ? (
    <Stack divider={<Divider />}>{children}</Stack>
  ) : (
    <Box sx={{ p: 3 }}>
      <Typography sx={{ color: "text.secondary" }}>{emptyText}</Typography>
    </Box>
  );

  return (
    <Paper elevation={1} sx={{ borderRadius: 2, overflow: "hidden" }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={1}
        sx={{ alignItems: { xs: "stretch", sm: "center" }, justifyContent: "space-between", p: 2 }}
      >
        <Stack direction="row" spacing={1} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
          <Typography variant="h6" sx={{ fontWeight: 900 }}>{title}</Typography>
          {collapsible && (
            <Button
              size="small"
              variant={expanded ? "contained" : "outlined"}
              endIcon={
                <ExpandMoreIcon
                  sx={{
                    transition: "transform 160ms ease",
                    transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
                  }}
                />
              }
              onClick={onToggle}
            >
              {expanded ? "Skjul brugte koder" : "Vis brugte koder"}
            </Button>
          )}
        </Stack>
        <Chip label={`${count} stk.`} sx={compactDarkChipSx("neutral")} />
      </Stack>
      <Divider />
      {collapsible ? (
        <Collapse in={expanded} timeout="auto" unmountOnExit>
          {content}
        </Collapse>
      ) : content}
    </Paper>
  );
}

export default function EnrollmentTokensPage() {
  const { isSuperadmin, isViewer } = useAuth();
  const canManageTokens = isSuperadmin;

  const [tokens, setTokens] = useState([]);
  const [loading, setLoading] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [tokenSearch, setTokenSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [expiresInHours, setExpiresInHours] = useState("72");
  const [note, setNote] = useState("");

  const [newCode, setNewCode] = useState(null);
  const [revokeTarget, setRevokeTarget] = useState(null);
  const [usedTokensExpanded, setUsedTokensExpanded] = useState(false);

  const [snackbar, setSnackbar] = useState({ open: false, message: "", severity: "success" });

  const freshInstallCommand = useMemo(
    () => buildFreshInstallDownloadCommand(newCode),
    [newCode],
  );

  const showSnackbar = useCallback((message, severity = "success") => {
    setSnackbar({ open: true, message, severity });
  }, []);

  const closeSnackbar = useCallback((_event, reason) => {
    if (reason === "clickaway") return;
    setSnackbar((prev) => ({ ...prev, open: false }));
  }, []);

  const loadTokens = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getEnrollmentTokens();
      setTokens(Array.isArray(data) ? data : []);
    } catch (err) {
      showSnackbar(err?.message || "Kunne ikke hente installationskoder", "error");
    } finally {
      setLoading(false);
    }
  }, [showSnackbar]);

  useEffect(() => { loadTokens(); }, [loadTokens]);
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);

  const visibleTokens = useMemo(() => {
    const needle = tokenSearch.trim().toLowerCase();
    return tokens
      .filter((token) => {
        const key = getTokenStatus(token, nowMs).key;
        if (key !== "active" && key !== "used") return false;
        if (!needle) return true;
        return tokenSearchText(token).includes(needle);
      })
      .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());
  }, [tokens, tokenSearch, nowMs]);

  const activeTokens = useMemo(
    () => visibleTokens.filter((token) => getTokenStatus(token, nowMs).key === "active"),
    [visibleTokens, nowMs],
  );
  const usedTokens = useMemo(
    () => visibleTokens.filter((token) => getTokenStatus(token, nowMs).key === "used"),
    [visibleTokens, nowMs],
  );

  const handleCopy = useCallback(async (text) => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showSnackbar("Kopieret til udklipsholder");
    } catch {
      showSnackbar("Kunne ikke kopiere automatisk. Markér og kopier manuelt.", "warning");
    }
  }, [showSnackbar]);

  const handleCreate = useCallback(async () => {
    const hours = Number.parseInt(expiresInHours, 10);
    if (!Number.isFinite(hours) || hours < 1 || hours > 720) {
      showSnackbar("Udløb skal være mellem 1 og 720 timer", "warning");
      return;
    }

    setCreating(true);
    try {
      const created = await createEnrollmentToken({
        expires_in_hours: hours,
        note: note.trim() || null,
      });
      setNewCode(created);
      setCreateOpen(false);
      setExpiresInHours("72");
      setNote("");
      setNowMs(Date.now());
      showSnackbar("Installationskode oprettet og bundet til godkendt ClientFlow-release");
      await loadTokens();
    } catch (err) {
      showSnackbar(err?.message || "Kunne ikke oprette installationskode", "error");
    } finally {
      setCreating(false);
    }
  }, [expiresInHours, note, loadTokens, showSnackbar]);

  const handleRevoke = useCallback(async () => {
    if (!revokeTarget?.id) return;
    setRevokingId(revokeTarget.id);
    try {
      await revokeEnrollmentToken(revokeTarget.id);
      setNowMs(Date.now());
      showSnackbar("Installationskode tilbagekaldt");
      setRevokeTarget(null);
      await loadTokens();
    } catch (err) {
      showSnackbar(err?.message || "Kunne ikke tilbagekalde installationskode", "error");
    } finally {
      setRevokingId(null);
    }
  }, [revokeTarget, loadTokens, showSnackbar]);

  if (!isSuperadmin && !isViewer) {
    return (
      <Box sx={embeddedPageShellSx}>
        <Alert severity="error">Kun superadministratorer og Se adgang kan se installationskoder.</Alert>
      </Box>
    );
  }

  return (
    <Box sx={embeddedPageShellSx}>
      <Stack spacing={2}>
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={1.5}
          sx={{ alignItems: { xs: "stretch", md: "center" } }}
        >
          <Box sx={{ flex: 1 }}>
            <Typography variant="h4" sx={{ fontWeight: 900 }}>Installationskoder</Typography>
          </Box>

          <TextField
            size="small"
            label="Søg"
            placeholder="Note, ID eller klient"
            value={tokenSearch}
            onChange={(event) => setTokenSearch(event.target.value)}
            sx={{ minWidth: { md: 280 } }}
          />

          <Button
            variant="outlined"
            startIcon={<RefreshIcon />}
            loading={loading}
            loadingPosition="start"
            onClick={loadTokens}
            disabled={loading}
          >
            Opdater
          </Button>

          {canManageTokens && (
            <Button variant="contained" startIcon={<AddCircleOutlinedIcon />} onClick={() => setCreateOpen(true)}>
              Opret kode
            </Button>
          )}
        </Stack>

        <TokenSection title="Aktive koder" count={activeTokens.length} emptyText="Ingen aktive installationskoder.">
          {activeTokens.map((token) => (
            <TokenRow
              key={token.id}
              token={token}
              nowMs={nowMs}
              revokingId={revokingId}
              onRevoke={setRevokeTarget}
              canManage={canManageTokens}
            />
          ))}
        </TokenSection>

        <TokenSection
          title="Brugte koder"
          count={usedTokens.length}
          emptyText="Ingen brugte installationskoder."
          collapsible
          expanded={usedTokensExpanded}
          onToggle={() => setUsedTokensExpanded((value) => !value)}
        >
          {usedTokens.map((token) => (
            <TokenRow
              key={token.id}
              token={token}
              nowMs={nowMs}
              revokingId={revokingId}
              onRevoke={setRevokeTarget}
              canManage={canManageTokens}
            />
          ))}
        </TokenSection>
      </Stack>

      <Dialog open={createOpen} onClose={() => !creating && setCreateOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Opret installationskode</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <DialogContentText>
              Koden kan bruges én gang af en ny Ubuntu-klient. Oprettelsen kræver, at den canonical fresh-install release allerede er publiceret og verificeret i 51M artifact store.
            </DialogContentText>
            <TextField
              label="Udløb i timer"
              value={expiresInHours}
              onChange={(e) => setExpiresInHours(e.target.value)}
              type="number"
              fullWidth
              slotProps={{ htmlInput: { min: 1, max: 720 } }}
            />
            <TextField
              label="Note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Fx Kunde X - foyer"
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateOpen(false)} disabled={creating}>Annuller</Button>
          <Button onClick={handleCreate} variant="contained" disabled={creating} loading={creating}>
            Opret kode
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!newCode} onClose={() => setNewCode(null)} maxWidth="md" fullWidth>
        <DialogTitle>Canonical fresh-install handoff oprettet</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            Den fulde installationskode og den signerede fresh-install authorization vises kun i dette svar. Kopiér handoff-blokken nu og opbevar den sikkert.
          </Alert>

          <Paper variant="outlined" sx={{ p: 2, bgcolor: "rgba(15,23,42,0.42)", display: "flex", alignItems: "center", gap: 1 }}>
            <Typography
              sx={{
                flex: 1,
                fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                fontWeight: 900,
                fontSize: { xs: "1rem", md: "1.25rem" },
                wordBreak: "break-all",
              }}
            >
              {newCode?.code}
            </Typography>
            <IconButton onClick={() => handleCopy(newCode?.code)}>
              <ContentCopyIcon />
            </IconButton>
          </Paper>

          <Stack spacing={0.6} sx={{ mt: 2 }}>
            <Typography variant="body2"><strong>Release:</strong> {newCode?.release_id || "-"}</Typography>
            <Typography variant="body2" sx={{ wordBreak: "break-all" }}><strong>Approved bundle SHA-256:</strong> {newCode?.bundle_sha256 || "-"}</Typography>
            <Typography variant="body2"><strong>Approval:</strong> {newCode?.release_approval_reference || "-"}</Typography>
            <Typography variant="body2" sx={{ wordBreak: "break-all" }}><strong>Source commit:</strong> {newCode?.source_commit || "-"}</Typography>
            <Typography variant="body2" sx={{ color: "text.secondary" }}>Udløber: {formatDateTime(newCode?.expires_at)}</Typography>
          </Stack>

          <Typography variant="subtitle2" sx={{ mt: 2.5, mb: 1, fontWeight: 900 }}>
            Ubuntu: download og verificér exact approved bundle
          </Typography>
          <Paper
            component="pre"
            variant="outlined"
            sx={{
              p: 2,
              m: 0,
              maxHeight: 360,
              overflow: "auto",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
              fontSize: "0.78rem",
              bgcolor: "rgba(15,23,42,0.42)",
            }}
          >
            {freshInstallCommand}
          </Paper>
          <Alert severity="info" sx={{ mt: 2 }}>
            Blokken downloader kun de bytes, som den signerede authorization peger på, og verificerer hele bundle-SHA-256. Derefter fortsættes den eksisterende 51I-procedure fra <code>CLIENTFLOW_RELEASE_PROCEDURE.md</code> afsnit 4. Kiosk-bruger og manuel aktivering gættes eller udføres ikke automatisk.
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => handleCopy(newCode?.code)} startIcon={<ContentCopyIcon />}>Kopiér kode</Button>
          <Button onClick={() => handleCopy(freshInstallCommand)} startIcon={<ContentCopyIcon />} disabled={!freshInstallCommand}>
            Kopiér handoff
          </Button>
          <Button variant="contained" onClick={() => setNewCode(null)}>Luk</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={!!revokeTarget} onClose={() => setRevokeTarget(null)}>
        <DialogTitle>Tilbagekald installationskode?</DialogTitle>
        <DialogContent>
          <DialogContentText>Koden kan ikke længere bruges til installation, når den er tilbagekaldt.</DialogContentText>
          {revokeTarget?.note && <Typography sx={{ mt: 2, fontWeight: 800 }}>{revokeTarget.note}</Typography>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRevokeTarget(null)} disabled={!!revokingId}>Annuller</Button>
          <Button color="error" variant="contained" onClick={handleRevoke} disabled={!!revokingId}>Tilbagekald</Button>
        </DialogActions>
      </Dialog>

      <AppSnackbar
        open={snackbar.open}
        message={snackbar.message}
        severity={snackbar.severity}
        onClose={closeSnackbar}
      />
    </Box>
  );
}
