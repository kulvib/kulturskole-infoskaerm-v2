import * as React from "react";
import { Box, Button, Slide, Stack, Typography } from "@mui/material";
import { getRoleLabel } from "../utils/roleUtils";

export default function ImpersonationBanner({ user, onStop, stopping = false }) {
  const active = user?.impersonation_active === true;
  const [snapshot, setSnapshot] = React.useState(active ? user : null);

  React.useEffect(() => {
    if (active) setSnapshot(user);
  }, [active, user]);

  const viewModel = active ? user : snapshot;
  if (!viewModel) return null;

  const effectiveName = viewModel?.full_name || viewModel?.username || "Bruger";
  const effectiveRole = getRoleLabel(viewModel?.role);
  const actorName = viewModel?.actor_full_name || viewModel?.actor_username || "administrator";

  return (
    <Box sx={{ position: "absolute", top: "100%", right: { xs: 8, sm: 16, md: 24 }, zIndex: 2, pointerEvents: "none", maxWidth: { xs: "calc(100vw - 16px)", sm: 520 } }}>
      <Slide direction="down" in={active} mountOnEnter unmountOnExit appear onExited={() => setSnapshot(null)}>
        <Box role="status" aria-label="Aktivt bruger-skift" sx={{ pointerEvents: "auto", display: "flex", alignItems: "center", minWidth: { sm: 360 }, maxWidth: 520, minHeight: 54, borderRadius: "0 0 14px 14px", px: 1.5, py: 0.75, color: "#111827", bgcolor: "warning.light", boxShadow: "0 7px 16px rgba(15, 23, 42, 0.20)" }}>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ width: "100%", minWidth: 0 }}>
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography noWrap sx={{ fontSize: 14, fontWeight: 800, lineHeight: 1.2 }}>
                Arbejder som {effectiveName}
              </Typography>
              <Typography noWrap sx={{ fontSize: 12, color: "rgba(17,24,39,0.78)", mt: 0.25 }}>
                {effectiveRole} · logget ind som {actorName}
              </Typography>
            </Box>
            <Button size="small" variant="contained" disableElevation onClick={onStop} disabled={stopping} sx={{ flexShrink: 0, textTransform: "none", fontWeight: 700, borderRadius: 999, bgcolor: "#1f2937", "&:hover": { bgcolor: "#111827" } }}>
              {stopping ? "Skifter tilbage…" : "Tilbage"}
            </Button>
          </Stack>
        </Box>
      </Slide>
    </Box>
  );
}
