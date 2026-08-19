import React, { useState } from "react";
import { Outlet, useNavigate, useLocation, Link as RouterLink } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { useTheme } from "@mui/material/styles";
import useMediaQuery from "@mui/material/useMediaQuery";
import {
  AppBar,
  Toolbar,
  Typography,
  Button,
  Box,
  IconButton,
  Menu,
  MenuItem,
  Divider,
  ListItemIcon,
  ListItemText,
  Drawer,
  List,
  ListItemButton,
} from "@mui/material";
import LogoutIcon from "@mui/icons-material/Logout";
import VpnKeyIcon from "@mui/icons-material/VpnKey";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import MenuIcon from "@mui/icons-material/Menu";
import CalendarMonthIcon from "@mui/icons-material/CalendarMonth";
import DesktopWindowsIcon from "@mui/icons-material/DesktopWindows";
import HomeIcon from "@mui/icons-material/Home";
import { PRODUCT_BRAND } from "./branding";
import { getCanonicalUserRole, getRoleLabel, hasAdminOrSuperadminRole, hasSuperadminRole, isViewerRole } from "./utils/roleUtils";

const DISPLAY_LOGO_WHITE = PRODUCT_BRAND.logo.dark;
const DISPLAY_PRODUCT_NAME = PRODUCT_BRAND.productName;
const NAVBAR_DARK = "#1e293b";


export default function Dashboard() {
  const { user, logoutUser } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("md"));

  const role = getCanonicalUserRole(user);
  const isSuperadmin = hasSuperadminRole(user);
  const isViewer = isViewerRole(user);
  const isAdmin = hasAdminOrSuperadminRole(user);
  const canViewAdmin = isAdmin || isViewer;
  const canViewCalendar = isAdmin || isViewer;

  const [userMenuAnchorEl, setUserMenuAnchorEl] = useState(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const userMenuOpen = Boolean(userMenuAnchorEl);

  const closeMenus = React.useCallback(() => {
    setUserMenuAnchorEl(null);
  }, []);

  const handleUserMenuOpen = (event) => {
    setUserMenuAnchorEl(event.currentTarget);
  };

  const handleUserMenuClose = () => {
    setUserMenuAnchorEl(null);
  };

  const navigateFromMenu = React.useCallback((to) => {
    closeMenus();
    setDrawerOpen(false);
    navigate(to);
  }, [closeMenus, navigate]);

  React.useEffect(() => {
    closeMenus();
  }, [location.pathname, closeMenus]);

  const handleLogout = () => {
    closeMenus();
    setDrawerOpen(false);
    logoutUser();
    navigate("/login");
  };

  const handleChangePassword = () => {
    navigateFromMenu("/skift-adgangskode");
  };

  const handleDrawerNavigate = (to) => {
    setDrawerOpen(false);
    navigate(to);
  };

  React.useEffect(() => {
    if (!isMobile && drawerOpen) setDrawerOpen(false);
    if (isMobile) closeMenus();
  }, [isMobile, drawerOpen, closeMenus]);

  const adminLink = canViewAdmin
    ? { to: "/administration", label: "Administration", icon: <AdminPanelSettingsIcon fontSize="small" /> }
    : null;

  const routeIsActive = (path) => {
    const [pathname, query] = path.split("?");
    if (query) return location.pathname === pathname && location.search.includes(query);
    return location.pathname === pathname || location.pathname.startsWith(`${pathname}/`);
  };

  const adminActive = location.pathname === "/administration";
  const organizationName = String(user?.organization_name || "").trim();
  const organizationKommune = String(user?.organization_kommune || "").trim();
  const orgLogoSrc = user?.organization_logo_url ?? user?.organizationLogoUrl ?? null;
  const showOrganizationIdentity = !isSuperadmin && Boolean(organizationName || organizationKommune || orgLogoSrc);
  const orgLabel = organizationName || DISPLAY_PRODUCT_NAME;

  const userDisplayName = user?.name || user?.full_name || user?.username || "";
  const userDisplayRole = getRoleLabel(role);
  const userDisplayWithRole = userDisplayName
    ? `${userDisplayName} - ${userDisplayRole}`
    : userDisplayRole;
  const userEmail = String(user?.email || "").trim();

  const navButtonSx = (active) => ({
    color: "#fff",
    bgcolor: active ? "rgba(255,255,255,0.16)" : "transparent",
    fontWeight: active ? 700 : 500,
    borderRadius: 1.5,
    textTransform: "none",
    fontSize: 14,
    whiteSpace: "nowrap",
    px: 1.5,
    py: 0.5,
    transition: "background-color 160ms ease, color 160ms ease",
    "&:hover": { bgcolor: "rgba(255,255,255,0.10)", color: "#fff" },
  });

  const drawerLinkSx = (isActive) => ({
    mx: 1,
    borderRadius: 1.5,
    mb: 0.5,
    gap: 1.5,
    minHeight: 44,
    color: isActive ? "#fff" : "#94a3b8",
    bgcolor: isActive ? "#334155" : "transparent",
    "&:hover": { bgcolor: "#334155", color: "#fff" },
    "&.Mui-selected": {
      bgcolor: "#334155",
      color: "#fff",
      "&:hover": { bgcolor: "#334155" },
    },
  });

  const mobileNavLinks = [
    { to: "/", label: "Forside", icon: <HomeIcon fontSize="small" /> },
    { to: "/clients", label: "Control Room", icon: <DesktopWindowsIcon fontSize="small" /> },
    ...(canViewCalendar ? [{ to: "/calendar", label: "Kalender", icon: <CalendarMonthIcon fontSize="small" /> }] : []),
  ];

  const drawer = (
    <Drawer
      anchor="left"
      open={drawerOpen}
      onClose={() => setDrawerOpen(false)}
      slotProps={{
        paper: {
          sx: {
            width: { xs: "85vw", sm: 280 },
            maxWidth: 320,
            bgcolor: NAVBAR_DARK,
            display: "flex",
            flexDirection: "column",
          },
        }
      }}
    >
      <Box
        onClick={() => handleDrawerNavigate("/")}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") handleDrawerNavigate("/"); }}
        sx={{
          px: 2,
          py: 2,
          display: "flex",
          alignItems: "center",
          gap: 1,
          borderBottom: "1px solid #334155",
          cursor: "pointer",
          "&:hover": { bgcolor: "#334155" },
        }}
      >
        <Box
          component="img"
          src={DISPLAY_LOGO_WHITE}
          alt={DISPLAY_PRODUCT_NAME}
          sx={{ width: 150, maxWidth: showOrganizationIdentity ? "58%" : "100%", height: "auto", flexShrink: 0 }}
        />
        {showOrganizationIdentity && (
          <>
            <Divider orientation="vertical" flexItem sx={{ borderColor: "rgba(255,255,255,0.35)", mx: 0.5 }} />
            {orgLogoSrc && (
              <Box
                component="img"
                src={orgLogoSrc}
                alt={`${orgLabel} logo`}
                sx={{ height: 28, width: "auto", maxWidth: 58, objectFit: "contain", flexShrink: 0 }}
              />
            )}
            <Box sx={{ minWidth: 0 }}>
              {organizationName && (
                <Typography
                  noWrap
                  sx={{
                    fontWeight: 700,
                    color: "#fff",
                    fontSize: 14
                  }}>
                  {organizationName}
                </Typography>
              )}
              {organizationKommune && (
                <Typography
                  noWrap
                  sx={{
                    fontSize: 12,
                    color: "#94a3b8"
                  }}>
                  {organizationKommune}
                </Typography>
              )}
            </Box>
          </>
        )}
      </Box>

      <List sx={{ flex: 1, py: 1, overflowY: "auto" }}>
        {mobileNavLinks.map((link) => {
          const isActive = routeIsActive(link.to);
          return (
            <ListItemButton
              key={link.to}
              selected={isActive}
              onClick={() => handleDrawerNavigate(link.to)}
              sx={drawerLinkSx(isActive)}
            >
              <ListItemIcon sx={{ minWidth: 0, color: "inherit" }}>{link.icon}</ListItemIcon>
              <ListItemText
                primary={link.label}
                slotProps={{
                  primary: { fontSize: 14, fontWeight: 700 }
                }}
              />
            </ListItemButton>
          );
        })}

        {adminLink && (
          <>
            <Divider sx={{ borderColor: "#334155", my: 0.5, mx: 1 }} />
            <ListItemButton
              selected={adminActive}
              onClick={() => handleDrawerNavigate(adminLink.to)}
              sx={drawerLinkSx(adminActive)}
            >
              <ListItemIcon sx={{ minWidth: 0, color: "inherit" }}>{adminLink.icon}</ListItemIcon>
              <ListItemText
                primary={adminLink.label}
                slotProps={{
                  primary: { fontSize: 14, fontWeight: 700 }
                }}
              />
            </ListItemButton>
          </>
        )}
      </List>

      <Box sx={{ borderTop: "1px solid #334155", p: 2 }}>
        <Box sx={{ mb: 1.5 }}>
          <Typography
            noWrap
            sx={{
              fontWeight: 700,
              color: "#fff",
              fontSize: 14
            }}>
            {userDisplayName}
          </Typography>
          {userEmail && (
            <Typography
              variant="caption"
              noWrap
              sx={{
                color: "#94a3b8",
                display: "block"
              }}>
              {userEmail}
            </Typography>
          )}
          <Typography
            variant="caption"
            sx={{
              color: "#64748b",
              display: "block"
            }}>
            {userDisplayRole}
          </Typography>
        </Box>
        <Button
          fullWidth
          variant="outlined"
          onClick={handleChangePassword}
          startIcon={<VpnKeyIcon fontSize="small" />}
          sx={{
            mb: 1,
            textTransform: "none",
            color: "#e2e8f0",
            borderColor: "#475569",
            "&:hover": { bgcolor: "#334155", borderColor: "#64748b" },
          }}
        >
          Skift adgangskode
        </Button>
        <Button
          fullWidth
          variant="outlined"
          onClick={handleLogout}
          startIcon={<LogoutIcon fontSize="small" />}
          sx={{
            textTransform: "none",
            color: "#f87171",
            borderColor: "#f87171",
            "&:hover": { bgcolor: "#7f1d1d30", borderColor: "#ef4444" },
          }}
        >
          Log ud
        </Button>
      </Box>
    </Drawer>
  );

  return (
    <>
      {drawer}
      <AppBar position="fixed" sx={{ zIndex: 1201, bgcolor: NAVBAR_DARK, backgroundImage: "none" }} elevation={2}>
        <Toolbar sx={{
          minHeight: 56,
          px: { xs: 1, md: 2 },
          position: "relative",
        }}>
          {/* ── VENSTRE ── */}
          <Box
            onClick={() => navigate("/")}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") navigate("/"); }}
            sx={{
              flex: "0 1 auto",
              display: "flex",
              alignItems: "center",
              gap: 1,
              minWidth: 0,
              maxWidth: { xs: "calc(100% - 48px)", md: 430 },
              cursor: "pointer",
              px: 0,
              py: 0,
            }}
          >
            {isMobile && (
              <IconButton
                onClick={(e) => { e.stopPropagation(); setDrawerOpen(true); }}
                aria-label="Åbn menu"
                sx={{ color: "white", p: 0.75, mr: 0.5, flexShrink: 0 }}
              >
                <MenuIcon />
              </IconButton>
            )}
            <Box
              component="img"
              src={DISPLAY_LOGO_WHITE}
              alt={DISPLAY_PRODUCT_NAME}
              sx={{ height: 34, width: "auto", maxWidth: 180, objectFit: "contain", display: "block", flexShrink: 0 }}
            />
            {showOrganizationIdentity && (
              <>
                <Divider orientation="vertical" flexItem sx={{ borderColor: "rgba(255,255,255,0.35)", mx: { xs: 0.5, md: 1 } }} />
                {orgLogoSrc && (
                  <Box
                    component="img"
                    src={orgLogoSrc}
                    alt={`${orgLabel} logo`}
                    sx={{ height: 30, width: "auto", maxWidth: 68, objectFit: "contain", display: "block", flexShrink: 0 }}
                  />
                )}
                <Box sx={{ minWidth: 0 }}>
                  {organizationName && (
                    <Typography
                      sx={{
                        fontWeight: 700,
                        color: "#fff",
                        letterSpacing: 0,
                        fontSize: { xs: 14, md: 17 },
                        lineHeight: 1.2,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis"
                      }}>
                      {organizationName}
                    </Typography>
                  )}
                  {organizationKommune && (
                    <Typography sx={{
                      color: "rgba(255,255,255,0.85)",
                      fontSize: { xs: 11, md: 13 },
                      lineHeight: 1.2,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}>
                      {organizationKommune}
                    </Typography>
                  )}
                </Box>
              </>
            )}
          </Box>

          {/* ── MIDTEN ── */}
          {!isMobile && (
            <Box sx={{
              position: "absolute",
              left: "50%",
              transform: "translateX(-50%)",
              display: "flex",
              alignItems: "center",
              gap: 0.5,
              height: "100%",
            }}>
              <Button
                component={RouterLink}
                to="/clients"
                startIcon={<DesktopWindowsIcon fontSize="small" />}
                sx={navButtonSx(routeIsActive("/clients"))}
              >
                Control Room
              </Button>

              {canViewCalendar && (
                <Button
                  component={RouterLink}
                  to="/calendar"
                  startIcon={<CalendarMonthIcon fontSize="small" />}
                  sx={navButtonSx(routeIsActive("/calendar"))}
                >
                  Kalender
                </Button>
              )}

              {adminLink && (
                <Button
                  component={RouterLink}
                  to={adminLink.to}
                  startIcon={<AdminPanelSettingsIcon fontSize="small" />}
                  sx={navButtonSx(adminActive)}
                >
                  Administration
                </Button>
              )}
            </Box>
          )}

          {/* ── HØJRE ── */}
          {!isMobile && (
            <Box sx={{
              ml: "auto",
              flex: "0 1 auto",
              display: "flex",
              alignItems: "center",
              justifyContent: "flex-end",
              gap: 1.5,
            }}>
              <Button
                onClick={handleUserMenuOpen}
                endIcon={<ExpandMoreIcon fontSize="small" />}
                aria-controls={userMenuOpen ? "user-menu" : undefined}
                aria-haspopup="true"
                aria-expanded={userMenuOpen ? "true" : undefined}
                sx={{
                  textTransform: "none",
                  borderRadius: 2,
                  px: 1.5,
                  py: 0.5,
                  color: "white",
                  "&:hover": { background: "rgba(255,255,255,0.10)" },
                }}
              >
                <Box sx={{ textAlign: "right", lineHeight: 1.2 }}>
                  <Typography component="span" sx={{ display: "block", color: "white", fontWeight: 500, fontSize: 15 }}>
                    {userDisplayWithRole}
                  </Typography>
                  {userEmail && (
                    <Typography component="span" sx={{ display: "block", color: "rgba(255,255,255,0.85)", fontSize: 12 }}>
                      {userEmail}
                    </Typography>
                  )}
                </Box>
              </Button>

              <Menu
                id="user-menu"
                anchorEl={userMenuAnchorEl}
                open={userMenuOpen}
                onClose={handleUserMenuClose}
                anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
                transformOrigin={{ vertical: "top", horizontal: "right" }}
                keepMounted
                slotProps={{ paper: { sx: { minWidth: 220, mt: 0.5 } } }}
              >
                <Box sx={{ px: 2, py: 1.25, maxWidth: 280 }}>
                  <Typography sx={{ fontWeight: 700, fontSize: 14 }}>
                    {userDisplayName}
                  </Typography>
                  {userEmail && (
                    <Typography sx={{ color: "text.secondary", fontSize: 12, wordBreak: "break-all" }}>
                      {userEmail}
                    </Typography>
                  )}
                </Box>
                <Divider />
                <MenuItem onClick={handleChangePassword}>
                  <ListItemIcon>
                    <VpnKeyIcon fontSize="small" />
                  </ListItemIcon>
                  Skift adgangskode
                </MenuItem>
                <MenuItem onClick={handleLogout}>
                  <ListItemIcon>
                    <LogoutIcon fontSize="small" />
                  </ListItemIcon>
                  Log ud
                </MenuItem>
              </Menu>
            </Box>
          )}

        </Toolbar>
      </AppBar>
      <Toolbar sx={{ minHeight: 56 }} />
      <Box component="main" sx={{ p: { xs: 2, md: 3 }, minHeight: "calc(100vh - 56px)", bgcolor: "transparent" }}>
        <Outlet />
      </Box>
    </>
  );
}
