import React, { useState, useEffect } from "react";
import { Box, Typography, Paper, Stack, Grid } from "@mui/material";
import { Link } from "react-router-dom";
import PeopleIcon from "@mui/icons-material/People";
import CalendarMonthIcon from "@mui/icons-material/CalendarMonth";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import { useAuth } from "./auth/AuthProvider";
import { getOrganizations } from "./api";
import { PRODUCT_BRAND } from "./branding";
import PlanIQBrandLockup from "./PlanIQBrandLockup";

function ActionCard({ title, description, to, icon }) {
  return (
    <Paper
      component={Link}
      to={to}
      elevation={0}
      sx={{
        textDecoration: "none",
        color: "inherit",
        cursor: "pointer",
        height: "100%",
        p: { xs: 2, md: 2.4 },
        borderRadius: 2,
        background: "rgba(15,23,42,0.62)",
        border: "1px solid rgba(148,163,184,0.16)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
        display: "flex",
        flexDirection: "column",
        gap: 1.25,
        transition: "background 160ms ease, border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease",
        "&:hover": {
          transform: "translateY(-2px)",
          background: "linear-gradient(135deg, rgba(56,189,248,0.18), rgba(20,184,166,0.10))",
          borderColor: "rgba(56,189,248,0.34)",
          boxShadow: "0 18px 55px rgba(8,47,73,0.24), inset 0 1px 0 rgba(255,255,255,0.05)",
        },
        "&:focus-visible": {
          outline: "2px solid rgba(56,189,248,0.75)",
          outlineOffset: 3,
          transform: "translateY(-2px)",
          background: "linear-gradient(135deg, rgba(56,189,248,0.18), rgba(20,184,166,0.10))",
          borderColor: "rgba(56,189,248,0.42)",
        },
      }}
    >
      <Box
        sx={{
          width: 42,
          height: 42,
          borderRadius: 2,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: "#bae6fd",
          bgcolor: "rgba(56,189,248,0.12)",
          border: "1px solid rgba(56,189,248,0.18)",
        }}
      >
        {icon}
      </Box>

      <Box sx={{ flexGrow: 1 }}>
        <Typography variant="h6" sx={{ fontWeight: 950, color: "#f8fafc", lineHeight: 1.1 }}>
          {title}
        </Typography>
        <Typography variant="body2" sx={{ mt: 0.65, color: "rgba(203,213,225,0.68)", lineHeight: 1.45 }}>
          {description}
        </Typography>
      </Box>

    </Paper>
  );
}

export default function HomePage() {
  const { user, isAdmin, isViewer } = useAuth();
  const [organizationName, setOrganizationName] = useState("");

  useEffect(() => {
    const organizationId = user?.organization_id;

    if (user && user.role === "bruger" && organizationId) {
      getOrganizations()
        .then((organizations) => {
          const organization = organizations.find((item) => String(item.id) === String(organizationId));
          setOrganizationName(organization ? organization.name : "");
        })
        .catch(() => setOrganizationName(""));
    } else {
      setOrganizationName("");
    }
  }, [user]);

  const subtitle = !isAdmin && !isViewer && organizationName
    ? `Administration af infoskærme for ${organizationName}`
    : PRODUCT_BRAND.homeSubtitle;

  return (
    <Box
      sx={{
        maxWidth: 1100,
        mx: "auto",
        py: { xs: 2, md: 5 },
        px: { xs: 0.5, sm: 0 },
      }}
    >
      <Paper
        elevation={0}
        sx={{
          position: "relative",
          overflow: "hidden",
          p: { xs: 2.25, sm: 3.5, md: 5 },
          borderRadius: 2,
          background:
            "radial-gradient(circle at 12% 0%, rgba(56,189,248,0.24), transparent 32%), radial-gradient(circle at 86% 12%, rgba(34,197,94,0.14), transparent 28%), linear-gradient(135deg, rgba(15,23,42,0.92), rgba(2,6,23,0.88))",
          border: "1px solid rgba(148,163,184,0.18)",
          boxShadow: "0 28px 90px rgba(0,0,0,0.34), inset 0 1px 0 rgba(255,255,255,0.05)",
        }}
      >
        <Box
          sx={{
            position: "absolute",
            inset: "auto -15% -35% auto",
            width: 420,
            height: 420,
            borderRadius: "50%",
            background: "rgba(56,189,248,0.09)",
            filter: "blur(24px)",
            pointerEvents: "none",
          }}
        />

        <Stack spacing={2.2} sx={{ position: "relative" }}>
          <PlanIQBrandLockup size="home" showSubtitle />

          <Box>
            <Typography
              variant="h4"
              sx={{
                fontWeight: 950,
                color: "#f8fafc",
                lineHeight: 1.02,
                fontSize: { xs: "2rem", sm: "2.6rem", md: "3.35rem" },
                maxWidth: 760,
              }}
            >
              {PRODUCT_BRAND.productAreaName}
            </Typography>
            <Typography
              variant="h6"
              sx={{
                mt: 1.2,
                color: "rgba(203,213,225,0.72)",
                fontWeight: 650,
                lineHeight: 1.4,
                maxWidth: 720,
              }}
            >
              {subtitle}
            </Typography>
          </Box>

          <Grid container spacing={1.5} sx={{ pt: 1 }}>
            <Grid
              size={{
                xs: 12,
                md: isAdmin || isViewer ? 4 : 6
              }}>
              <ActionCard
                title="Klienter"
                description="Se skærme og status."
                to="/clients"
                icon={<PeopleIcon />}
              />
            </Grid>
            <Grid
              size={{
                xs: 12,
                md: isAdmin || isViewer ? 4 : 6
              }}>
              <ActionCard
                title="Kalender"
                description="Planlæg tænd/sluk-dage og få overblik over driftstider."
                to="/calendar"
                icon={<CalendarMonthIcon />}
              />
            </Grid>
            {(isAdmin || isViewer) && (
              <Grid
                size={{
                  xs: 12,
                  md: 4
                }}>
                <ActionCard
                  title="Administration"
                  description="Administrér brugere, organisationer og systemopsætning."
                  to="/administration"
                  icon={<AdminPanelSettingsIcon />}
                />
              </Grid>
            )}
          </Grid>
        </Stack>
      </Paper>
    </Box>
  );
}
