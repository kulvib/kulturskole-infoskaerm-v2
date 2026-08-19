// src/auth/authcontext.jsx
// Fælles PlanIQ-sessionpolitik:
// kort access token i memory, refresh-token i HttpOnly-cookie,
// 25+5 minutters idle-advarsel, servervalideret fortsættelse,
// cross-tab logout/aktivitet og absolut sessiongrænse.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  apiUrl,
  authHeaders,
  clearAuthToken,
  getSessionExpiresAt,
  logout as apiLogout,
  performBootRefresh,
  refreshSession,
} from "../api";
import SessionTimeoutDialog from "./SessionTimeoutDialog";
import { useSessionPolicy } from "./sessionPolicy";
import { getCanonicalUserRole, getRoleLabel, hasAdminOrSuperadminRole, hasSuperadminRole, isViewerRole } from "../utils/roleUtils";

const AuthContext = createContext();

function normalizeUserData(userData) {
  if (!userData) return userData;
  const organizationId = userData.organization_id ?? userData.organizationId ?? null;
  const role = getCanonicalUserRole(userData);
  return {
    ...userData,
    organization_id: organizationId,
    role,
    role_display: userData.role_display || getRoleLabel(role),
  };
}

const PUBLIC_AUTH_PATHS = new Set([
  "/login",
  "/glemt-adgangskode",
  "/nulstil-adgangskode",
]);

function isPublicAuthPath(pathname = "") {
  return PUBLIC_AUTH_PATHS.has(pathname);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sessionExpiresAt, setSessionExpiresAtState] = useState(null);
  const navigate = useNavigate();
  const location = useLocation();

  const endLocalSession = useCallback(async () => {
    // Start server-logout mens det nuværende access-token stadig er tilgængeligt.
    const serverLogout = apiLogout().catch(() => {
      // Lokal session ryddes under alle omstændigheder.
    });

    setUser(null);
    setLoading(false);
    setSessionExpiresAtState(null);
    localStorage.removeItem("user");
    clearAuthToken();
    navigate("/login", { replace: true });

    await serverLogout;
  }, [navigate]);

  const validateCurrentSession = useCallback(async () => {
    const refreshed = await refreshSession();
    const nextExpiry = refreshed?.session_expires_at || getSessionExpiresAt() || null;
    setSessionExpiresAtState(nextExpiry);
    return refreshed;
  }, []);

  const sessionPolicy = useSessionPolicy({
    active: Boolean(user),
    sessionExpiresAt,
    validateSession: validateCurrentSession,
    onSessionEnd: endLocalSession,
  });

  const loginUser = useCallback((userData, nextSessionExpiresAt = null) => {
    const normalized = normalizeUserData(userData);
    setUser(normalized);
    setLoading(false);
    setSessionExpiresAtState(nextSessionExpiresAt || getSessionExpiresAt() || null);
    localStorage.setItem("user", JSON.stringify(normalized));
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function boot() {
      setLoading(true);

      // Login/nulstil-adgangskode er offentlige sider. Her skal en manglende
      // refresh-cookie ikke skabe et forventet 401-kald i baggrunden.
      if (isPublicAuthPath(location.pathname)) {
        if (!cancelled) {
          setUser(null);
          setSessionExpiresAtState(null);
          localStorage.removeItem("user");
          clearAuthToken();
          setLoading(false);
        }
        return;
      }

      try {
        const refreshed = await performBootRefresh();
        if (!refreshed) {
          if (!cancelled) {
            setUser(null);
            setSessionExpiresAtState(null);
            localStorage.removeItem("user");
          }
          return;
        }

        const res = await fetch(`${apiUrl}/api/auth/me`, {
          headers: authHeaders(),
          credentials: "include",
        });
        if (!res.ok) throw new Error("Sessionen er ikke længere gyldig");
        const data = normalizeUserData(await res.json());
        if (!cancelled) {
          setUser(data);
          setSessionExpiresAtState(refreshed?.session_expires_at || getSessionExpiresAt() || null);
          localStorage.setItem("user", JSON.stringify(data));
        }
      } catch {
        if (!cancelled) {
          setUser(null);
          setSessionExpiresAtState(null);
          localStorage.removeItem("user");
          clearAuthToken();
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    boot();
    return () => { cancelled = true; };
  }, [location.pathname]);

  const isSuperadmin = hasSuperadminRole(user);
  const isViewer = isViewerRole(user);
  const isAdministrator = getCanonicalUserRole(user) === "admin";
  const isAdmin = hasAdminOrSuperadminRole(user);
  const canReadAll = isSuperadmin || isViewer;

  return (
    <AuthContext.Provider value={{
      user,
      me: user,
      loading,
      loginUser,
      logoutUser: sessionPolicy.logoutNow,
      logout: sessionPolicy.logoutNow,
      isAdmin,
      isSuperadmin,
      isViewer,
      isAdministrator,
      canReadAll,
    }}>
      {children}
      <SessionTimeoutDialog
        type={sessionPolicy.dialogType}
        secondsRemaining={sessionPolicy.secondsRemaining}
        continuePending={sessionPolicy.continuePending}
        continueError={sessionPolicy.continueError}
        onContinue={sessionPolicy.continueSession}
        onLogout={sessionPolicy.logoutNow}
        onLoginAgain={sessionPolicy.loginAgain}
        onDismissAbsolute={sessionPolicy.dismissAbsoluteWarning}
      />
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
