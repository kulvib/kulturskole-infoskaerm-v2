import React, { useCallback, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import SecurityIcon from "@mui/icons-material/Security";
import RocketLaunchIcon from "@mui/icons-material/RocketLaunch";
import HistoryIcon from "@mui/icons-material/History";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";

import OrganizationAdministration from "./OrganizationAdministration";
import UserAdministration from "./UserAdministration";
import EnrollmentTokensPage from "./EnrollmentTokensPage";
import AuditLog from "./AuditLog";
import { useAuth } from "../../auth/AuthProvider";
import { compactDarkChipSx } from "../../utils/chipStyles";
import {
  pageHeaderIconSx,
  pageHeaderPaperSx,
  pageShellSx,
} from "../../utils/layoutStyles";

const DEFAULT_SECTION = "organisation";

const SECTIONS = [
  {
    key: "organisation",
    label: "Organisation",
    icon: <AccountTreeIcon fontSize="small" />,
  },
  {
    key: "access",
    label: "Adgang",
    icon: <SecurityIcon fontSize="small" />,
  },
  {
    key: "audit",
    label: "Audit-log",
    icon: <HistoryIcon fontSize="small" />,
    superadminOnly: true,
  },
  {
    key: "installation",
    label: "Installation",
    icon: <RocketLaunchIcon fontSize="small" />,
    superadminOnly: true,
  },
];

const panelSx = {
  borderRadius: 2,
  background: "rgba(15,23,42,0.74)",
  border: "1px solid rgba(148,163,184,0.16)",
  boxShadow: "0 24px 80px rgba(0,0,0,0.22)",
};

function SectionButton({ section, active, onClick }) {
  return (
    <Button
      onClick={onClick}
      startIcon={section.icon}
      aria-current={active ? "page" : undefined}
      sx={{
        minHeight: 50,
        justifyContent: "flex-start",
        borderRadius: 2,
        px: 1.7,
        color: active ? "#f8fafc" : "rgba(203,213,225,0.74)",
        fontWeight: active ? 950 : 800,
        border: active
          ? "1px solid rgba(56,189,248,0.32)"
          : "1px solid rgba(148,163,184,0.12)",
        background: active
          ? "linear-gradient(90deg, rgba(56,189,248,0.20), rgba(20,184,166,0.10))"
          : "rgba(15,23,42,0.42)",
        "&:hover": {
          background: active
            ? "linear-gradient(90deg, rgba(56,189,248,0.26), rgba(20,184,166,0.14))"
            : "rgba(30,41,59,0.62)",
          borderColor: "rgba(148,163,184,0.24)",
        },
      }}
    >
      {section.label}
    </Button>
  );
}

export default function AdminPage() {
  const { user, isSuperadmin, isViewer } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedSection = searchParams.get("section") || DEFAULT_SECTION;

  const visibleSections = useMemo(
    () =>
      SECTIONS.filter(
        (section) => !section.superadminOnly || isSuperadmin || isViewer,
      ),
    [isSuperadmin, isViewer],
  );

  const fallbackSection = visibleSections[0]?.key || DEFAULT_SECTION;
  const activeSection = visibleSections.some(
    (section) => section.key === requestedSection,
  )
    ? requestedSection
    : fallbackSection;

  const setSection = useCallback(
    (key) => {
      const next = new URLSearchParams(searchParams);
      next.set("section", key);
      setSearchParams(next, { replace: false });
    },
    [searchParams, setSearchParams],
  );

  useEffect(() => {
    if (activeSection !== requestedSection) {
      const next = new URLSearchParams(searchParams);
      next.set("section", activeSection);
      setSearchParams(next, { replace: true });
    }
  }, [activeSection, requestedSection, searchParams, setSearchParams]);

  const activeConfig =
    visibleSections.find((section) => section.key === activeSection) ||
    visibleSections[0];

  return (
    <Box sx={{ ...pageShellSx, color: "#f8fafc" }}>
      <Stack spacing={2.2}>
        <Paper
          elevation={0}
          sx={{
            ...pageHeaderPaperSx,
            background:
              "linear-gradient(135deg, rgba(15,23,42,0.92), rgba(30,41,59,0.62))",
          }}
        >
          <Stack spacing={2}>
            <Stack
              direction={{ xs: "column", md: "row" }}
              spacing={1.4}
              sx={{
                alignItems: { xs: "stretch", md: "flex-end" },
                justifyContent: "space-between"
              }}>
              <Stack
                direction="row"
                spacing={1.35}
                sx={{
                  alignItems: "center",
                  minWidth: 0
                }}>
                <Box sx={pageHeaderIconSx}>
                  <AdminPanelSettingsIcon />
                </Box>
                <Box sx={{
                  minWidth: 0
                }}>
                  <Typography
                    variant="h4"
                    sx={{
                      fontWeight: 950,
                      letterSpacing: -0.7,
                      fontSize: { xs: "1.55rem", sm: "2rem", md: "2.35rem" },
                    }}
                  >
                    Administration
                  </Typography>
                </Box>
              </Stack>

              <Stack
                direction="row"
                spacing={1}
                sx={{
                  alignItems: "center",
                  flexWrap: "wrap"
                }}>
                <Chip
                  label={
                    user?.role === "superadmin"
                      ? "Superadministrator"
                      : user?.role === "viewer"
                        ? "Se adgang"
                        : "Administrator"
                  }
                  sx={compactDarkChipSx(
                    user?.role === "superadmin"
                      ? "primary"
                      : user?.role === "viewer"
                        ? "info"
                        : "neutral",
                  )}
                />
              </Stack>
            </Stack>

            <Divider sx={{ borderColor: "rgba(148,163,184,0.12)" }} />

            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: {
                  xs: "1fr",
                  sm: "repeat(2, minmax(0, 1fr))",
                  lg: `repeat(${visibleSections.length}, minmax(0, 1fr))`,
                },
                gap: 1,
              }}
            >
              {visibleSections.map((section) => (
                <SectionButton
                  key={section.key}
                  section={section}
                  active={section.key === activeSection}
                  onClick={() => setSection(section.key)}
                />
              ))}
            </Box>
          </Stack>
        </Paper>

        {activeSection === "organisation" && (
          <Box>
            <OrganizationAdministration />
          </Box>
        )}

        {activeSection === "access" && (
          <Box>
            <UserAdministration />
          </Box>
        )}

        {activeSection === "audit" &&
          (isSuperadmin || isViewer ? (
            <Box>
              <AuditLog />
            </Box>
          ) : (
            <Alert severity="error">
              Kun superadministratorer og Se adgang kan se audit-log.
            </Alert>
          ))}

        {activeSection === "installation" &&
          (isSuperadmin || isViewer ? (
            <Box>
              <EnrollmentTokensPage />
            </Box>
          ) : (
            <Alert severity="error">
              Kun superadministratorer og Se adgang kan se installationskoder.
            </Alert>
          ))}
      </Stack>
    </Box>
  );
}
