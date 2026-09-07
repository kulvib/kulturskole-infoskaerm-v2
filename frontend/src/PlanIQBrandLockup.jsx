import { Box, Stack, Typography } from "@mui/material";
import { PRODUCT_BRAND } from "./branding";

const SIZE_CONFIG = {
  navbar: {
    height: { xs: 38, sm: 42, md: 46 },
    maxWidth: { xs: 168, sm: 190, md: 214 },
    subtitleSize: { xs: "0.72rem", sm: "0.78rem" },
    gap: 0.55,
  },
  menu: {
    height: 42,
    maxWidth: 210,
    subtitleSize: "0.76rem",
    gap: 0.6,
  },
  login: {
    height: { xs: 78, sm: 92 },
    maxWidth: { xs: 280, sm: 340 },
    subtitleSize: { xs: "0.8rem", sm: "0.86rem" },
    gap: 0.85,
  },
  home: {
    height: { xs: 66, sm: 78, md: 88 },
    maxWidth: { xs: 260, sm: 330, md: 390 },
    subtitleSize: { xs: "0.78rem", sm: "0.84rem" },
    gap: 0.75,
  },
};

const LOGO_BY_VARIANT = {
  onDark: PRODUCT_BRAND.logoOnDarkSrc,
  light: PRODUCT_BRAND.logoSrc,
  monoDark: PRODUCT_BRAND.logoMonoDarkSrc,
};

export default function PlanIQBrandLockup({
  size = "navbar",
  variant = "onDark",
  showSubtitle = false,
  sx,
}) {
  const config = SIZE_CONFIG[size] || SIZE_CONFIG.navbar;
  const logoSrc = LOGO_BY_VARIANT[variant] || PRODUCT_BRAND.logoOnDarkSrc;

  return (
    <Stack
      spacing={config.gap}
      aria-label={PRODUCT_BRAND.productName}
      sx={{
        alignItems: "flex-start",
        minWidth: 0,
        maxWidth: "100%",
        ...sx
      }}>
      <Box
        component="img"
        src={logoSrc}
        alt={PRODUCT_BRAND.productName}
        sx={{
          height: config.height,
          width: "auto",
          maxWidth: config.maxWidth,
          objectFit: "contain",
          objectPosition: "left center",
          display: "block",
          filter: "drop-shadow(0 10px 24px rgba(0,0,0,0.28))",
        }}
      />
      {showSubtitle && (
        <Typography
          component="div"
          sx={{
            color: "rgba(203,213,225,0.72)",
            fontWeight: 750,
            fontSize: config.subtitleSize,
            lineHeight: 1.25,
            letterSpacing: 0.08,
            whiteSpace: "normal",
          }}
        >
          {PRODUCT_BRAND.navbarSubtitle}
        </Typography>
      )}
    </Stack>
  );
}
