import React from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Paper,
  Typography,
  Chip,
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Divider,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  IconButton,
  Tooltip,
  TextField,
} from "@mui/material";
import TerminalIcon from "@mui/icons-material/Terminal";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import ContentPasteIcon from "@mui/icons-material/ContentPaste";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import FullscreenIcon from "@mui/icons-material/Fullscreen";
import FullscreenExitIcon from "@mui/icons-material/FullscreenExit";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";
import {
  clearAdminTerminalStepUp,
  createTerminalBrowserWsTicket,
  getAdminTerminalStepUpToken,
  getBrowserWsProtocols,
  getTerminalBrowserWsUrl,
  hasRecentAdminTerminalStepUp,
  setAdminTerminalStepUp,
} from "../../../api";
import { compactDarkChipSx } from "../../../utils/chipStyles";

function nowTime() {
  return new Date().toLocaleTimeString("da-DK", { hour12: false });
}

function normalizeTerminalText(value) {
  return String(value || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trimEnd();
}

function normalizePasteText(value) {
  return String(value || "").replace(/\r\n/g, "\r").replace(/\n/g, "\r");
}

function utf8ToBase64(value) {
  const bytes = new TextEncoder().encode(String(value || ""));
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return window.btoa(binary);
}

function safeClipboardFilename(value) {
  const firstLine = normalizeTerminalText(value).split("\n").find((line) => line.trim()) || "clipboard";
  const base = firstLine
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 42) || "clipboard";
  return `${base}.sh`;
}

function shouldStageClipboardAsScript(value) {
  const text = String(value || "");
  return (
    text.includes("\n") ||
    text.length > 800 ||
    text.includes("<<'") ||
    text.includes('<<"') ||
    text.includes("cat >")
  );
}

function writeSystemLine(term, text, color = "90") {
  if (!term) return;
  term.writeln(`\x1b[${color}m[ClientFlow ${nowTime()}] ${text}\x1b[0m`);
}


const CLIENTFLOW_CANONICAL_STATUS_COMMAND = `cat <<'CLIENTFLOW_CMD' | sudo bash
set -u

echo "== ClientFlow canonical services =="
systemctl --no-pager --full status \
  clientflow-display-agent.service \
  clientflow-display-runtime.service \
  clientflow-status-agent.service \
  clientflow-system-agent.service \
  clientflow-livestream-agent.service \
  clientflow-livestream-broker.service \
  clientflow-livestream-producer.service \
  clientflow-livestream-uploader.service \
  clientflow-terminal-agent.service \
  clientflow-remote-desktop-agent.service \
  clientflow-remote-desktop-capture.service \
  2>/dev/null || true

echo
echo "== Active release =="
readlink -f /opt/clientflow/active 2>/dev/null || true
cat /opt/clientflow/active/VERSION 2>/dev/null || true
CLIENTFLOW_CMD`;

const LIVESTREAM_CANONICAL_STATUS_COMMAND = `cat <<'CLIENTFLOW_CMD' | sudo bash
set -u

echo "== Livestream v2 services =="
systemctl is-active \
  clientflow-livestream-agent.service \
  clientflow-livestream-broker.service \
  clientflow-livestream-producer.service \
  clientflow-livestream-uploader.service || true

echo
echo "== Desired/producer/uploader state =="
for f in \
  /var/lib/clientflow/livestream/desired-state.json \
  /var/lib/clientflow/livestream/producer-status.json \
  /var/lib/clientflow/livestream-uploader/status.json; do
  echo "--- $f"
  cat "$f" 2>/dev/null | python3 -m json.tool || true
done
CLIENTFLOW_CMD`;

const TERMINAL_CANONICAL_STATUS_COMMAND = `cat <<'CLIENTFLOW_CMD' | sudo bash
set -u
systemctl --no-pager --full status \
  clientflow-terminal-agent.service \
  clientflow-standard-terminal-broker.socket \
  clientflow-root-terminal-broker.socket \
  2>/dev/null || true
CLIENTFLOW_CMD`;

const REMOTE_DESKTOP_CANONICAL_STATUS_COMMAND = `cat <<'CLIENTFLOW_CMD' | sudo bash
set -u
systemctl --no-pager --full status \
  clientflow-remote-desktop-agent.service \
  clientflow-remote-desktop-capture.service \
  clientflow-remote-desktop-input-broker.socket \
  2>/dev/null || true
CLIENTFLOW_CMD`;

const SUPPORT_COMMAND_GROUPS = [
  {
    title: "Canonical runtime",
    commands: [
      { label: "ClientFlow samlet status", command: CLIENTFLOW_CANONICAL_STATUS_COMMAND, adminOnly: true },
      { label: "Livestream v2 status", command: LIVESTREAM_CANONICAL_STATUS_COMMAND, adminOnly: true },
      { label: "Terminal status", command: TERMINAL_CANONICAL_STATUS_COMMAND, adminOnly: true },
      { label: "Remote Desktop status", command: REMOTE_DESKTOP_CANONICAL_STATUS_COMMAND, adminOnly: true },
      { label: "Aktive ClientFlow units", command: "systemctl list-units --all --type=service --type=socket --type=target | grep -i clientflow || true" },
    ],
  },
  {
    title: "Logs",
    commands: [
      { label: "Status/System logs", command: "journalctl -u clientflow-status-agent.service -u clientflow-system-agent.service -n 220 --no-pager -l" },
      { label: "Livestream logs", command: "journalctl -u clientflow-livestream-agent.service -u clientflow-livestream-broker.service -u clientflow-livestream-producer.service -u clientflow-livestream-uploader.service -n 240 --no-pager -l" },
      { label: "Terminal logs", command: "journalctl -u clientflow-terminal-agent.service -u clientflow-standard-terminal-broker.service -u clientflow-root-terminal-broker.service -n 220 --no-pager -l" },
      { label: "Remote Desktop logs", command: "journalctl -u clientflow-remote-desktop-agent.service -u clientflow-remote-desktop-capture.service -u clientflow-remote-desktop-input-broker.service -n 220 --no-pager -l" },
    ],
  },
];

export default function ClientTerminalDialog({ open, onClose, client, defaultFullscreen = false, organizations = [] }) {
  const [connected, setConnected] = React.useState(false);
  const [agentConnected, setAgentConnected] = React.useState(false);
  const [ptyReady, setPtyReady] = React.useState(false);
  const [mode, setMode] = React.useState("user");
  const [adminPassword, setAdminPassword] = React.useState("");
  const [adminStepUpReady, setAdminStepUpReady] = React.useState(() => hasRecentAdminTerminalStepUp());
  const [isFullscreen, setIsFullscreen] = React.useState(() => Boolean(defaultFullscreen));

  const [terminalHostEl, setTerminalHostEl] = React.useState(null);
  const terminalRef = React.useRef(null);
  const fitAddonRef = React.useRef(null);
  const wsRef = React.useRef(null);
  const resizeObserverRef = React.useRef(null);
  const openedRef = React.useRef(false);
  const ptyReadyRef = React.useRef(false);
  const sessionIdRef = React.useRef(null);
  const adminPasswordRef = React.useRef("");
  const openPtyRef = React.useRef(null);

  const sendTerminalInput = React.useCallback((data) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !ptyReadyRef.current || !data) return false;
    try {
      ws.send(JSON.stringify({ type: "input", data }));
      terminalRef.current?.focus();
      return true;
    } catch {
      return false;
    }
  }, []);

  const pasteText = React.useCallback(
    (text) => {
      const normalized = normalizePasteText(text);
      if (!normalized) return false;
      return sendTerminalInput(normalized);
    },
    [sendTerminalInput]
  );

  const stageClipboardScript = React.useCallback((text) => {
    const normalized = normalizeTerminalText(text);
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !ptyReadyRef.current || !normalized) return false;

    try {
      ws.send(
        JSON.stringify({
          type: "stage_script",
          filename: safeClipboardFilename(normalized),
          content_b64: utf8ToBase64(normalized),
        })
      );
      terminalRef.current?.focus();
      return true;
    } catch {
      terminalRef.current?.focus();
      return false;
    }
  }, []);

  const copySelection = React.useCallback(async () => {
    const term = terminalRef.current;
    const selected = term?.getSelection?.() || "";
    if (!selected) return false;
    try {
      await navigator.clipboard.writeText(selected);
      term.focus();
      return true;
    } catch {
      return false;
    }
  }, []);

  const pasteFromClipboard = React.useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      const normalized = normalizeTerminalText(text);
      if (!normalized) return false;

      // Store/multiline scripts sendes som fil til klienten og indsætter kun én kommando i prompten.
      // Brugeren skal stadig selv trykke Enter.
      if (shouldStageClipboardAsScript(normalized)) {
        return stageClipboardScript(normalized);
      }

      // Korte/single-line kommandoer indsættes normalt, uden ekstra Enter.
      return pasteText(normalized);
    } catch {
      terminalRef.current?.focus();
      return false;
    }
  }, [pasteText, stageClipboardScript]);

  const selectAllTerminal = React.useCallback(() => {
    const term = terminalRef.current;
    if (!term) return false;
    try {
      term.selectAll();
      term.focus();
      return true;
    } catch {
      return false;
    }
  }, []);

  const fitTerminalAndNotify = React.useCallback(() => {
    const term = terminalRef.current;
    const fitAddon = fitAddonRef.current;
    if (!term || !fitAddon) return;

    try {
      fitAddon.fit();
    } catch {
      return;
    }

    const ws = wsRef.current;
    if (openedRef.current && ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      } catch {
        // Ignorer resize-fejl; næste resize/focus prøver igen.
      }
    }
  }, []);

  React.useEffect(() => {
    if (!open) {
      setIsFullscreen(Boolean(defaultFullscreen));
      return;
    }
    if (defaultFullscreen) setIsFullscreen(true);
  }, [open, defaultFullscreen]);

  React.useEffect(() => {
    if (!open) return undefined;

    const timers = [0, 80, 220, 420].map((delay) =>
      window.setTimeout(() => {
        fitTerminalAndNotify();
        terminalRef.current?.focus();
      }, delay)
    );

    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [open, isFullscreen, fitTerminalAndNotify]);

  React.useEffect(() => {
    if (!open || !client?.id || !terminalHostEl) return undefined;

    setConnected(false);
    setAgentConnected(false);
    setPtyReady(false);
    openedRef.current = false;
    ptyReadyRef.current = false;
    sessionIdRef.current = null;

    let ws;
    let closedByComponent = false;
    let inputDisposable = null;
    let usingWindowResizeFallback = false;

    const term = new Terminal({
      cursorBlink: true,
      convertEol: false,
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
      fontSize: 13,
      scrollback: 5000,
      allowProposedApi: false,
      customKeyEventHandler: (event) => {
        if (event.type !== "keydown") return true;
        const key = String(event.key || "").toLowerCase();
        const isMac = /Mac|iPhone|iPad|iPod/i.test(window.navigator.platform || "");
        const copyShortcut = isMac
          ? event.metaKey && !event.ctrlKey && !event.altKey && key === "c"
          : event.ctrlKey && event.shiftKey && !event.altKey && key === "c";
        const pasteShortcut = isMac
          ? event.metaKey && !event.ctrlKey && !event.altKey && key === "v"
          : event.ctrlKey && event.shiftKey && !event.altKey && key === "v";
        const selectAllShortcut = isMac
          ? event.metaKey && !event.ctrlKey && !event.altKey && key === "a"
          : event.ctrlKey && event.shiftKey && !event.altKey && key === "a";

        if (selectAllShortcut) {
          event.preventDefault();
          selectAllTerminal();
          return false;
        }
        if (copyShortcut) {
          event.preventDefault();
          copySelection();
          return false;
        }
        if (pasteShortcut) {
          event.preventDefault();
          pasteFromClipboard();
          return false;
        }
        return true;
      },
      theme: {
        background: "#0b0f14",
        foreground: "#d7e1ea",
        cursor: "#ffffff",
        selectionBackground: "#375a7f",
      },
    });
    const fitAddon = new FitAddon();
    term.loadAddon(fitAddon);
    term.open(terminalHostEl);
    terminalRef.current = term;
    fitAddonRef.current = fitAddon;

    const sendWs = (payload) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return false;
      try {
        ws.send(JSON.stringify(payload));
        return true;
      } catch {
        return false;
      }
    };

    const fitAndNotifyResize = () => {
      fitTerminalAndNotify();
    };

    const openPty = () => {
      if (openedRef.current || !sessionIdRef.current || !ws || ws.readyState !== WebSocket.OPEN) return;
      const password = String(adminPasswordRef.current || "");
      const stepUpToken = mode === "admin" ? getAdminTerminalStepUpToken() : "";
      if (mode === "admin" && !stepUpToken && !password) {
        setAdminStepUpReady(false);
        writeSystemLine(term, "Admin-terminal kræver step-up med din adgangskode.", "33");
        return;
      }
      try {
        fitAddon.fit();
      } catch {}
      openedRef.current = true;
      const adminAuth = mode !== "admin"
        ? {}
        : (stepUpToken ? { step_up_token: stepUpToken } : { password });
      const sent = sendWs({
        type: "open",
        cols: term.cols || 120,
        rows: term.rows || 32,
        ...adminAuth,
      });
      if (!sent) {
        openedRef.current = false;
      }
    };
    openPtyRef.current = openPty;

    inputDisposable = term.onData((data) => {
      if (!ptyReadyRef.current) {
        term.write("\x07");
        return;
      }
      sendTerminalInput(data);
    });

    const handlePaste = (event) => {
      const text = event.clipboardData?.getData("text/plain") || "";
      const normalized = normalizeTerminalText(text);
      if (!normalized) return;
      event.preventDefault();
      if (shouldStageClipboardAsScript(normalized)) {
        stageClipboardScript(normalized);
      } else {
        pasteText(normalized);
      }
    };

    const handleCopy = (event) => {
      const selected = term.getSelection?.() || "";
      if (!selected) return;
      event.preventDefault();
      event.clipboardData?.setData("text/plain", selected);
      term.focus();
    };

    terminalHostEl.addEventListener("paste", handlePaste);
    terminalHostEl.addEventListener("copy", handleCopy);

    try {
      resizeObserverRef.current = new ResizeObserver(() => {
        window.requestAnimationFrame(fitAndNotifyResize);
      });
      resizeObserverRef.current.observe(terminalHostEl);
    } catch {
      usingWindowResizeFallback = true;
      window.addEventListener("resize", fitAndNotifyResize);
    }

    window.setTimeout(() => {
      fitAndNotifyResize();
      term.focus();
    }, 0);

    let reconnectTimer = null;
    let reconnectAttempt = 0;

    const scheduleReconnect = () => {
      if (closedByComponent || reconnectTimer) return;
      const delay = Math.min(1000 * (2 ** Math.min(reconnectAttempt, 4)), 10_000);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connectWebSocket();
      }, delay);
    };

    const connectWebSocket = async () => {
      try {
        const ticket = await createTerminalBrowserWsTicket(client.id, mode);
        if (closedByComponent) return;
        ws = new WebSocket(
          getTerminalBrowserWsUrl(client.id, mode),
          getBrowserWsProtocols(ticket)
        );
        wsRef.current = ws;
      } catch (err) {
        if (!closedByComponent) {
          writeSystemLine(term, `FEJL: ${err?.message || "Kunne ikke oprette WebSocket-forbindelsen."}`, "31");
          scheduleReconnect();
        }
        return;
      }

      ws.onopen = () => {
      reconnectAttempt = 0;
      setConnected(true);
      writeSystemLine(term, "Forbundet til backend-terminalbroker.");
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        term.write(String(event.data || ""));
        return;
      }

      if (msg.type === "hello") {
        sessionIdRef.current = msg.session_id || null;
        setAgentConnected(!!msg.client_connected);
        writeSystemLine(
          term,
          `${mode === "admin" ? "Admin-terminal" : "Bruger-terminal"} · Session ${msg.session_id || "?"}. Agent: ${
            msg.client_connected ? "forbundet" : "ikke forbundet"
          }.`
        );
        if (msg.client_connected && mode !== "admin") openPty();
        return;
      }

      if (msg.type === "agent_status") {
        const isConnected = !!msg.client_connected;
        setAgentConnected(isConnected);
        writeSystemLine(
          term,
          `Agent: ${isConnected ? "forbundet" : "afbrudt"}${msg.hostname ? ` · ${msg.hostname}` : ""}${
            msg.euid !== undefined && msg.euid !== null ? ` · euid=${msg.euid}` : ""
          }.`
        );
        if (isConnected) {
          if (mode !== "admin") openPty();
        } else {
          openedRef.current = false;
          ptyReadyRef.current = false;
          setPtyReady(false);
        }
        return;
      }

      if (msg.type === "status") {
        writeSystemLine(term, msg.message || "Status");
        return;
      }

      if (msg.type === "admin_step_up") {
        setAdminTerminalStepUp(msg.token, msg.expires_at);
        const ready = hasRecentAdminTerminalStepUp();
        setAdminStepUpReady(ready);
        adminPasswordRef.current = "";
        setAdminPassword("");
        if (ready) {
          writeSystemLine(term, "Admin-step-up godkendt i 10 minutter.", "32");
        }
        return;
      }

      if (msg.type === "ready") {
        ptyReadyRef.current = true;
        setPtyReady(true);
        writeSystemLine(term, `PTY åben (${msg.cols || "?"}x${msg.rows || "?"}${msg.cwd ? ` · ${msg.cwd}` : ""}).`);
        term.focus();
        return;
      }

      if (msg.type === "output") {
        term.write(String(msg.data || ""));
        return;
      }

      if (msg.type === "exit") {
        openedRef.current = false;
        ptyReadyRef.current = false;
        setPtyReady(false);
        writeSystemLine(term, `Terminalprocessen afsluttede med kode ${msg.code}.`, "33");
        return;
      }

      if (msg.type === "error") {
        openedRef.current = false;
        ptyReadyRef.current = false;
        setPtyReady(false);
        if (msg.code === "admin_step_up_required") {
          clearAdminTerminalStepUp();
          setAdminStepUpReady(false);
        }
        writeSystemLine(term, `FEJL: ${msg.message || "Ukendt fejl"}`, "31");
      }
    };

    ws.onclose = (event) => {
      setConnected(false);
      setAgentConnected(false);
      setPtyReady(false);
      openedRef.current = false;
      ptyReadyRef.current = false;
      if (!closedByComponent) {
        writeSystemLine(
          term,
          `Forbindelsen blev lukket (${event.code}${event.reason ? `: ${event.reason}` : ""}). Genopretter …`,
          "33"
        );
        scheduleReconnect();
      }
    };

      ws.onerror = () => {
        writeSystemLine(term, "WebSocket-fejl.", "31");
      };
    };

    void connectWebSocket();

    return () => {
      closedByComponent = true;
      if (reconnectTimer) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }

      try {
        sendWs({ type: "close" });
      } catch {}
      try {
        ws?.close();
      } catch {}

      try {
        inputDisposable?.dispose();
      } catch {}
      terminalHostEl.removeEventListener("paste", handlePaste);
      terminalHostEl.removeEventListener("copy", handleCopy);

      if (usingWindowResizeFallback) {
        window.removeEventListener("resize", fitAndNotifyResize);
      } else {
        try {
          resizeObserverRef.current?.disconnect();
        } catch {}
      }
      try {
        term.dispose();
      } catch {}

      wsRef.current = null;
      terminalRef.current = null;
      fitAddonRef.current = null;
      resizeObserverRef.current = null;
      openedRef.current = false;
      ptyReadyRef.current = false;
      sessionIdRef.current = null;
      openPtyRef.current = null;
    };
  }, [
    open,
    client?.id,
    mode,
    terminalHostEl,
    sendTerminalInput,
    pasteText,
    stageClipboardScript,
    copySelection,
    pasteFromClipboard,
    selectAllTerminal,
    fitTerminalAndNotify,
  ]);

  const insertCommand = React.useCallback(
    (cmd) => {
      const normalized = normalizeTerminalText(cmd);
      if (!normalized) return;

      // Indsæt sender aldrig Enter. Multiline scripts stages som fil og indsætter én bash-kommando.
      if (shouldStageClipboardAsScript(normalized)) {
        stageClipboardScript(normalized);
        return;
      }
      sendTerminalInput(normalizePasteText(normalized));
    },
    [sendTerminalInput, stageClipboardScript]
  );

  const runCommand = React.useCallback(
    (cmd) => {
      const normalized = normalizeTerminalText(cmd);
      if (!normalized) return;
      sendTerminalInput(`${normalized}\r`);
    },
    [sendTerminalInput]
  );

  const copyCommand = React.useCallback(async (cmd) => {
    try {
      await navigator.clipboard.writeText(cmd);
    } catch {
      // Clipboard kan være blokeret i nogle browsere. Ignorer.
    }
  }, []);

  const handleModeChange = React.useCallback((event, nextMode) => {
    if (!nextMode) return;
    if (nextMode !== "admin") {
      adminPasswordRef.current = "";
      setAdminPassword("");
    } else {
      setAdminStepUpReady(hasRecentAdminTerminalStepUp());
    }
    setMode(nextMode);
  }, []);

  const handleAdminPasswordChange = React.useCallback((event) => {
    const value = event.target.value;
    adminPasswordRef.current = value;
    setAdminPassword(value);
  }, []);

  const openAdminTerminal = React.useCallback(() => {
    openPtyRef.current?.();
  }, []);

  const isAdminMode = mode === "admin";
  const terminalDisabled = !connected || !agentConnected || !ptyReady;
  const clientName = client?.name || client?.client_name || client?.hostname || client?.display_name || client?.id || "Ukendt klient";
  const clientIdLabel = client?.id || client?.client_id || client?.clientId || "Ukendt";
  const clientOrganizationId = client?.organization_id ?? client?.organizationId ?? client?.organization?.id ?? null;
  const organizationFromList = Array.isArray(organizations)
    ? organizations.find((org) => String(org?.organization_id ?? org?.id ?? "") === String(clientOrganizationId ?? ""))
    : null;
  const organizationName =
    client?.organization?.name ||
    client?.organization_name ||
    client?.org_name ||
    client?.organisation ||
    organizationFromList?.name ||
    (clientOrganizationId ? `Organisation #${clientOrganizationId}` : "Ukendt organisation");
  const clientLocation = client?.locality || client?.location || client?.address || "Ikke angivet";
  const terminalModeLabel = isAdminMode ? "Admin-terminal" : "Bruger-terminal";
  const terminalModeHelp = isAdminMode
    ? "Admin-terminal kører som root med fulde systemrettigheder."
    : "Bruger-terminal kører som kiosk-brugeren.";

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth={isFullscreen ? false : "xl"}
      fullWidth
      fullScreen={isFullscreen}
      slotProps={{
        paper: {
          sx: {
            height: isFullscreen ? "100vh" : { xs: "calc(100vh - 24px)", md: "calc(100vh - 64px)" },
            maxHeight: isFullscreen ? "100vh" : { xs: "calc(100vh - 24px)", md: "calc(100vh - 64px)" },
            bgcolor: "#020617",
            color: "#f8fafc",
            borderRadius: isFullscreen ? 0 : 2,
            overflow: "hidden",
            border: isFullscreen ? "none" : "1px solid rgba(148,163,184,0.16)",
            boxShadow: "0 28px 110px rgba(0,0,0,0.45)",
          },
        }
      }}
    >
      <DialogTitle
        sx={{
          px: { xs: 1.5, md: 2.5 },
          py: { xs: 1.25, md: 1.6 },
          bgcolor: "rgba(15,23,42,0.88)",
          borderBottom: "1px solid rgba(148,163,184,0.16)",
        }}
      >
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.25} sx={{
          alignItems: { xs: "stretch", md: "center" }
        }}>
          <Stack
            direction="row"
            spacing={1.2}
            sx={{
              alignItems: "center",
              flex: 1,
              minWidth: 0
            }}>
            <Box
              sx={{
                width: 42,
                height: 42,
                borderRadius: 1.5,
                bgcolor: "rgba(37,99,235,0.20)",
                border: "1px solid rgba(96,165,250,0.30)",
                display: "grid",
                placeItems: "center",
                flex: "0 0 auto",
              }}
            >
              <TerminalIcon />
            </Box>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="h6" sx={{ fontWeight: 950, lineHeight: 1.12 }}>
                Terminal
              </Typography>
              <Typography variant="body2" sx={{ color: "rgba(226,232,240,0.72)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={String(clientName)}>
                {clientName}
              </Typography>
              <Stack
                direction="row"
                spacing={0.75}
                useFlexGap
                sx={{
                  flexWrap: "wrap",
                  mt: 0.8
                }}>
                <Chip size="small" label={`Organisation: ${organizationName}`} variant="outlined" sx={compactDarkChipSx("neutral")} />
                <Chip size="small" label={`Klient ID: ${clientIdLabel}`} variant="outlined" sx={compactDarkChipSx("neutral")} />
                <Chip size="small" label={`Lokalitet: ${clientLocation}`} variant="outlined" sx={compactDarkChipSx("neutral")} />
              </Stack>
            </Box>
          </Stack>

          <Stack
            direction="row"
            spacing={0.75}
            useFlexGap
            sx={{
              flexWrap: "wrap",
              alignItems: "center"
            }}>
            <Chip
              size="small"
              label={isAdminMode ? "ROOT" : "Bruger"}
              sx={compactDarkChipSx(isAdminMode ? "error" : "neutral")}
            />
            <Chip size="small" label={connected ? "Backend forbundet" : "Backend afbrudt"} sx={compactDarkChipSx(connected ? "success" : "neutral")} />
            <Chip size="small" label={agentConnected ? "Klient-agent forbundet" : "Venter på klient-agent"} sx={compactDarkChipSx(agentConnected ? "success" : "warning")} />
            <Chip size="small" label={ptyReady ? "PTY klar" : "PTY ikke klar"} sx={compactDarkChipSx(ptyReady ? "success" : "neutral")} />
            <Tooltip title={isFullscreen ? "Afslut fuld skærm" : "Fuld skærm"}>
              <IconButton
                size="small"
                onClick={() => setIsFullscreen((value) => !value)}
                aria-label={isFullscreen ? "Afslut fuld skærm" : "Fuld skærm"}
                sx={{ color: "#e2e8f0", border: "1px solid rgba(148,163,184,0.20)" }}
              >
                {isFullscreen ? <FullscreenExitIcon /> : <FullscreenIcon />}
              </IconButton>
            </Tooltip>
          </Stack>
        </Stack>
      </DialogTitle>
      <DialogContent
        sx={{
          display: "flex",
          flexDirection: "column",
          minHeight: 0,
          p: { xs: 1.25, md: 2 },
          bgcolor: "#020617",
        }}
      >
        <Stack spacing={1.5} sx={{ minHeight: 0, flex: 1 }}>
          <Paper
            elevation={0}
            sx={{
              p: { xs: 1.25, md: 1.5 },
              borderRadius: 2,
              bgcolor: "rgba(15,23,42,0.58)",
              border: "1px solid rgba(148,163,184,0.14)",
            }}
          >
            <Stack direction={{ xs: "column", md: "row" }} spacing={1.2} sx={{
              alignItems: { xs: "stretch", md: "center" }
            }}>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 950, lineHeight: 1.15 }}>
                  {terminalModeLabel}
                </Typography>
                <Typography variant="body2" sx={{ color: "rgba(226,232,240,0.68)" }}>
                  {terminalModeHelp}
                </Typography>
              </Box>
              <ToggleButtonGroup
                size="small"
                exclusive
                value={mode}
                onChange={handleModeChange}
                sx={{
                  bgcolor: "rgba(2,6,23,0.68)",
                  borderRadius: 2,
                  p: 0.4,
                  border: "1px solid rgba(148,163,184,0.14)",
                  "& .MuiToggleButton-root": {
                    color: "rgba(226,232,240,0.78)",
                    border: "none",
                    px: 1.4,
                    borderRadius: "8px !important",
                  },
                  "& .Mui-selected": {
                    bgcolor: "rgba(37,99,235,0.88) !important",
                    color: "#fff !important",
                  },
                }}
              >
                <ToggleButton value="user">Bruger-terminal</ToggleButton>
                <ToggleButton value="admin">Admin-terminal</ToggleButton>
              </ToggleButtonGroup>
            </Stack>
            {isAdminMode ? (
              <Stack spacing={1} sx={{ mt: 1.25 }}>
                <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ alignItems: { md: "flex-start" } }}>
                  {adminStepUpReady ? (
                    <Box sx={{ flex: 1, minWidth: 0, pt: 0.5 }}>
                      <Chip size="small" label="Step-up godkendt · op til 10 min" sx={compactDarkChipSx("success")} />
                      <Typography variant="caption" display="block" sx={{ color: "rgba(226,232,240,0.58)", mt: 0.6 }}>
                        Admin-terminal kan genåbnes uden ny adgangskode i den aktive grace-periode.
                      </Typography>
                    </Box>
                  ) : (
                    <TextField
                      size="small"
                      fullWidth
                      type="password"
                      autoComplete="current-password"
                      value={adminPassword}
                      onChange={handleAdminPasswordChange}
                      label="Bekræft din adgangskode"
                      helperText="Kræves ved første Admin-terminal og igen efter 10 minutter. Gemmes ikke."
                      inputProps={{ maxLength: 512 }}
                      sx={{
                        "& .MuiInputLabel-root": { color: "rgba(226,232,240,0.68)" },
                        "& .MuiInputBase-root": { color: "#f8fafc" },
                        "& .MuiFormHelperText-root": { color: "rgba(226,232,240,0.52)" },
                      }}
                    />
                  )}
                  <Button
                    variant="contained"
                    onClick={openAdminTerminal}
                    disabled={!connected || !agentConnected || ptyReady || (!adminStepUpReady && !adminPassword)}
                    sx={{ minWidth: { md: 190 }, whiteSpace: "nowrap", alignSelf: { md: "flex-start" } }}
                  >
                    Åbn Admin-terminal
                  </Button>
                </Stack>
              </Stack>
            ) : null}
          </Paper>

          <Paper
            elevation={0}
            sx={{
              p: { xs: 1, md: 1.2 },
              borderRadius: 2,
              bgcolor: "rgba(15,23,42,0.58)",
              border: "1px solid rgba(148,163,184,0.14)",
            }}
          >
            <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{
              alignItems: { xs: "stretch", md: "center" }
            }}>
              <Typography variant="caption" sx={{ color: "rgba(226,232,240,0.64)", flex: 1 }}>
                Markér alt: Ctrl+Shift+A på Windows/Linux, Cmd+A på Mac. Copy/paste: Ctrl+Shift+C / Ctrl+Shift+V. På Mac: Cmd+C / Cmd+V.
              </Typography>
              <Stack direction="row" spacing={1} useFlexGap sx={{
                flexWrap: "wrap"
              }}>
                <Button size="small" variant="outlined" startIcon={<ContentCopyIcon />} onClick={copySelection} sx={{ color: "#e2e8f0", borderColor: "rgba(148,163,184,0.28)" }}>
                  Kopiér valgt
                </Button>
                <Button size="small" variant="outlined" startIcon={<ContentPasteIcon />} onClick={pasteFromClipboard} disabled={terminalDisabled} sx={{ color: "#e2e8f0", borderColor: "rgba(148,163,184,0.28)" }}>
                  Indsæt clipboard
                </Button>
              </Stack>
            </Stack>
          </Paper>

          <Paper
            elevation={0}
            sx={{
              bgcolor: "rgba(2,6,23,0.92)",
              p: { xs: 1, md: 1.35 },
              borderRadius: 2,
              overflow: "hidden",
              minHeight: 0,
              flex: isFullscreen ? "1 1 auto" : "0 0 auto",
              border: "1px solid rgba(148,163,184,0.16)",
              boxShadow: "0 24px 80px rgba(0,0,0,0.28)",
            }}
          >
            <Box
              sx={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 1,
                mb: 1,
                px: 0.25,
              }}
            >
              <Typography variant="body2" sx={{ color: "rgba(226,232,240,0.72)", fontWeight: 700 }}>
                Aktiv terminalsession
              </Typography>
              <Typography variant="caption" sx={{ color: terminalDisabled ? "rgba(248,113,113,0.9)" : "rgba(134,239,172,0.88)" }}>
                {terminalDisabled ? "Venter på terminalforbindelse" : "Klar til kommandoer"}
              </Typography>
            </Box>
            <Box
              ref={setTerminalHostEl}
              sx={{
                height: isFullscreen ? "calc(100vh - 410px)" : { xs: 340, md: 500 },
                minHeight: isFullscreen ? { xs: 360, md: 500 } : undefined,
                overflow: "hidden",
                bgcolor: "#0b0f14",
                borderRadius: 2,
                p: 1,
                border: "1px solid rgba(148,163,184,0.16)",
                boxShadow: "inset 0 0 0 1px rgba(15,23,42,0.85)",
                "& .xterm": { height: "100%" },
                "& .xterm-viewport": { borderRadius: 1, backgroundColor: "#0b0f14 !important" },
                "& .xterm-screen": { borderRadius: 1 },
              }}
            />
          </Paper>

          <Accordion
            sx={{
              bgcolor: "rgba(15,23,42,0.74)",
              color: "#f8fafc",
              borderRadius: "8px !important",
              border: "1px solid rgba(148,163,184,0.16)",
              boxShadow: "0 18px 60px rgba(0,0,0,0.20)",
              overflow: "hidden",
              "&:before": { display: "none" },
            }}
          >
            <AccordionSummary expandIcon={<ExpandMoreIcon sx={{ color: "#e2e8f0" }} />}>
              <Box>
                <Typography sx={{
                  fontWeight: 900
                }}>Supportkommandoer</Typography>
                <Typography variant="caption" sx={{ color: "rgba(226,232,240,0.62)" }}>
                  Skriver direkte i den aktive terminal. “Kør” sender kommandoen med Enter.
                </Typography>
              </Box>
            </AccordionSummary>
            <AccordionDetails
              sx={{
                pt: 0,
                pr: 0.5,
                maxHeight: { xs: "42vh", md: isFullscreen ? "min(44vh, 560px)" : 420 },
                overflowY: "auto",
                overscrollBehavior: "contain",
                scrollbarGutter: "stable",
                "&::-webkit-scrollbar": { width: 10 },
                "&::-webkit-scrollbar-thumb": {
                  bgcolor: "rgba(148,163,184,0.34)",
                  borderRadius: 999,
                  border: "2px solid rgba(15,23,42,0.74)",
                },
                "&::-webkit-scrollbar-track": { bgcolor: "rgba(2,6,23,0.22)" },
              }}
            >
              <Stack spacing={1.5} sx={{ minWidth: 0, pb: 0.5 }}>
                {SUPPORT_COMMAND_GROUPS.map((group) => (
                  <Box key={group.title}>
                    <Typography
                      variant="subtitle2"
                      sx={{
                        fontWeight: 900,
                        mb: 0.75,
                        color: "#f8fafc"
                      }}>
                      {group.title}
                    </Typography>
                    <Stack spacing={0.75}>
                      {group.commands.map((item) => {
                        const itemDisabled = terminalDisabled || (item.adminOnly && !isAdminMode);
                        return (
                          <Box
                            key={item.label}
                            sx={{
                              display: "grid",
                              minWidth: 0,
                              gridTemplateColumns: { xs: "1fr", md: "190px minmax(0, 1fr) auto auto auto" },
                              gap: 0.75,
                              alignItems: "center",
                              p: 1,
                              borderRadius: 2,
                              bgcolor: "rgba(2,6,23,0.52)",
                              border: "1px solid rgba(148,163,184,0.10)",
                            }}
                          >
                            <Typography
                              variant="body2"
                              sx={{
                                fontWeight: 800,
                                color: "#f8fafc"
                              }}>
                              {item.label}{item.adminOnly ? " · Admin" : ""}
                            </Typography>
                            <Typography
                              variant="caption"
                              sx={{
                                minWidth: 0,
                                fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                                wordBreak: "break-word",
                                overflowWrap: "anywhere",
                                color: "rgba(226,232,240,0.62)",
                              }}
                            >
                              {item.command}
                            </Typography>
                            <Button size="small" variant="outlined" onClick={() => insertCommand(item.command)} disabled={itemDisabled} sx={{ color: "#e2e8f0", borderColor: "rgba(148,163,184,0.28)" }}>
                              Indsæt
                            </Button>
                            <Button size="small" variant="contained" startIcon={<PlayArrowIcon />} onClick={() => runCommand(item.command)} disabled={itemDisabled}>
                              Kør
                            </Button>
                            <Button size="small" variant="text" startIcon={<ContentCopyIcon />} onClick={() => copyCommand(item.command)} sx={{ color: "#bfdbfe" }}>
                              Kopiér
                            </Button>
                          </Box>
                        );
                      })}
                    </Stack>
                    <Divider sx={{ mt: 1.5, borderColor: "rgba(148,163,184,0.12)" }} />
                  </Box>
                ))}
              </Stack>
            </AccordionDetails>
          </Accordion>
        </Stack>
      </DialogContent>
      {!defaultFullscreen && (
        <DialogActions
          sx={{
            px: { xs: 1.5, md: 2.5 },
            py: 1.25,
            bgcolor: "rgba(15,23,42,0.88)",
            borderTop: "1px solid rgba(148,163,184,0.16)",
          }}
        >
          <Button onClick={onClose} variant="outlined" sx={{ color: "#e2e8f0", borderColor: "rgba(148,163,184,0.28)" }}>
            Luk
          </Button>
        </DialogActions>
      )}
    </Dialog>
  );
}
