import { getOrganizations } from "../../api";
import client from "../../api/client";
import { formatApiError } from "../../api/apiError";

// ─── Auth-model ─────────────────────────────────────────────────────────────
//
// Display-repoet bruger samme centrale API-klient som resten af adminområdet.
// Det betyder, at et udløbet access-token forsøges fornyet via refresh-cookie,
// før brugeren sendes til login. Adgangskoder eksponeres ikke i UI.

async function request(path, { method = "GET", body } = {}) {
  const config = { method, url: path };
  if (body !== undefined) config.data = body;
  const { data } = await client.request(config);
  return data ?? null;
}

function normalizeUser(user) {
  if (!user) return user;
  const name = user.name ?? user.full_name ?? "";
  return {
    ...user,
    name,
    full_name: user.full_name ?? name,
    organization_id: user.organization_id ?? user.organizationId ?? null,
  };
}

export function normalizeText(value) {
  return String(value ?? "").trim().replace(/\s+/g, " ");
}

export function normalizeEmail(value) {
  return normalizeText(value).toLowerCase();
}

export function normalizeUsername(value) {
  return normalizeText(value);
}

export async function fetchUsers() {
  const data = await request("/api/users/");
  return Array.isArray(data) ? data.map(normalizeUser) : [];
}

export async function createUser(body) {
  return normalizeUser(await request("/api/users/", { method: "POST", body }));
}

export async function patchUser(userId, body) {
  return normalizeUser(await request(`/api/users/${userId}`, { method: "PATCH", body }));
}

export async function sendPasswordResetLink(userId) {
  return request(`/api/users/${userId}/reset-password`, { method: "POST", body: {} });
}

export async function assignTemporaryPassword(userId, temporaryPassword) {
  return request(`/api/users/${userId}/temporary-password`, {
    method: "POST",
    body: { temporary_password: temporaryPassword },
  });
}

export async function permanentlyDeleteUser(userId, confirmationEmail) {
  return request(`/api/users/${userId}/permanent-delete`, {
    method: "POST",
    body: { confirmation_email: confirmationEmail },
  });
}

export async function fetchOrganizations() {
  const organizations = await getOrganizations();
  return Array.isArray(organizations) ? organizations : [];
}

export function validateEmail(email) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(email ?? "").trim().toLowerCase());
}

/**
 * Genererer et tilfældigt midlertidigt password efter Worklog-princippet:
 * mindst 12 tegn og med bogstav, tal og specialtegn.
 */
export function generatePassword(length = 16) {
  if (length < 12) length = 12;

  const lower = "abcdefghijklmnopqrstuvwxyz";
  const upper = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  const digits = "0123456789";
  const special = "!@#$%&*";
  const all = lower + upper + digits + special;

  const pickFrom = (set) => {
    const buf = new Uint32Array(1);
    crypto.getRandomValues(buf);
    return set[buf[0] % set.length];
  };

  const required = [pickFrom(lower), pickFrom(upper), pickFrom(digits), pickFrom(special)];
  const rest = Array.from(crypto.getRandomValues(new Uint8Array(length - required.length))).map(
    (b) => all[b % all.length]
  );

  const chars = [...required, ...rest];
  for (let i = chars.length - 1; i > 0; i -= 1) {
    const buf = new Uint32Array(1);
    crypto.getRandomValues(buf);
    const j = buf[0] % (i + 1);
    [chars[i], chars[j]] = [chars[j], chars[i]];
  }
  return chars.join("");
}

export function errorToString(err) {
  if (!err) return "Ukendt fejl";

  const data = err?.response?.data;
  const status = err?.status ?? err?.response?.status;

  // Uventede serverfejl må aldrig vise rå backendtekst. Den centrale
  // fejlkontrakt viser i stedet det korrelerede request-id til support.
  if (Number(status || 0) >= 500) {
    return formatApiError(err, "Der opstod en uventet fejl.");
  }

  if (data) {
    if (typeof data.detail === "string") return _humanize(data.detail);

    if (Array.isArray(data.detail)) {
      const messages = data.detail
        .map((item) => _humanize(item?.msg || item?.message || ""))
        .filter(Boolean);
      if (messages.length) return messages.join(" · ");
    }

    if (typeof data.message === "string") return _humanize(data.message);
  }

  if (
    err?.code === "ERR_NETWORK" ||
    err?.message === "Network Error" ||
    err?.message === "Failed to fetch" ||
    err?.message === "NetworkError when attempting to fetch resource." ||
    (!err?.response && err instanceof Error)
  ) {
    return "Netværksfejl – tjek din internetforbindelse og prøv igen.";
  }

  if (err?.code === "ECONNABORTED" || err?.message?.toLowerCase().includes("timeout")) {
    return "Serveren svarer ikke – prøv igen om lidt.";
  }

  if (status) {
    if (status === 401) return "Din session er udløbet – log ind igen.";
    if (status === 403) return "Du har ikke adgang til denne handling.";
    if (status === 404) return "Den ønskede ressource blev ikke fundet.";
    if (status === 409) return "Handlingen kunne ikke gennemføres – data eksisterer muligvis allerede.";
    if (status === 422) return "De indtastede oplysninger er ugyldige – tjek felterne og prøv igen.";
    if (status >= 500) return "Der opstod en fejl på serveren – prøv igen om lidt.";
  }

  const raw = err?.message || String(err);
  return _humanize(raw);
}

function _humanize(raw) {
  if (!raw) return "Der opstod en uventet fejl – prøv igen.";
  let msg = raw.replace(/^Value error,\s*/i, "").trim();

  const known = [
    [/adgangskode.*mindst\s*12|password.*mindst\s*12/i, "Adgangskoden skal være mindst 12 tegn lang."],
    [/password.*samme.*gamle|adgangskode.*samme.*gamle/i, "Det nye password må ikke være det samme som det gamle."],
    [/bruger.*email.*allerede|brugernavn.*email.*allerede|allerede i brug/i, "Der findes allerede en bruger med dette brugernavn eller denne email."],
    [/ugyldig.*email|e-mail/i, "Email-adressen er ikke gyldig."],
    [/organisation.*ikke fundet/i, "Den valgte organisation findes ikke."],
    [/bruger.*ikke fundet/i, "Brugeren blev ikke fundet."],
    [/bekræftelses-email matcher ikke/i, "Bekræftelses-email matcher ikke brugeren."],
    [/brugeren skal være deaktiveret/i, "Brugeren skal først deaktiveres, før den kan slettes permanent."],
    [/superadministrator kan ikke slettes|superadministrator kan ikke deaktiveres/i, "En superadministrator kan ikke deaktiveres eller slettes."],
    [/sidste aktive superadministrator/i, "Du kan ikke ændre eller deaktivere den sidste aktive superadministrator."],
    [/session.*udløbet|login udløbet|ugyldig eller udløbet session/i, "Din session er udløbet – log ind igen."],
    [/brugerkontoen er deaktiveret|kontoen er inaktiv/i, "Denne brugerkonto er deaktiveret."],
    [/du skal skifte adgangskode/i, "Du skal skifte adgangskode, før du kan fortsætte."],
    [/ikke.*adgang|ikke tilstrækkelig/i, "Du har ikke de nødvendige rettigheder til denne handling."],
    [/kun.*egen organisation/i, "Du kan kun administrere brugere i din egen organisation."],
    [/viewer|se \/ viewer|se-adgang/i, "Kun superadministrator kan oprette eller administrere Se-adgang."],
    [/network error|failed to fetch/i, "Netværksfejl – tjek forbindelsen og prøv igen."],
  ];

  for (const [pattern, replacement] of known) {
    if (pattern.test(msg)) return replacement;
  }

  return msg || "Der opstod en uventet fejl – prøv igen.";
}

export function downloadUserFile({ name, email, username, password }) {
  const content = [
    "Loginoplysninger til PlanIQ Display",
    "====================================",
    `Navn:       ${name || ""}`,
    `Email:      ${email || ""}`,
    `Brugernavn: ${username || ""}`,
    `Password:   ${password || ""}`,
    "",
    "Brugeren skal skifte adgangskode ved næste login.",
  ].join("\n");
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `login-${username}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}
