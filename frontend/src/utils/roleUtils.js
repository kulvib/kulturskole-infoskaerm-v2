export const CANONICAL_ROLES = ["superadmin", "admin", "bruger", "viewer"];

const ROLE_ALIASES = {
  super_admin: "superadmin",
  superadministrator: "superadmin",
  super_administrator: "superadmin",
  administrator: "admin",
  user: "bruger",
  se: "viewer",
  se_adgang: "viewer",
  seadgang: "viewer",
  "se adgang": "viewer",
  read_only: "viewer",
  readonly: "viewer",
};

export function normalizeCanonicalRole(value) {
  const raw = String(value || "").trim().toLowerCase().replace(/[\s-]+/g, "_");
  if (!raw) return "";
  const role = ROLE_ALIASES[raw] || raw;
  return CANONICAL_ROLES.includes(role) ? role : "";
}

export function getCanonicalUserRole(user) {
  if (!user) return "bruger";

  const roleFromField = normalizeCanonicalRole(user.role || user.user_role);
  if (roleFromField) return roleFromField;

  const roles = Array.isArray(user.roles) ? user.roles : [];
  const roleFromList = roles.map((role) => normalizeCanonicalRole(role)).find(Boolean);
  if (roleFromList) return roleFromList;

  return "bruger";
}

export function hasSuperadminRole(user) {
  return getCanonicalUserRole(user) === "superadmin";
}

export function hasAdminRole(user) {
  return getCanonicalUserRole(user) === "admin";
}

export function hasAdminOrSuperadminRole(user) {
  return ["superadmin", "admin"].includes(getCanonicalUserRole(user));
}

export function isViewerRole(user) {
  return getCanonicalUserRole(user) === "viewer";
}

export function getRoleLabel(userOrRole) {
  const role = typeof userOrRole === "string"
    ? normalizeCanonicalRole(userOrRole)
    : getCanonicalUserRole(userOrRole);

  if (role === "superadmin") return "Superadministrator";
  if (role === "admin") return "Administrator";
  if (role === "viewer") return "Se adgang";
  return "Bruger";
}
