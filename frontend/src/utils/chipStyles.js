export const darkChipTones = {
  default: {
    bgcolor: "rgba(148,163,184,0.12)",
    color: "rgba(226,232,240,0.88)",
    borderColor: "rgba(148,163,184,0.26)",
  },
  neutral: {
    bgcolor: "rgba(148,163,184,0.12)",
    color: "rgba(226,232,240,0.88)",
    borderColor: "rgba(148,163,184,0.26)",
  },
  primary: {
    bgcolor: "rgba(56,189,248,0.13)",
    color: "#bae6fd",
    borderColor: "rgba(56,189,248,0.30)",
  },
  info: {
    bgcolor: "rgba(56,189,248,0.13)",
    color: "#bae6fd",
    borderColor: "rgba(56,189,248,0.30)",
  },
  secondary: {
    bgcolor: "rgba(20,184,166,0.13)",
    color: "#99f6e4",
    borderColor: "rgba(20,184,166,0.30)",
  },
  success: {
    bgcolor: "rgba(34,197,94,0.13)",
    color: "#bbf7d0",
    borderColor: "rgba(34,197,94,0.30)",
  },
  warning: {
    bgcolor: "rgba(245,158,11,0.14)",
    color: "#fde68a",
    borderColor: "rgba(245,158,11,0.34)",
  },
  error: {
    bgcolor: "rgba(239,68,68,0.14)",
    color: "#fecaca",
    borderColor: "rgba(239,68,68,0.34)",
  },
  danger: {
    bgcolor: "rgba(239,68,68,0.14)",
    color: "#fecaca",
    borderColor: "rgba(239,68,68,0.34)",
  },
};

export function chipToneFromMuiColor(color = "default") {
  const normalized = String(color || "default").trim().toLowerCase();
  if (normalized === "default") return "neutral";
  if (normalized === "danger") return "error";
  if (darkChipTones[normalized]) return normalized;
  return "neutral";
}

export function darkChipSx(tone = "default", overrides = {}) {
  const resolvedTone = darkChipTones[chipToneFromMuiColor(tone)] || darkChipTones.default;
  return {
    borderRadius: 999,
    fontWeight: 850,
    border: "1px solid",
    boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
    ...resolvedTone,
    "& .MuiChip-icon, & .MuiChip-deleteIcon": {
      color: "inherit",
    },
    "& .MuiChip-label": {
      color: "inherit",
    },
    ...overrides,
  };
}

export function compactDarkChipSx(tone = "default", overrides = {}) {
  const labelOverrides = overrides["& .MuiChip-label"] || {};
  return darkChipSx(tone, {
    height: 22,
    fontSize: 11,
    "& .MuiChip-label": { px: 1, ...labelOverrides },
    ...overrides,
  });
}
