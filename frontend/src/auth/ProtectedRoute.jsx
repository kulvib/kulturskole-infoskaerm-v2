// src/auth/ProtectedRoute.jsx
// Beskytter routes mod ikke-indloggede brugere.
// Validerer sessionen ved at kalde GET /api/auth/me med HttpOnly-cookie.
import React, { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthProvider";
import { apiUrl, authHeaders, clearAuthToken, performBootRefresh } from "../api";

export default function ProtectedRoute({ children, requireSuperadmin = false }) {
  const { user, logoutUser, isSuperadmin, loading } = useAuth();
  const location = useLocation();
  const [valid, setValid] = useState(null); // null = tjekker stadig

  useEffect(() => {
    if (loading) return;
    if (!user) {
      setValid(false);
      return;
    }

    let cancelled = false;
    async function validate() {
      let res = await fetch(`${apiUrl}/api/auth/me`, {
        headers: authHeaders(),
        credentials: "include",
      });

      if (res.status === 401) {
        const refreshed = await performBootRefresh();
        if (refreshed) {
          res = await fetch(`${apiUrl}/api/auth/me`, {
            headers: authHeaders(),
            credentials: "include",
          });
        }
      }

      if (cancelled) return;
      if (res.status === 401 || res.status === 403) {
        clearAuthToken();
        logoutUser();
        setValid(false);
      } else {
        setValid(true);
      }
    }

    validate().catch(() => {
      if (!cancelled) setValid(true);
    });

    return () => { cancelled = true; };
  }, [loading, user, logoutUser]);

  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (valid === null) return null;
  if (!valid) return <Navigate to="/login" replace />;
  if (requireSuperadmin && !isSuperadmin) return <Navigate to="/" replace />;
  if (user.must_change_password && !["/skift-adgangskode", "/skift-password"].includes(location.pathname)) {
    return <Navigate to="/skift-adgangskode" replace />;
  }

  return children;
}
