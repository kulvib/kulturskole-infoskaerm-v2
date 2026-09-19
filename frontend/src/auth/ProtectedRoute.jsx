// src/auth/ProtectedRoute.jsx
// Beskytter routes mod ikke-indloggede brugere.
// AuthProvider ejer servervalidering/refresh; denne komponent er kun UI/rolle-gate.
import React from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export default function ProtectedRoute({ children, requireSuperadmin = false }) {
  const { user, isSuperadmin, loading } = useAuth();
  const location = useLocation();

  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  if (requireSuperadmin && !isSuperadmin) return <Navigate to="/" replace />;
  if (user.must_change_password && !["/skift-adgangskode", "/skift-password"].includes(location.pathname)) {
    return <Navigate to="/skift-adgangskode" replace />;
  }

  return children;
}
