const LOGO_SRC = "/brand/planiq-display/planiq-display-logo.png";
const LOGO_ON_DARK_SRC = "/brand/planiq-display/planiq-display-logo-on-dark.png";
const LOGO_MONO_DARK_SRC = "/brand/planiq-display/planiq-display-logo-mono-dark.png";
const MARK_SRC = "/brand/planiq-display/planiq-display-mark.png";
const MARK_ON_DARK_SRC = "/brand/planiq-display/planiq-display-mark-on-dark.png";

export const PRODUCT_BRAND = {
  companyName: "PlanIQ",
  productName: "PlanIQ Display",
  productShortName: "Display",
  productAreaName: "Infoskærm administration",
  browserTitle: "PlanIQ Display",
  loginHeadline: "Log ind",
  loginSubtitle: "Log ind for at styre skærme, kalender og drift.",
  homeSubtitle: "Samlet drift, kalender og administration af infoskærme.",
  navbarSubtitle: "Skærme · kalender · drift",

  // Worklog-kompatibel struktur. Nogle Worklog-baserede filer bruger
  // PRODUCT_BRAND.logo.light / .dark direkte, mens nyere Display-filer
  // bruger de flade *Src-felter nedenfor. Begge bevares med samme værdier.
  logo: {
    light: LOGO_SRC,
    dark: LOGO_ON_DARK_SRC,
    monoDark: LOGO_MONO_DARK_SRC,
    mark: MARK_SRC,
    markDark: MARK_ON_DARK_SRC,
  },

  logoSrc: LOGO_SRC,
  logoOnDarkSrc: LOGO_ON_DARK_SRC,
  logoMonoDarkSrc: LOGO_MONO_DARK_SRC,
  markSrc: MARK_SRC,
  markOnDarkSrc: MARK_ON_DARK_SRC,
  mailProductName: "PlanIQ Display",
  mailFromName: "PlanIQ Display",
  mailLogoPath: LOGO_SRC,
};

export function getBrowserTitle(pageTitle) {
  const normalized = String(pageTitle || "").trim();
  return normalized ? `${normalized} · ${PRODUCT_BRAND.browserTitle}` : PRODUCT_BRAND.browserTitle;
}
