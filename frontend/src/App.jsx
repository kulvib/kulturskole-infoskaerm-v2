import { lazy, Suspense, useEffect } from "react";
import { Navigate, Routes, Route } from "react-router-dom";

import ProtectedRoute from "./auth/ProtectedRoute";
import AdminRoute from "./auth/AdminRoute";
import { getBrowserTitle } from "./branding";
import { SeasonProvider } from "./season/SeasonProvider";

const Dashboard = lazy(() => import("./Dashboard"));
const ClientInfoPage = lazy(() => import("./pages/ClientInfoPage"));
const ClientDetailsPageWrapper = lazy(
  () => import("./pages/clientdetailspage/ClientDetailsPageWrapper"),
);
const LoginPage = lazy(() => import("./LoginPage"));
const HomePage = lazy(() => import("./HomePage"));
const NotFound = lazy(() => import("./NotFound"));
const CalendarPage = lazy(() => import("./pages/calendarpage/CalendarPage"));
const AdminPage = lazy(() => import("./pages/adminpages/AdminPage"));
const RemoteDesktop = lazy(
  () => import("./pages/clientdetailspage/remotedesktop/RemoteDesktop"),
);
const ClientTerminalPage = lazy(
  () => import("./pages/clientdetailspage/terminal/ClientTerminalPage"),
);
const ChangePassword = lazy(() => import("./ChangePassword"));
const ForgotPasswordPage = lazy(() => import("./ForgotPasswordPage"));
const ResetPasswordPage = lazy(() => import("./ResetPasswordPage"));

function RouteLoadingFallback() {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        minHeight: "35vh",
        display: "grid",
        placeItems: "center",
        color: "#cbd5e1",
        fontFamily: "Inter, system-ui, sans-serif",
      }}
    >
      Indlæser…
    </div>
  );
}

/*
  App.jsx

  Klientoversigt:
  - /clients

  Klient Control Room:
  - /clients/:id

  Remote Desktop:
  - /remote-desktop/:clientId

  Terminal:
  - /terminal/:clientId

  Administration:
  - /administration
  - /installationskoder redirecter til /administration?section=installation
*/

export default function App() {
  useEffect(() => {
    document.title = getBrowserTitle();
  }, []);

  return (
    <Suspense fallback={<RouteLoadingFallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/glemt-adgangskode" element={<ForgotPasswordPage />} />
        <Route path="/nulstil-adgangskode" element={<ResetPasswordPage />} />

        <Route
          path="/"
          element={
            <ProtectedRoute>
              <SeasonProvider>
                <Dashboard />
              </SeasonProvider>
            </ProtectedRoute>
          }
        >
          <Route index element={<HomePage />} />
          <Route path="clients" element={<ClientInfoPage />} />
          <Route path="clients/:id" element={<ClientDetailsPageWrapper />} />
          <Route path="calendar" element={<CalendarPage />} />
          <Route path="skift-adgangskode" element={<ChangePassword />} />
          <Route path="skift-password" element={<ChangePassword />} />

          <Route
            path="administration"
            element={
              <AdminRoute allowViewer>
                <AdminPage />
              </AdminRoute>
            }
          />
          <Route
            path="installationskoder"
            element={
              <AdminRoute requireSuperadmin>
                <Navigate to="/administration?section=installation" replace />
              </AdminRoute>
            }
          />
        </Route>

        <Route
          path="/remote-desktop/:clientId"
          element={
            <ProtectedRoute>
              <AdminRoute requireSuperadmin>
                <RemoteDesktop />
              </AdminRoute>
            </ProtectedRoute>
          }
        />

        <Route
          path="/terminal/:clientId"
          element={
            <ProtectedRoute>
              <AdminRoute requireSuperadmin>
                <ClientTerminalPage />
              </AdminRoute>
            </ProtectedRoute>
          }
        />

        <Route path="*" element={<NotFound />} />
      </Routes>
    </Suspense>
  );
}
