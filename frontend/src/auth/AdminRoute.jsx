// src/auth/AdminRoute.jsx
// Beskytter routes mod ikke-administratorer.
import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export default function AdminRoute({ children, requireSuperadmin = false, allowViewer = false }) {
  const { user, isAdmin, isSuperadmin, isViewer } = useAuth();

  if (!user) return <Navigate to="/login" replace />;
  if (requireSuperadmin && !isSuperadmin) return <Navigate to="/" replace />;
  if (!isAdmin && !(allowViewer && isViewer)) return <Navigate to="/" replace />;

  return children;
}
