// Fælles sidebredde for PlanIQ Display.
// Best practice: én central content-container pr. top-level side, så papers flugter,
// indholdet er centreret, og responsive padding forhindrer horisontal scroll.
export const PAGE_CONTENT_MAX_WIDTH = 1680;

export const pageShellSx = {
  width: "100%",
  maxWidth: PAGE_CONTENT_MAX_WIDTH,
  mx: "auto",
  px: { xs: 1.5, sm: 2, lg: 3 },
  py: { xs: 2, md: 3 },
  boxSizing: "border-box",
};

// Bruges af undersider, der allerede ligger inde i en pageShell.
// Dermed undgår vi dobbelt padding og smallere papers i fx Administration.
export const embeddedPageShellSx = {
  width: "100%",
  maxWidth: "100%",
  mx: 0,
  px: 0,
  py: 0,
  boxSizing: "border-box",
};

export const darkPagePanelSx = {
  borderRadius: 2,
  background: "rgba(15,23,42,0.74)",
  border: "1px solid rgba(148,163,184,0.16)",
  boxShadow: "0 24px 80px rgba(0,0,0,0.22)",
  color: "#f8fafc",
};

export const darkPagePaperSx = {
  ...darkPagePanelSx,
  p: { xs: 1.5, md: 2 },
  mb: 2,
};

export const pageHeaderPaperSx = {
  ...darkPagePanelSx,
  p: { xs: 1.7, sm: 2.4 },
  mb: 2.2,
};

export const pageHeaderIconSx = {
  width: 46,
  height: 46,
  borderRadius: 2,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "#020617",
  background: "linear-gradient(135deg, #38bdf8, #14b8a6)",
  boxShadow: "0 0 0 8px rgba(56,189,248,0.08)",
  flex: "0 0 auto",
};
