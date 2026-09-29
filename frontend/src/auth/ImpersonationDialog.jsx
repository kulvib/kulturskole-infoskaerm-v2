import * as React from "react";
import {
  Alert,
  Autocomplete,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { getRoleLabel } from "../utils/roleUtils";

function candidateLabel(candidate) {
  const name = candidate?.full_name || candidate?.username || "Bruger";
  const role = getRoleLabel(candidate?.role);
  const organization = candidate?.organization_name || "Ingen organisation";
  return `${name} · ${role} · ${organization}`;
}

function organizationLabel(option) {
  return option?.organization_name || "Ingen organisation";
}

export default function ImpersonationDialog({ open, onClose, loadCandidates, onStart, actorRole }) {
  const [candidates, setCandidates] = React.useState([]);
  const [selected, setSelected] = React.useState(null);
  const [selectedOrganization, setSelectedOrganization] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState("");
  const requiresOrganizationSelection = actorRole === "superadmin";

  React.useEffect(() => {
    if (!open) return undefined;
    const controller = new AbortController();
    setSelected(null);
    setSelectedOrganization(null);
    setError("");
    setLoading(true);
    Promise.resolve(loadCandidates(controller.signal))
      .then((rows) => setCandidates(Array.isArray(rows) ? rows : []))
      .catch((loadError) => {
        if (loadError?.name !== "AbortError") {
          setCandidates([]);
          setError(loadError?.message || "Kunne ikke hente brugere");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [loadCandidates, open]);

  const organizationOptions = React.useMemo(() => {
    const unique = new Map();
    for (const candidate of candidates) {
      const key = candidate.organization_id == null ? "none" : String(candidate.organization_id);
      if (!unique.has(key)) {
        unique.set(key, {
          key,
          organization_id: candidate.organization_id ?? null,
          organization_name: candidate.organization_name || "Ingen organisation",
        });
      }
    }
    return [...unique.values()].sort((a, b) => organizationLabel(a).localeCompare(organizationLabel(b), "da"));
  }, [candidates]);

  const filteredCandidates = React.useMemo(() => {
    if (!requiresOrganizationSelection) return candidates;
    if (!selectedOrganization) return [];
    return candidates.filter(
      (candidate) => (candidate.organization_id ?? null) === (selectedOrganization.organization_id ?? null),
    );
  }, [candidates, requiresOrganizationSelection, selectedOrganization]);

  const handleStart = async () => {
    if (!selected || selected.must_change_password === true || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await onStart(selected.id);
      onClose();
    } catch (startError) {
      setError(startError?.message || "Kunne ikke skifte bruger");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={submitting ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>Skift bruger</DialogTitle>
      <DialogContent>
        <Typography sx={{ mb: 2, color: "text.secondary" }}>
          Du får den valgte brugers rettigheder og dataadgang. Din administrator-identitet
          bevares server-side, og bruger-skiftet registreres i auditloggen.
        </Typography>
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          {requiresOrganizationSelection && (
            <Autocomplete
              options={organizationOptions}
              value={selectedOrganization}
              onChange={(_, value) => {
                setSelectedOrganization(value);
                setSelected(null);
              }}
              getOptionLabel={organizationLabel}
              isOptionEqualToValue={(option, value) => option.key === value.key}
              loading={loading}
              disabled={loading || submitting}
              noOptionsText={loading ? "Henter organisationer…" : "Ingen organisationer kan vælges"}
              renderInput={(params) => <TextField {...params} label="Vælg organisation" />}
            />
          )}
          <Autocomplete
            options={filteredCandidates}
            value={selected}
            onChange={(_, value) => setSelected(value)}
            getOptionLabel={candidateLabel}
            isOptionEqualToValue={(option, value) => option.id === value.id}
            getOptionDisabled={(option) => option.must_change_password === true}
            loading={loading}
            disabled={loading || submitting || (requiresOrganizationSelection && !selectedOrganization)}
            noOptionsText={
              loading
                ? "Henter brugere…"
                : requiresOrganizationSelection && !selectedOrganization
                  ? "Vælg først en organisation"
                  : "Ingen brugere kan vælges"
            }
            renderOption={(props, option) => (
              <li {...props}>
                <Stack direction="row" spacing={1} alignItems="center" justifyContent="space-between" sx={{ width: "100%", minWidth: 0 }}>
                  <Typography variant="body2" noWrap sx={{ minWidth: 0 }}>{candidateLabel(option)}</Typography>
                  {option.must_change_password === true && (
                    <Chip label="Afventer første login" size="small" color="warning" variant="outlined" sx={{ flexShrink: 0, fontWeight: 700 }} />
                  )}
                </Stack>
              </li>
            )}
            renderInput={(params) => <TextField {...params} label="Vælg bruger" placeholder="Søg navn, rolle eller organisation" />}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={submitting}>Annuller</Button>
        <Button variant="contained" onClick={handleStart} disabled={!selected || selected?.must_change_password === true || loading || submitting}>
          {submitting ? "Skifter…" : "Skift bruger"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
