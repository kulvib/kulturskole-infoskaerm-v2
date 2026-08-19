import React from "react";
import { createRoot } from "react-dom/client";
import { ThemeProvider, CssBaseline } from "@mui/material";
import App from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import { BrowserRouter } from "react-router-dom";
import theme from "./theme";
import { AppSnackbarProvider } from "./components/AppSnackbar";

const container = document.getElementById("root");
const root = createRoot(container);
root.render(
  <React.StrictMode>
    <BrowserRouter>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <AppSnackbarProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </AppSnackbarProvider>
      </ThemeProvider>
    </BrowserRouter>
  </React.StrictMode>
);
