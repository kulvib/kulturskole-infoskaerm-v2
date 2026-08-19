import React from "react";
import Alert from "@mui/material/Alert";
import Snackbar from "@mui/material/Snackbar";
import { alpha } from "@mui/material/styles";

export const SNACKBAR_BACKGROUND_OPACITY = 0.8;

const AUTO_HIDE_DURATION = Object.freeze({
  success: 5000,
  info: 6000,
  warning: 8000,
  error: 8000,
});

const AppSnackbarContext = React.createContext(null);

function normalizeSeverity(severity) {
  return Object.hasOwn(AUTO_HIDE_DURATION, severity) ? severity : "info";
}

function SnackbarSurface({
  open,
  message,
  severity = "info",
  onClose,
  autoHideDuration,
}) {
  const normalizedSeverity = normalizeSeverity(severity);

  const handleClose = (event, reason) => {
    if (reason === "clickaway") return;
    onClose?.(event, reason);
  };

  return (
    <Snackbar
      open={Boolean(open)}
      autoHideDuration={autoHideDuration ?? AUTO_HIDE_DURATION[normalizedSeverity]}
      onClose={handleClose}
      anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
    >
      <Alert
        data-planiq-snackbar-opacity={SNACKBAR_BACKGROUND_OPACITY}
        elevation={6}
        variant="filled"
        severity={normalizedSeverity}
        onClose={handleClose}
        sx={(theme) => ({
          width: "100%",
          maxWidth: { xs: "calc(100vw - 32px)", sm: 560 },
          // Dobbelt specificitet sikrer, at MuiAlert-filled*-temaets solide
          // baggrunde aldrig kan overskrive snackbarens fælles 80 %-kontrakt.
          "&&": {
            backgroundColor: alpha(
              theme.palette[normalizedSeverity].main,
              SNACKBAR_BACKGROUND_OPACITY,
            ),
            backgroundImage: "none",
          },
          color: theme.palette[normalizedSeverity].contrastText,
          backdropFilter: "blur(10px)",
        })}
      >
        {message}
      </Alert>
    </Snackbar>
  );
}

export function AppSnackbarProvider({ children }) {
  const [activeSnackbar, setActiveSnackbar] = React.useState(null);
  const activeSnackbarRef = React.useRef(null);
  const sequenceRef = React.useRef(0);

  const publish = React.useCallback((nextSnackbar) => {
    const previousSnackbar = activeSnackbarRef.current;
    sequenceRef.current += 1;
    const publishedSnackbar = {
      ...nextSnackbar,
      instanceKey: `${nextSnackbar.sourceId}-${sequenceRef.current}`,
    };

    if (previousSnackbar && previousSnackbar.sourceId !== nextSnackbar.sourceId) {
      previousSnackbar.onCloseRef.current?.(null, "replaced");
    }

    activeSnackbarRef.current = publishedSnackbar;
    setActiveSnackbar(publishedSnackbar);
  }, []);

  const dismiss = React.useCallback((sourceId) => {
    if (activeSnackbarRef.current?.sourceId !== sourceId) return;
    activeSnackbarRef.current = null;
    setActiveSnackbar(null);
  }, []);

  const handleClose = React.useCallback((event, reason) => {
    if (reason === "clickaway") return;

    const currentSnackbar = activeSnackbarRef.current;
    activeSnackbarRef.current = null;
    setActiveSnackbar(null);
    currentSnackbar?.onCloseRef.current?.(event, reason);
  }, []);

  const contextValue = React.useMemo(
    () => ({ publish, dismiss }),
    [publish, dismiss],
  );

  return (
    <AppSnackbarContext.Provider value={contextValue}>
      {children}
      <SnackbarSurface
        key={activeSnackbar?.instanceKey ?? "empty"}
        open={Boolean(activeSnackbar)}
        message={activeSnackbar?.message ?? ""}
        severity={activeSnackbar?.severity ?? "info"}
        autoHideDuration={activeSnackbar?.autoHideDuration}
        onClose={handleClose}
      />
    </AppSnackbarContext.Provider>
  );
}

export default function AppSnackbar({
  open,
  message,
  severity = "info",
  onClose,
  autoHideDuration,
}) {
  const snackbarContext = React.useContext(AppSnackbarContext);
  const sourceId = React.useId();
  const onCloseRef = React.useRef(onClose);

  React.useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  React.useEffect(() => {
    if (!snackbarContext) return undefined;

    if (open) {
      snackbarContext.publish({
        sourceId,
        message,
        severity: normalizeSeverity(severity),
        autoHideDuration,
        onCloseRef,
      });
    } else {
      snackbarContext.dismiss(sourceId);
    }

    return () => snackbarContext.dismiss(sourceId);
  }, [
    snackbarContext,
    sourceId,
    open,
    message,
    severity,
    autoHideDuration,
  ]);

  if (snackbarContext) return null;

  return (
    <SnackbarSurface
      open={open}
      message={message}
      severity={severity}
      onClose={onClose}
      autoHideDuration={autoHideDuration}
    />
  );
}
