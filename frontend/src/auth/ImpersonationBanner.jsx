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
  const actorRole = getRoleLabel(viewModel?.actor_role) || "administrator";
  const stopLabel = `Tilbage til ${actorRole}`;

  return (
    <Box
      sx={{
        position: "absolute",
        top: "100%",
        right: { xs: 8, sm: 16, md: 24 },
        zIndex: 2,
        pointerEvents: "none",
        maxWidth: { xs: "calc(100vw - 16px)", sm: "calc(100vw - 32px)", md: "calc(100vw - 48px)" },
      }}
    >
      <Slide
        direction="down"
        in={active}
        mountOnEnter
        unmountOnExit
        appear
        timeout={{ enter: 260, exit: 220 }}
        onExited={() => setSnapshot(null)}
      >
        <Box
          role="status"
          aria-label="Aktiv bruger-session"
          sx={{
            pointerEvents: "auto",
            display: "flex",
            alignItems: "center",
            width: { xs: "calc(100vw - 16px)", sm: "auto" },
            minWidth: { sm: 350 },
            maxWidth: { sm: 520 },
            minHeight: { xs: 52, sm: 56 },
            borderRadius: "0 0 14px 14px",
            px: { xs: 1.25, sm: 1.5 },
            py: 0.625,
            color: "#111827",
            bgcolor: "warning.light",
            boxShadow: "0 7px 16px rgba(15, 23, 42, 0.20)",
          }}
        >
          <Stack direction="row" spacing={{ xs: 1, sm: 1.5 }} alignItems="center" sx={{ width: "100%", minWidth: 0 }}>
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Stack direction="row" spacing={0.75} alignItems="center" sx={{ minWidth: 0 }}>
                <Typography
                  sx={{
                    flexShrink: 0,
                    fontSize: 10.5,
                    fontWeight: 800,
                    letterSpacing: 0.3,
                    color: "#111827",
                    textTransform: "uppercase",
                    lineHeight: 1.2,
                  }}
                >
                  Aktiv bruger
                </Typography>
                <Typography noWrap sx={{ minWidth: 0, fontSize: 14, fontWeight: 800, lineHeight: 1.2, color: "#111827" }}>
                  {effectiveName}
                </Typography>
              </Stack>
              <Typography noWrap sx={{ fontSize: 12, color: "rgba(17,24,39,0.78)", lineHeight: 1.25, mt: 0.25 }}>
                {effectiveRole} · logget ind som {actorName}
              </Typography>
            </Box>
            <Button
              size="small"
              variant="contained"
              disableElevation
              aria-label={stopLabel}
              onClick={onStop}
              disabled={stopping}
              sx={{
                flexShrink: 0,
                minWidth: 0,
                px: { xs: 1.25, sm: 1.5 },
                textTransform: "none",
                fontWeight: 700,
                borderRadius: 999,
                whiteSpace: "nowrap",
                color: "common.white",
                borderColor: "#1f2937",
                bgcolor: "#1f2937",
                boxShadow: "0 1px 2px rgba(15, 23, 42, 0.18)",
                "&:hover": {
                  borderColor: "#111827",
                  bgcolor: "#111827",
                },
                "&:focus-visible": {
                  outline: "3px solid rgba(17,24,39,0.28)",
                  outlineOffset: 2,
                },
                "&.Mui-disabled": {
                  color: "rgba(255,255,255,0.82)",
                  borderColor: "rgba(31,41,55,0.45)",
                  bgcolor: "rgba(31,41,55,0.45)",
                },
              }}
            >
              {stopping ? (
                "Skifter tilbage…"
              ) : (
                <>
                  <Box component="span" sx={{ display: { xs: "inline", sm: "none" } }}>
                    Tilbage
                  </Box>
                  <Box component="span" sx={{ display: { xs: "none", sm: "inline" } }}>
                    {stopLabel}
                  </Box>
                </>
              )}
            </Button>
          </Stack>
        </Box>
      </Slide>
    </Box>
  );
}
