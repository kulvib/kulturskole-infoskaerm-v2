import * as React from "react";
import { Alert, AlertTitle, Button, Skeleton } from "@mui/material";
import { useNavigate } from "react-router-dom";
import { getSeasonReadiness } from "../api";
import { useSeasonClock } from "./SeasonProvider";

function useReadiness(organizationId, season, enabled, refreshKey) {
  const [state, setState] = React.useState({ loading: false, data: null, error: "" });

  React.useEffect(() => {
    if (!enabled || !organizationId || !season) {
      setState({ loading: false, data: null, error: "" });
      return undefined;
    }
    let active = true;
    setState({ loading: true, data: null, error: "" });
    getSeasonReadiness(organizationId, season)
      .then((data) => {
        if (active) setState({ loading: false, data, error: "" });
      })
      .catch((error) => {
        if (active) {
          setState({
            loading: false,
            data: null,
            error: error?.message || "Kunne ikke kontrollere sæsonen.",
          });
        }
      });
    return () => {
      active = false;
    };
  }, [enabled, organizationId, refreshKey, season]);

  return state;
}

function readinessMessage(data) {
  const parts = [];
  if (!data?.season_times_configured) parts.push("organisationens standardtider mangler");
  if (data?.missing_calendars) parts.push(`${data.missing_calendars} klientkalender${data.missing_calendars === 1 ? "" : "e"} mangler`);
  if (data?.incomplete_calendars) parts.push(`${data.incomplete_calendars} kalender${data.incomplete_calendars === 1 ? " er" : "e er"} ufuldstændig${data.incomplete_calendars === 1 ? "" : "e"}`);
  if (data?.missing_days) parts.push(`${data.missing_days} kalenderdag${data.missing_days === 1 ? "" : "e"} mangler samlet`);
  return parts.length ? `${parts.join(", ")}.` : "Sæsonen er ikke fuldt klargjort.";
}

export default function SeasonPreparationAlert({ organizationId, compact = false }) {
  const navigate = useNavigate();
  const { currentSeason, nextSeason, preparationWindow, serverTimeUtc } = useSeasonClock();
  const current = useReadiness(organizationId, currentSeason, Boolean(organizationId), serverTimeUtc);
  const next = useReadiness(
    organizationId,
    nextSeason,
    Boolean(organizationId) && preparationWindow,
    serverTimeUtc,
  );

  if (!organizationId) return null;
  if (current.loading || (preparationWindow && next.loading)) {
    return <Skeleton variant="rounded" height={compact ? 52 : 68} />;
  }

  const action = (
    <Button
      color="inherit"
      size="small"
      onClick={() => navigate("/administration?section=organisation")}
    >
      Åbn sæsontider
    </Button>
  );

  if (current.data && !current.data.is_ready) {
    return (
      <Alert severity="warning" action={action}>
        {!compact && <AlertTitle>Aktuel sæson kræver opmærksomhed</AlertTitle>}
        {currentSeason}: {readinessMessage(current.data)} Den automatiske sæsonvedligeholdelse ændrer ikke manuelle kalenderafvigelser.
      </Alert>
    );
  }

  if (preparationWindow && next.data && !next.data.is_ready) {
    return (
      <Alert severity="info" action={action}>
        {!compact && <AlertTitle>Næste sæson er ikke fuldt klargjort</AlertTitle>}
        {nextSeason}: {readinessMessage(next.data)} Systemet opretter normalt sæsonen automatisk; advarslen viser en konkret afvigelse, som bør rettes før 1. august.
      </Alert>
    );
  }

  return null;
}
