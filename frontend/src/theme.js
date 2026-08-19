import { createTheme } from "@mui/material/styles";

const colors = {
  bg: "#020617",
  bg2: "#07111f",
  surface: "rgba(15, 23, 42, 0.88)",
  surfaceSoft: "rgba(15, 23, 42, 0.64)",
  border: "rgba(148, 163, 184, 0.18)",
  borderStrong: "rgba(148, 163, 184, 0.28)",
  text: "#f8fafc",
  muted: "rgba(203, 213, 225, 0.72)",
  cyan: "#38bdf8",
  cyanDark: "#0284c7",
  green: "#22c55e",
  amber: "#f59e0b",
  red: "#ef4444",
};

const glassShadow = "0 24px 80px rgba(0,0,0,0.32), inset 0 1px 0 rgba(255,255,255,0.05)";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: colors.cyan,
      dark: colors.cyanDark,
      light: "#7dd3fc",
      contrastText: "#020617",
    },
    secondary: {
      main: "#14b8a6",
      dark: "#0f766e",
      light: "#5eead4",
      contrastText: "#020617",
    },
    success: {
      main: colors.green,
      dark: "#15803d",
      light: "#86efac",
      contrastText: "#020617",
    },
    warning: {
      main: colors.amber,
      dark: "#b45309",
      light: "#fcd34d",
      contrastText: "#020617",
    },
    error: {
      main: colors.red,
      dark: "#b91c1c",
      light: "#fca5a5",
      contrastText: "#ffffff",
    },
    info: {
      main: colors.cyan,
      dark: colors.cyanDark,
      light: "#7dd3fc",
      contrastText: "#020617",
    },
    background: {
      default: colors.bg,
      paper: colors.surface,
    },
    text: {
      primary: colors.text,
      secondary: colors.muted,
    },
    divider: colors.border,
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica Neue", "Arial", sans-serif',
    h4: { fontWeight: 900, letterSpacing: -0.8 },
    h5: { fontWeight: 900, letterSpacing: -0.55 },
    h6: { fontWeight: 850, letterSpacing: -0.25 },
    subtitle1: { fontWeight: 750 },
    subtitle2: { fontWeight: 850 },
    button: { textTransform: "none", fontWeight: 800 },
    overline: { fontWeight: 900, letterSpacing: 1.1 },
  },
  shape: {
    // Fælles sektion-radius: matcher ClientInfoPage.jsx (borderRadius: 2 / ca. 10 px).
    borderRadius: 10,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          minHeight: "100vh",
          color: colors.text,
          background:
            "radial-gradient(circle at 15% 0%, rgba(56,189,248,0.16), transparent 34%), radial-gradient(circle at 92% 4%, rgba(34,197,94,0.10), transparent 28%), linear-gradient(135deg, #020617 0%, #07111f 45%, #0f172a 100%)",
          scrollbarColor: "rgba(148,163,184,0.45) rgba(15,23,42,0.6)",
        },
        "#root": {
          minHeight: "100vh",
        },
        "*::-webkit-scrollbar": {
          width: 10,
          height: 10,
        },
        "*::-webkit-scrollbar-track": {
          background: "rgba(15,23,42,0.65)",
        },
        "*::-webkit-scrollbar-thumb": {
          background: "rgba(148,163,184,0.42)",
          borderRadius: 999,
          border: "2px solid rgba(15,23,42,0.65)",
        },
        "*::-webkit-scrollbar-thumb:hover": {
          background: "rgba(203,213,225,0.55)",
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: "linear-gradient(90deg, rgba(2,6,23,0.96), rgba(15,23,42,0.92))",
          color: colors.text,
          borderBottom: `1px solid ${colors.border}`,
          boxShadow: "0 18px 50px rgba(0,0,0,0.26)",
          backdropFilter: "blur(18px)",
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          background: "linear-gradient(180deg, rgba(2,6,23,0.98), rgba(15,23,42,0.94))",
          color: colors.text,
          borderRight: `1px solid ${colors.border}`,
          boxShadow: "18px 0 60px rgba(0,0,0,0.28)",
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          backgroundColor: colors.surface,
          color: colors.text,
          border: `1px solid ${colors.border}`,
        },
        rounded: {
          borderRadius: 10,
        },
        elevation1: { boxShadow: glassShadow },
        elevation2: { boxShadow: glassShadow },
        elevation3: { boxShadow: glassShadow },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          background: "linear-gradient(180deg, rgba(15,23,42,0.88), rgba(15,23,42,0.68))",
          color: colors.text,
          border: `1px solid ${colors.border}`,
          borderRadius: 10,
          boxShadow: glassShadow,
          backgroundImage: "none",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: "none",
          fontWeight: 850,
          borderRadius: 10,
          boxShadow: "none",
        },
        contained: {
          boxShadow: "0 14px 32px rgba(0,0,0,0.24)",
        },
        outlined: {
          borderColor: colors.borderStrong,
          color: colors.text,
          backgroundColor: "rgba(15,23,42,0.28)",
        },
        text: {
          color: colors.text,
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          color: colors.text,
        },
      },
    },
    MuiDialog: {
      styleOverrides: {
        paper: {
          background: "linear-gradient(180deg, rgba(15,23,42,0.98), rgba(2,6,23,0.96))",
          color: colors.text,
          border: `1px solid ${colors.borderStrong}`,
          borderRadius: 12,
          boxShadow: "0 32px 110px rgba(0,0,0,0.56)",
          backgroundImage: "none",
        },
      },
    },
    MuiBackdrop: {
      styleOverrides: {
        root: {
          backgroundColor: "rgba(2,6,23,0.74)",
          backdropFilter: "blur(8px)",
        },
      },
    },
    MuiDialogTitle: {
      styleOverrides: {
        root: {
          color: colors.text,
          fontWeight: 900,
          letterSpacing: -0.2,
          padding: "22px 24px 10px",
        },
      },
    },
    MuiDialogContent: {
      styleOverrides: {
        root: {
          color: colors.muted,
          padding: "10px 24px 16px",
        },
      },
    },
    MuiDialogActions: {
      styleOverrides: {
        root: {
          padding: "14px 24px 22px",
          borderTop: `1px solid ${colors.border}`,
          gap: 8,
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          border: `1px solid ${colors.border}`,
          backgroundColor: "rgba(15,23,42,0.88)",
          color: colors.text,
          boxShadow: "0 18px 48px rgba(0,0,0,0.24)",
          alignItems: "center",
        },
        standardSuccess: {
          backgroundColor: "rgba(34,197,94,0.12)",
          color: "#bbf7d0",
          borderColor: "rgba(34,197,94,0.30)",
        },
        standardInfo: {
          backgroundColor: "rgba(56,189,248,0.12)",
          color: "#bae6fd",
          borderColor: "rgba(56,189,248,0.30)",
        },
        standardWarning: {
          backgroundColor: "rgba(245,158,11,0.13)",
          color: "#fde68a",
          borderColor: "rgba(245,158,11,0.32)",
        },
        standardError: {
          backgroundColor: "rgba(239,68,68,0.14)",
          color: "#fecaca",
          borderColor: "rgba(239,68,68,0.34)",
        },
        filledSuccess: {
          backgroundColor: colors.green,
          color: "#052e16",
          borderColor: "rgba(34,197,94,0.72)",
          "& .MuiAlert-icon": { color: "#052e16" },
          "& .MuiAlert-action": { color: "#052e16" },
        },
        filledInfo: {
          backgroundColor: colors.cyan,
          color: "#082f49",
          borderColor: "rgba(56,189,248,0.72)",
          "& .MuiAlert-icon": { color: "#082f49" },
          "& .MuiAlert-action": { color: "#082f49" },
        },
        filledWarning: {
          backgroundColor: colors.amber,
          color: "#451a03",
          borderColor: "rgba(245,158,11,0.72)",
          "& .MuiAlert-icon": { color: "#451a03" },
          "& .MuiAlert-action": { color: "#451a03" },
        },
        filledError: {
          backgroundColor: colors.red,
          color: "#ffffff",
          borderColor: "rgba(239,68,68,0.72)",
          "& .MuiAlert-icon": { color: "#ffffff" },
          "& .MuiAlert-action": { color: "#ffffff" },
        },
        message: {
          fontWeight: 650,
        },
      },
    },
    MuiSnackbarContent: {
      styleOverrides: {
        root: {
          background: "rgba(15,23,42,0.96)",
          color: colors.text,
          border: `1px solid ${colors.borderStrong}`,
          borderRadius: 10,
          boxShadow: "0 24px 80px rgba(0,0,0,0.42)",
        },
      },
    },
    MuiTabs: {
      styleOverrides: {
        root: {
          minHeight: 46,
        },
        indicator: {
          height: 3,
          borderRadius: 999,
          backgroundColor: colors.cyan,
        },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          minHeight: 46,
          textTransform: "none",
          fontWeight: 850,
          color: colors.muted,
          "&.Mui-selected": {
            color: colors.text,
          },
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          backgroundColor: "rgba(15,23,42,0.54)",
          color: colors.text,
          "& fieldset": {
            borderColor: colors.borderStrong,
          },
          "&:hover fieldset": {
            borderColor: "rgba(56,189,248,0.46)",
          },
          "&.Mui-focused fieldset": {
            borderColor: colors.cyan,
            borderWidth: 1,
          },
        },
        input: {
          color: colors.text,
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: {
        root: {
          color: colors.muted,
          "&.Mui-focused": {
            color: colors.cyan,
          },
        },
      },
    },
    MuiFormHelperText: {
      styleOverrides: {
        root: {
          color: colors.muted,
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 999,
          fontWeight: 850,
          border: "1px solid rgba(148,163,184,0.18)",
          backgroundColor: "rgba(15,23,42,0.56)",
          color: "rgba(226,232,240,0.86)",
          "& .MuiChip-icon, & .MuiChip-deleteIcon": {
            color: "inherit",
          },
          "&.MuiChip-colorPrimary, &.MuiChip-colorInfo": {
            backgroundColor: "rgba(56,189,248,0.13)",
            color: "#bae6fd",
            borderColor: "rgba(56,189,248,0.30)",
          },
          "&.MuiChip-colorSecondary": {
            backgroundColor: "rgba(20,184,166,0.13)",
            color: "#99f6e4",
            borderColor: "rgba(20,184,166,0.30)",
          },
          "&.MuiChip-colorSuccess": {
            backgroundColor: "rgba(34,197,94,0.13)",
            color: "#bbf7d0",
            borderColor: "rgba(34,197,94,0.30)",
          },
          "&.MuiChip-colorWarning": {
            backgroundColor: "rgba(245,158,11,0.14)",
            color: "#fde68a",
            borderColor: "rgba(245,158,11,0.34)",
          },
          "&.MuiChip-colorError": {
            backgroundColor: "rgba(239,68,68,0.14)",
            color: "#fecaca",
            borderColor: "rgba(239,68,68,0.34)",
          },
          "&.MuiChip-outlined": {
            backgroundColor: "rgba(15,23,42,0.34)",
            borderColor: "rgba(148,163,184,0.24)",
            color: "rgba(226,232,240,0.88)",
          },
          "&.MuiChip-outlined.MuiChip-colorPrimary, &.MuiChip-outlined.MuiChip-colorInfo": {
            backgroundColor: "rgba(56,189,248,0.08)",
            color: "#bae6fd",
            borderColor: "rgba(56,189,248,0.30)",
          },
          "&.MuiChip-outlined.MuiChip-colorSuccess": {
            backgroundColor: "rgba(34,197,94,0.08)",
            color: "#bbf7d0",
            borderColor: "rgba(34,197,94,0.30)",
          },
          "&.MuiChip-outlined.MuiChip-colorWarning": {
            backgroundColor: "rgba(245,158,11,0.09)",
            color: "#fde68a",
            borderColor: "rgba(245,158,11,0.34)",
          },
          "&.MuiChip-outlined.MuiChip-colorError": {
            backgroundColor: "rgba(239,68,68,0.09)",
            color: "#fecaca",
            borderColor: "rgba(239,68,68,0.34)",
          },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        root: {
          color: colors.text,
          borderColor: colors.border,
        },
        head: {
          fontWeight: 850,
          color: colors.text,
          backgroundColor: "rgba(15,23,42,0.88)",
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: colors.border,
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: "rgba(2,6,23,0.96)",
          color: colors.text,
          border: `1px solid ${colors.borderStrong}`,
          borderRadius: 10,
          boxShadow: "0 16px 50px rgba(0,0,0,0.35)",
          fontWeight: 650,
        },
        arrow: {
          color: "rgba(2,6,23,0.96)",
        },
      },
    },
    MuiMenu: {
      styleOverrides: {
        paper: {
          background: "rgba(15,23,42,0.98)",
          border: `1px solid ${colors.borderStrong}`,
          borderRadius: 10,
          boxShadow: "0 24px 80px rgba(0,0,0,0.42)",
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          color: colors.muted,
          "&.Mui-selected": {
            color: colors.text,
            backgroundColor: "rgba(56,189,248,0.14)",
          },
          "&.Mui-selected:hover": {
            backgroundColor: "rgba(56,189,248,0.20)",
          },
        },
      },
    },
  },
});

export default theme;
