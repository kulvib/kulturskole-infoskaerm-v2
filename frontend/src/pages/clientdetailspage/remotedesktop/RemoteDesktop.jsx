import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Divider,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import KeyboardIcon from "@mui/icons-material/Keyboard";
import MouseIcon from "@mui/icons-material/Mouse";
import FullscreenIcon from "@mui/icons-material/Fullscreen";
import {
  apiUrl,
  authHeaders,
  createBrowserWsTicket,
  getBrowserWsProtocols,
  getClient,
  getOrganizations,
  getRemoteDesktopBrowserWsUrl,
} from "../../../api";
import RemoteDesktopFileManager from "./RemoteDesktopFileManager";
import AppSnackbar from "../../../components/AppSnackbar";
import {
  buildRemoteDesktopBrowserDownloadUrl,
  buildRemoteDesktopUploadMultipleUrl,
} from "./remoteDesktopUrls";
import {
  getEffectiveDisplayResolution,
  getRemoteDesktopCaptureResolution,
  formatDisplayResolution,
} from "../../../utils/displayResolution";
import { compactDarkChipSx } from "../../../utils/chipStyles";
import {
  getRemoteKeyboardAction,
  REMOTE_KEYBOARD_MODE_MAC,
  REMOTE_KEYBOARD_MODE_STANDARD,
} from "./remoteKeyboardMapping";

function clamp(n, min, max) {
  return Math.max(min, Math.min(max, n));
}

function getRemoteScreenGeometryFromMessage(msg, allowWidthHeightFallback = false) {
  const width =
    Number(msg?.screen_width || msg?.screenWidth || msg?.source_width || msg?.sourceWidth || msg?.remote_width || msg?.remoteWidth || 0) ||
    (allowWidthHeightFallback ? Number(msg?.width || 0) : 0);
  const height =
    Number(msg?.screen_height || msg?.screenHeight || msg?.source_height || msg?.sourceHeight || msg?.remote_height || msg?.remoteHeight || 0) ||
    (allowWidthHeightFallback ? Number(msg?.height || 0) : 0);

  if (width > 0 && height > 0) {
    return { width: Math.round(width), height: Math.round(height) };
  }
  return null;
}


function formatBytes(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "";
  const bytes = Number(value);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const UPLOAD_TOTAL_LIMIT_BYTES = 100 * 1024 * 1024;

function sumFileSizes(files) {
  return Array.from(files || []).reduce((sum, file) => sum + Number(file?.size || 0), 0);
}

export default function RemoteDesktop() {
  const { clientId } = useParams();

  const [client, setClient] = useState(null);
  const [organizations, setOrganizations] = useState([]);

  const wsRef = useRef(null);
  const connectAttemptRef = useRef(0);
  const connectRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const imgRef = useRef(null);
  const containerRef = useRef(null);
  const fileInputRef = useRef(null);
  const dragCounterRef = useRef(0);
  const mouseDownRef = useRef(false);
  const lastMouseMoveSentRef = useRef(0);
  const shoutAckTimerRef = useRef(null);
  const fileBrowserPathRef = useRef("");
  const fileBrowserShowHiddenRef = useRef(false);
  const pendingDeleteCountRef = useRef(0);
  const pendingDeleteTotalRef = useRef(0);
  const pendingDeleteErrorsRef = useRef([]);

  const [connected, setConnected] = useState(false);
  const [agentConnected, setAgentConnected] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [status, setStatus] = useState("Ikke forbundet");
  const [error, setError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [frameSrc, setFrameSrc] = useState("");
  const [screenSize, setScreenSize] = useState({ width: null, height: null });
  const [lastFrameTs, setLastFrameTs] = useState(null);
  const [frameAgeTick, setFrameAgeTick] = useState(0);
  const [keyboardEnabled, setKeyboardEnabled] = useState(false);
  const [keyboardMode, setKeyboardMode] = useState(REMOTE_KEYBOARD_MODE_STANDARD);
  const [activeTab, setActiveTab] = useState("desktop");
  const [dragOverUpload, setDragOverUpload] = useState(false);
  const [shoutText, setShoutText] = useState("");
  const [shoutSending, setShoutSending] = useState(false);
  const [transferFiles, setTransferFiles] = useState([]);
  const [transferUploading, setTransferUploading] = useState(false);
  const [transferStatus, setTransferStatus] = useState("");
  const [transferError, setTransferError] = useState("");
  const [fileBrowserPath, setFileBrowserPath] = useState("");
  const [fileBrowserDisplayPath, setFileBrowserDisplayPath] = useState("");
  const [fileBrowserParentPath, setFileBrowserParentPath] = useState("");
  const [fileBrowserShortcuts, setFileBrowserShortcuts] = useState([]);
  const [fileBrowserEntries, setFileBrowserEntries] = useState([]);
  const [fileBrowserLoading, setFileBrowserLoading] = useState(false);
  const [fileBrowserShowHidden, setFileBrowserShowHidden] = useState(false);
  const [fileBrowserError, setFileBrowserError] = useState("");
  const [fileDownloadStatus, setFileDownloadStatus] = useState("");
  const [fileDownloadingPath, setFileDownloadingPath] = useState("");
  const [fileOperationBusy, setFileOperationBusy] = useState(false);
  const [fileOperationStatus, setFileOperationStatus] = useState("");
  const [selectedFilePaths, setSelectedFilePaths] = useState([]);

  const canControl = connected && agentConnected && sessionId;

  const effectiveRemoteResolution = useMemo(
    () => getEffectiveDisplayResolution(client, screenSize),
    [client, screenSize]
  );
  const effectiveRemoteAspectRatio = `${effectiveRemoteResolution.width} / ${effectiveRemoteResolution.height}`;
  const effectiveRemoteResolutionText = formatDisplayResolution(effectiveRemoteResolution);
  const remoteCaptureResolution = useMemo(
    () => getRemoteDesktopCaptureResolution(client, screenSize),
    [client, screenSize]
  );
  const remoteCaptureResolutionText = formatDisplayResolution(remoteCaptureResolution);
  const streamStartPayload = useMemo(() => ({
    type: "start_stream",
    // Native geometry is authoritative on the physical client. The browser
    // must not turn stale inventory/fallback dimensions into a capture cap.
    native: true,
  }), []);
  const streamStartPayloadRef = useRef(streamStartPayload);
  const effectiveRemoteResolutionTextRef = useRef(effectiveRemoteResolutionText);
  const remoteCaptureResolutionTextRef = useRef(remoteCaptureResolutionText);

  useEffect(() => {
    streamStartPayloadRef.current = streamStartPayload;
  }, [streamStartPayload]);

  useEffect(() => {
    effectiveRemoteResolutionTextRef.current = effectiveRemoteResolutionText;
    remoteCaptureResolutionTextRef.current = remoteCaptureResolutionText;
  }, [effectiveRemoteResolutionText, remoteCaptureResolutionText]);

  useEffect(() => {
    let cancelled = false;

    async function loadClient() {
      if (!clientId) return;
      try {
        const [clientData, organizationData] = await Promise.all([
          getClient(clientId),
          getOrganizations().catch(() => []),
        ]);
        if (!cancelled) {
          setClient(clientData || null);
          setOrganizations(Array.isArray(organizationData) ? organizationData : []);
        }
      } catch {
        if (!cancelled) {
          setClient(null);
          setOrganizations([]);
        }
      }
    }

    loadClient();
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  const send = useCallback((payload) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }, []);

  const showActionMessage = useCallback((message) => {
    setActionMessage(String(message || ""));
  }, []);

  const startStream = useCallback(() => {
    send(streamStartPayloadRef.current);
  }, [send]);

  const stopStream = useCallback(() => {
    send({ type: "stop_stream" });
  }, [send]);

  const connect = useCallback(async () => {
    if (!clientId) return;
    const attemptId = ++connectAttemptRef.current;

    const scheduleReconnect = (reason = "") => {
      if (attemptId !== connectAttemptRef.current || reconnectTimerRef.current) return;
      const delay = Math.min(1000 * (2 ** Math.min(reconnectAttemptRef.current, 4)), 10_000);
      reconnectAttemptRef.current += 1;
      setStatus(`${reason || "Forbindelse afbrudt"} · genopretter …`);
      reconnectTimerRef.current = window.setTimeout(() => {
        reconnectTimerRef.current = null;
        void connectRef.current?.();
      }, delay);
    };

    try {
      if (wsRef.current) {
        wsRef.current.close();
      }
    } catch {}

    setError("");
    setStatus("Forbinder...");
    setConnected(false);
    setAgentConnected(false);
    setKeyboardEnabled(false);
    setFrameSrc("");
    setLastFrameTs(null);
    setScreenSize({ width: null, height: null });
    setFileBrowserEntries([]);
    setFileBrowserPath("");
    setFileBrowserDisplayPath("");
    setFileBrowserParentPath("");
    setFileBrowserShortcuts([]);
    setFileBrowserError("");
    setFileDownloadStatus("");
    setFileDownloadingPath("");
    setFileOperationBusy(false);
    setFileOperationStatus("");
    setSelectedFilePaths([]);
    dragCounterRef.current = 0;
    fileBrowserPathRef.current = "";
    fileBrowserShowHiddenRef.current = false;
    setFileBrowserShowHidden(false);
    mouseDownRef.current = false;
    lastMouseMoveSentRef.current = 0;

    let ticket;
    try {
      ticket = await createBrowserWsTicket(clientId, "remote_desktop");
    } catch (err) {
      if (attemptId === connectAttemptRef.current) {
        setError(err?.message || "Kunne ikke oprette en sikker WebSocket-forbindelse.");
        scheduleReconnect("WebSocket-godkendelse fejlede");
      }
      return;
    }

    if (attemptId !== connectAttemptRef.current) return;

    let ws;
    try {
      ws = new WebSocket(
        getRemoteDesktopBrowserWsUrl(clientId),
        getBrowserWsProtocols(ticket)
      );
    } catch (err) {
      setError(err?.message || "Kunne ikke åbne WebSocket-forbindelsen.");
      setStatus("WebSocket-fejl");
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttemptRef.current = 0;
      setError("");
      setConnected(true);
      setStatus("Browser forbundet");
    };

    ws.onclose = (event) => {
      if (attemptId !== connectAttemptRef.current) return;
      setConnected(false);
      setAgentConnected(false);
      setKeyboardEnabled(false);
      scheduleReconnect(`Forbindelse lukket${event.reason ? `: ${event.reason}` : ""}`);
    };

    ws.onerror = () => {
      setError("WebSocket-fejl");
      setStatus("WebSocket-fejl");
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }

      if (msg.type === "hello") {
        setSessionId(msg.session_id);
        setAgentConnected(!!msg.agent_connected);
        const geometry = getRemoteScreenGeometryFromMessage(msg, true);
        if (geometry) {
          setScreenSize(geometry);
        }
        setStatus(msg.agent_connected ? "Remote desktop klar" : "Venter på klient-agent");
        if (msg.agent_connected) {
          setTimeout(() => startStream(), 200);
          setTimeout(() => {
            setFileBrowserLoading(true);
            send({ type: "file_list_request", path: "", show_hidden: fileBrowserShowHiddenRef.current });
          }, 350);
        }
        return;
      }

      if (msg.type === "agent_status") {
        setAgentConnected(!!msg.agent_connected);
        const geometry = getRemoteScreenGeometryFromMessage(msg, true);
        if (geometry) {
          setScreenSize(geometry);
        }
        setStatus(msg.agent_connected ? "Klient-agent forbundet" : "Klient-agent ikke forbundet");
        if (msg.agent_connected) {
          setTimeout(() => startStream(), 200);
          setTimeout(() => {
            setFileBrowserLoading(true);
            send({ type: "file_list_request", path: "", show_hidden: fileBrowserShowHiddenRef.current });
          }, 350);
        }
        return;
      }

      if (msg.type === "stream_started") {
        const geometry = getRemoteScreenGeometryFromMessage(msg, false);
        if (geometry) {
          setScreenSize(geometry);
        }
        const captureText = msg.width && msg.height ? `${msg.width}x${msg.height}` : remoteCaptureResolutionTextRef.current;
        const viewingText = geometry ? `${geometry.width}×${geometry.height}` : effectiveRemoteResolutionTextRef.current;
        setStatus(`Stream startet ${captureText}@${msg.fps || "?"}fps · visning ${viewingText}`);
        return;
      }

      if (msg.type === "frame") {
        setFrameSrc(`data:image/jpeg;base64,${msg.data}`);
        const geometry = getRemoteScreenGeometryFromMessage(msg, false);
        if (geometry) {
          setScreenSize(geometry);
          setStatus(`Stream aktiv ${geometry.width}x${geometry.height}@${msg.fps || "?"}fps · visning ${geometry.width}×${geometry.height}`);
        }
        setLastFrameTs(Date.now());
        return;
      }

      if (msg.type === "status") {
        setStatus(msg.message || "Status");
        return;
      }

      if (msg.type === "shout_result") {
        if (shoutAckTimerRef.current) {
          window.clearTimeout(shoutAckTimerRef.current);
          shoutAckTimerRef.current = null;
        }

        setShoutSending(false);

        if (msg.ok === false) {
          setError(msg.message || "Shout out fejlede på klienten.");
        } else {
          setError("");
          showActionMessage(msg.message || "Shout out vist på klienten");
        }
        return;
      }

      if (msg.type === "file_upload_result") {
        if (msg.ok === false) setTransferError(msg.message || "Filoverførsel fejlede på klienten.");
        return;
      }

      if (msg.type === "file_list_result") {
        setFileBrowserLoading(false);
        if (msg.ok === false) {
          setFileBrowserError(msg.message || "Kunne ikke læse filer på klienten.");
          setFileBrowserEntries([]);
        } else {
          setFileBrowserError("");
          fileBrowserPathRef.current = msg.path || "";
          setFileBrowserPath(msg.path || "");
          setFileBrowserDisplayPath(msg.display_path || msg.home_path || "");
          setFileBrowserParentPath(msg.parent_path || "");
          setFileBrowserShortcuts(Array.isArray(msg.shortcuts) ? msg.shortcuts : []);
          setFileBrowserEntries(Array.isArray(msg.entries) ? msg.entries : []);
          setSelectedFilePaths([]);
          if (typeof msg.show_hidden === "boolean") {
            fileBrowserShowHiddenRef.current = msg.show_hidden;
            setFileBrowserShowHidden(msg.show_hidden);
          }
        }
        return;
      }

      if (msg.type === "file_download_result") {
        if (msg.ok === false) {
          setFileDownloadingPath("");
          setFileDownloadStatus("");
          setFileBrowserError(msg.message || "Download fra klient fejlede.");
        } else if (msg.status === "uploading") {
          setFileDownloadStatus(msg.message || "Klient-agenten forbereder filen...");
        }
        return;
      }

      if (msg.type === "file_download_ready") {
        const transferId = msg.transfer_id;
        const filename = msg.filename || "download.bin";
        setFileDownloadStatus(`Downloader ${filename} fra backend...`);

        (async () => {
          try {
            const res = await fetch(buildRemoteDesktopBrowserDownloadUrl(apiUrl, clientId, transferId), {
              credentials: "include",
              headers: authHeaders(),
            });
            if (!res.ok) {
              let detail = "Download fejlede";
              try {
                const data = await res.json();
                detail = data?.detail || data?.message || detail;
              } catch {}
              throw new Error(detail);
            }
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
            setFileBrowserError("");
            setFileDownloadStatus("");
            setFileOperationStatus(`Download klar: ${filename}`);
            setSelectedFilePaths([]);
          } catch (err) {
            setFileBrowserError(err?.message || "Download fejlede");
            setFileDownloadStatus("");
          } finally {
            setFileDownloadingPath("");
          }
        })();
        return;
      }

      if (msg.type === "file_delete_result" && pendingDeleteCountRef.current > 0) {
        pendingDeleteCountRef.current = Math.max(0, pendingDeleteCountRef.current - 1);
        if (msg.ok === false) {
          pendingDeleteErrorsRef.current.push(msg.message || "Sletning fejlede.");
        }

        if (pendingDeleteCountRef.current > 0) {
          setFileOperationStatus(`Sletter valgte elementer... ${pendingDeleteCountRef.current} tilbage`);
          return;
        }

        setFileOperationBusy(false);
        setSelectedFilePaths([]);
        if (pendingDeleteErrorsRef.current.length > 0) {
          setFileBrowserError(pendingDeleteErrorsRef.current[0]);
          setFileOperationStatus("");
          pendingDeleteErrorsRef.current = [];
        } else {
          setFileBrowserError("");
          const deletedTotal = Math.max(1, Number(pendingDeleteTotalRef.current || 1));
          setFileOperationStatus(`${deletedTotal} element(er) slettet permanent.`);
        }
        pendingDeleteTotalRef.current = 0;
        send({ type: "file_list_request", path: fileBrowserPathRef.current || "", show_hidden: fileBrowserShowHiddenRef.current });
        return;
      }

      if (["file_delete_result", "file_rename_result", "file_mkdir_result", "file_move_result"].includes(msg.type)) {
        setFileOperationBusy(false);
        if (msg.ok === false) {
          setFileBrowserError(msg.message || "Filhandling fejlede.");
          setFileOperationStatus("");
        } else {
          setFileBrowserError("");
          const successMessage =
            msg.type === "file_delete_result"
              ? "Elementet er slettet permanent."
              : msg.type === "file_rename_result"
              ? "Elementet er omdøbt."
              : msg.type === "file_mkdir_result"
              ? "Mappen er oprettet."
              : msg.type === "file_move_result"
              ? "Elementet er flyttet."
              : "Filhandling gennemført.";
          setFileOperationStatus(successMessage);
          send({ type: "file_list_request", path: fileBrowserPathRef.current || "", show_hidden: fileBrowserShowHiddenRef.current });
        }
        return;
      }

      if (msg.type === "remote_error" || msg.type === "error") {
        setError(msg.message || "Ukendt fejl");
        if (String(msg.message || "").toLowerCase().includes("shout")) {
          setShoutSending(false);
        }
        return;
      }
    };
  }, [
    clientId,
    send,
    startStream,
    showActionMessage,
    setFileOperationStatus,
  ]);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    connectRef.current = connect;
    void connect();
    return () => {
      connectAttemptRef.current += 1;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (shoutAckTimerRef.current) {
        window.clearTimeout(shoutAckTimerRef.current);
        shoutAckTimerRef.current = null;
      }
      try {
        wsRef.current?.send(JSON.stringify({ type: "stop_stream" }));
        wsRef.current?.close();
      } catch {}
    };
  }, [connect]);

  useEffect(() => {
    if (!lastFrameTs) return undefined;
    const timer = window.setInterval(() => {
      setFrameAgeTick((prev) => prev + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [lastFrameTs]);

  const frameAgeText = (() => {
    if (!lastFrameTs) return "";
    const sec = Math.max(0, Math.round((Date.now() - lastFrameTs) / 1000));
    return sec <= 1 ? "seneste frame nu" : `seneste frame ${sec}s siden`;
  })();

  const getRemoteCoordinates = useCallback((event) => {
    const img = imgRef.current;
    if (!img || !effectiveRemoteResolution.width || !effectiveRemoteResolution.height) return null;

    const rect = img.getBoundingClientRect();
    const px = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    const py = clamp((event.clientY - rect.top) / rect.height, 0, 1);

    return {
      x: Math.round(px * effectiveRemoteResolution.width),
      y: Math.round(py * effectiveRemoteResolution.height),
    };
  }, [effectiveRemoteResolution]);

  const focusRemoteDesktop = useCallback(() => {
    try {
      containerRef.current?.focus();
    } catch {}
  }, []);

  const sendMouseEvent = useCallback((event, action, extra = {}) => {
    if (!canControl) return;
    const pos = getRemoteCoordinates(event);
    if (!pos) return;

    send({
      type: "mouse",
      action,
      ...pos,
      ...extra,
    });
  }, [canControl, getRemoteCoordinates, send]);

  const handleMouseDown = useCallback((event) => {
    if (!canControl) return;
    event.preventDefault();
    event.stopPropagation();
    focusRemoteDesktop();

    const button = event.button === 2 ? 3 : 1;
    mouseDownRef.current = button === 1;

    sendMouseEvent(event, "down", { button });
  }, [canControl, focusRemoteDesktop, sendMouseEvent]);

  const handleMouseUp = useCallback((event) => {
    if (!canControl) return;
    event.preventDefault();
    event.stopPropagation();

    const button = event.button === 2 ? 3 : 1;
    sendMouseEvent(event, "up", { button });

    if (button === 1) {
      mouseDownRef.current = false;
    }
  }, [canControl, sendMouseEvent]);

  const handleDoubleClick = useCallback((event) => {
    if (!canControl) return;
    event.preventDefault();
    event.stopPropagation();
    sendMouseEvent(event, "double_click");
  }, [canControl, sendMouseEvent]);

  const handleContextMenu = useCallback((event) => {
    event.preventDefault();
    if (!canControl) return;
    event.stopPropagation();
    sendMouseEvent(event, "right_click");
  }, [canControl, sendMouseEvent]);

  const handleMouseMove = useCallback((event) => {
    if (!canControl) return;
    const pos = getRemoteCoordinates(event);
    if (!pos) return;

    const now = Date.now();
    const throttleMs = mouseDownRef.current ? 25 : 80;
    if (now - lastMouseMoveSentRef.current < throttleMs) return;
    lastMouseMoveSentRef.current = now;

    send({
      type: "mouse",
      action: "move",
      ...pos,
      dragging: mouseDownRef.current,
    });
  }, [canControl, getRemoteCoordinates, send]);

  const handleMouseLeave = useCallback((event) => {
    if (!canControl) return;
    if (!mouseDownRef.current) return;

    // Hvis musen forlader billedet mens venstre knap er nede, slipper vi den
    // på klienten, så et vindue ikke bliver ved med at hænge fast.
    sendMouseEvent(event, "up", { button: 1 });
    mouseDownRef.current = false;
  }, [canControl, sendMouseEvent]);

  const handleWheel = useCallback((event) => {
    if (!canControl) return;
    event.preventDefault();
    send({
      type: "mouse",
      action: "scroll",
      delta: event.deltaY < 0 ? 3 : -3,
    });
  }, [canControl, send]);

  const sendShout = useCallback(() => {
    const message = shoutText.trim();
    if (!message || shoutSending) return;

    if (!canControl) {
      setError("Shout out kan ikke sendes endnu: remote desktop er ikke klar.");
      return;
    }

    setError("");
    setShoutSending(true);

    const ok = send({
      type: "shout",
      text: message,
      duration: 8,
    });

    if (!ok) {
      setShoutSending(false);
      setError("Shout out kunne ikke sendes: WebSocket er ikke forbundet.");
      return;
    }

    showActionMessage("Shout out sendt til klient-agenten");
    setShoutText("");

    if (shoutAckTimerRef.current) {
      window.clearTimeout(shoutAckTimerRef.current);
    }

    shoutAckTimerRef.current = window.setTimeout(() => {
      setShoutSending(false);
      setError("Shout out blev sendt, men klient-agenten kvitterede ikke. Tjek klientloggen.");
      shoutAckTimerRef.current = null;
    }, 6000);
  }, [canControl, send, shoutSending, shoutText, showActionMessage]);


  const getTransferFileKey = useCallback((file) => {
    return [file?.name || "", file?.size || 0, file?.lastModified || 0].join("::");
  }, []);

  const selectTransferFiles = useCallback((filesLike) => {
    const incomingFiles = Array.from(filesLike || []).filter(Boolean);
    if (!incomingFiles.length) return;

    setTransferError("");
    setTransferStatus("");

    setTransferFiles((prevFiles) => {
      const existingKeys = new Set(Array.from(prevFiles || []).map(getTransferFileKey));
      const nextFiles = [...(prevFiles || [])];
      let skippedDuplicates = 0;

      incomingFiles.forEach((file) => {
        const key = getTransferFileKey(file);
        if (existingKeys.has(key)) {
          skippedDuplicates += 1;
          return;
        }
        existingKeys.add(key);
        nextFiles.push(file);
      });

      const totalSize = sumFileSizes(nextFiles);
      if (totalSize > UPLOAD_TOTAL_LIMIT_BYTES) {
        setTransferError(`Samlet upload er for stor. Maksimum er ${formatBytes(UPLOAD_TOTAL_LIMIT_BYTES)} i alt.`);
      } else if (nextFiles.length) {
        const duplicateText = skippedDuplicates ? ` · ${skippedDuplicates} dublet(ter) sprunget over` : "";
        setTransferStatus(`${nextFiles.length} fil(er) i uploadlisten · ${formatBytes(totalSize)} / ${formatBytes(UPLOAD_TOTAL_LIMIT_BYTES)}${duplicateText}`);
      }

      return nextFiles;
    });
  }, [getTransferFileKey, setTransferStatus]);

  const removeTransferFileAt = useCallback((indexToRemove) => {
    setTransferFiles((prevFiles) => Array.from(prevFiles || []).filter((_, index) => index !== indexToRemove));
    setTransferError("");
    setTransferStatus("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const clearTransferFiles = useCallback(() => {
    setTransferFiles([]);
    setTransferStatus("");
    setTransferError("");
    if (fileInputRef.current) fileInputRef.current.value = "";
  }, []);

  const handleUploadDrop = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    dragCounterRef.current = 0;
    setDragOverUpload(false);

    if (!canControl || transferUploading) return;

    const files = event.dataTransfer?.files;
    if (!files || !files.length) return;
    selectTransferFiles(files);
  }, [canControl, selectTransferFiles, transferUploading]);

  const handleUploadDragEnter = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!canControl || transferUploading) return;
    dragCounterRef.current += 1;
    setDragOverUpload(true);
  }, [canControl, transferUploading]);

  const handleUploadDragOver = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!canControl || transferUploading) return;
    setDragOverUpload(true);
  }, [canControl, transferUploading]);

  const handleUploadDragLeave = useCallback((event) => {
    event.preventDefault();
    event.stopPropagation();
    dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
    if (dragCounterRef.current === 0) {
      setDragOverUpload(false);
    }
  }, []);


  const uploadFilesToClient = useCallback(async (conflictStrategiesByIndex = {}) => {
    const originalFiles = Array.from(transferFiles || []);
    if (!originalFiles.length || transferUploading) return;

    if (!canControl) {
      setTransferError("Filoverførsel kan ikke starte endnu: remote desktop er ikke klar.");
      return;
    }

    const filesWithStrategies = originalFiles.map((file, index) => ({
      file,
      index,
      strategy: conflictStrategiesByIndex[index] || "keep_both",
    }));

    const filesToUpload = filesWithStrategies.filter((item) => item.strategy !== "skip");

    if (!filesToUpload.length) {
      clearTransferFiles();
      setTransferStatus("Ingen filer blev uploadet — konflikter blev sprunget over.");
      return;
    }

    const totalSize = sumFileSizes(filesToUpload.map((item) => item.file));
    if (totalSize > UPLOAD_TOTAL_LIMIT_BYTES) {
      setTransferError(`Samlet upload er for stor. Maksimum er ${formatBytes(UPLOAD_TOTAL_LIMIT_BYTES)} i alt.`);
      return;
    }

    const formData = new FormData();
    formData.append("session_id", sessionId);
    formData.append("destination_path", fileBrowserPathRef.current || "");
    formData.append("conflict_strategies_json", JSON.stringify(filesToUpload.map((item) => item.strategy)));
    filesToUpload.forEach(({ file }) => formData.append("files", file));

    setTransferUploading(true);
    setTransferError("");
    setTransferStatus(`Uploader ${filesToUpload.length} fil(er) til aktuel mappe${fileBrowserDisplayPath ? `: ${fileBrowserDisplayPath}` : ""}...`);

    try {
      const res = await fetch(buildRemoteDesktopUploadMultipleUrl(apiUrl, clientId), {
        method: "POST",
        credentials: "include",
        headers: authHeaders(),
        body: formData,
      });

      let data = {};
      try {
        data = await res.json();
      } catch {
        data = {};
      }

      if (!res.ok) {
        throw new Error(data?.detail || data?.message || "Upload fejlede");
      }

      const expectedCount = Number(data?.count || filesToUpload.length || 1);
      setTransferUploading(false);
      setTransferFiles([]);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setTransferStatus("");
      setFileOperationStatus(data?.message || `${expectedCount} fil(er) uploadet til klienten.`);
      send({
        type: "file_list_request",
        path: data?.destination_path ?? fileBrowserPathRef.current ?? "",
        show_hidden: fileBrowserShowHiddenRef.current,
      });
    } catch (err) {
      setTransferUploading(false);
      setTransferStatus("");
      setTransferError(err?.message || "Upload fejlede");
    }
  }, [canControl, clearTransferFiles, clientId, fileBrowserDisplayPath, send, sessionId, setTransferStatus, transferFiles, transferUploading]);

  const beginUploadFilesToClient = useCallback((conflictStrategiesByIndex = {}) => {
    if (!Array.from(transferFiles || []).length || transferUploading) return;

    // Ingen konflikt-dialog: eventuelle konflikter håndteres fra uploadlisten.
    // Default er stadig keep_both, så eksisterende filer beskyttes.
    uploadFilesToClient(conflictStrategiesByIndex || {});
  }, [transferFiles, transferUploading, uploadFilesToClient]);


  const requestFileList = useCallback((path = fileBrowserPath, showHidden = fileBrowserShowHiddenRef.current) => {
    if (!canControl) {
      setFileBrowserError("Filbrowser kan ikke læses endnu: remote desktop er ikke klar.");
      return;
    }
    fileBrowserShowHiddenRef.current = !!showHidden;
    setFileBrowserShowHidden(!!showHidden);
    setFileBrowserLoading(true);
    setFileBrowserError("");
    setFileOperationStatus("");
    send({ type: "file_list_request", path: path || "", show_hidden: !!showHidden });
  }, [canControl, fileBrowserPath, send]);

  const requestFileDownload = useCallback((entry) => {
    if (!canControl || !entry) return;
    if (entry.is_dir) {
      setFileBrowserError("Mappedownload understøttes ikke af Remote Desktop v2-filområdet.");
      return;
    }
    setFileBrowserError("");
    setFileDownloadingPath(entry.relative_path || "");
    setFileDownloadStatus(`Forbereder download: ${entry.name}`);
    const ok = send({ type: "file_download_request", path: entry.relative_path || "" });
    if (!ok) {
      setFileDownloadingPath("");
      setFileDownloadStatus("");
      setFileBrowserError("Kunne ikke sende download-request til klient-agenten.");
    }
  }, [canControl, send]);

  const selectedPathSet = useMemo(() => new Set(selectedFilePaths), [selectedFilePaths]);

  const toggleFileSelection = useCallback((entry) => {
    const path = entry?.relative_path || "";
    if (!path) return;
    setSelectedFilePaths((prev) => (
      prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]
    ));
  }, []);

  const requestSelectedDelete = useCallback(() => {
    const paths = selectedFilePaths.filter(Boolean);
    if (!canControl || fileOperationBusy || !paths.length) return;
    const okConfirm = window.confirm(`Er du sikker på, at du vil slette ${paths.length} valgte element(er) permanent?`);
    if (!okConfirm) return;

    pendingDeleteCountRef.current = paths.length;
    pendingDeleteTotalRef.current = paths.length;
    pendingDeleteErrorsRef.current = [];
    setFileBrowserError("");
    setFileOperationStatus(`Sletter ${paths.length} valgte element(er) permanent...`);
    setFileOperationBusy(true);

    let sent = 0;
    paths.forEach((path) => {
      const ok = send({ type: "file_delete_request", path });
      if (ok) sent += 1;
    });

    if (sent !== paths.length) {
      pendingDeleteCountRef.current = sent;
      pendingDeleteTotalRef.current = sent;
      if (sent === 0) {
        setFileOperationBusy(false);
        pendingDeleteTotalRef.current = 0;
        setFileOperationStatus("");
        setFileBrowserError("Kunne ikke sende slette-request til klient-agenten.");
      } else {
        pendingDeleteErrorsRef.current.push("Nogle slet-requests kunne ikke sendes.");
      }
    }
  }, [canControl, fileOperationBusy, selectedFilePaths, send]);


  const requestCreateFolder = useCallback(() => {
    if (!canControl || fileOperationBusy) return;
    const name = window.prompt("Navn på ny mappe:");
    if (!name || !name.trim()) return;
    setFileBrowserError("");
    setFileOperationStatus("Opretter mappe...");
    setFileOperationBusy(true);
    const ok = send({ type: "file_mkdir_request", path: fileBrowserPathRef.current || "", name: name.trim() });
    if (!ok) {
      setFileOperationBusy(false);
      setFileOperationStatus("");
      setFileBrowserError("Kunne ikke sende opret-mappe request til klient-agenten.");
    }
  }, [canControl, fileOperationBusy, send]);

  const requestRenameEntry = useCallback((entry, explicitName = null) => {
    if (!canControl || fileOperationBusy || !entry) return;
    const rawName = explicitName !== null && explicitName !== undefined
      ? String(explicitName)
      : window.prompt("Nyt navn:", entry.name || "");
    const nextName = String(rawName || "").trim();
    if (!nextName || nextName === entry.name) return;
    setFileBrowserError("");
    setFileOperationStatus(`Omdøber ${entry.name}...`);
    setFileOperationBusy(true);
    const ok = send({ type: "file_rename_request", path: entry.relative_path || "", new_name: nextName });
    if (!ok) {
      setFileOperationBusy(false);
      setFileOperationStatus("");
      setFileBrowserError("Kunne ikke sende omdøb request til klient-agenten.");
    }
  }, [canControl, fileOperationBusy, send]);

  const requestDeleteEntry = useCallback((entry) => {
    if (!canControl || fileOperationBusy || !entry) return;
    const label = entry.is_dir ? "mappen" : "filen";
    const okConfirm = window.confirm(`Er du sikker på, at du vil slette ${label} "${entry.name}" permanent?`);
    if (!okConfirm) return;
    setFileBrowserError("");
    setFileOperationStatus(`Sletter ${entry.name} permanent...`);
    setFileOperationBusy(true);
    const ok = send({ type: "file_delete_request", path: entry.relative_path || "" });
    if (!ok) {
      setFileOperationBusy(false);
      setFileOperationStatus("");
      setFileBrowserError("Kunne ikke sende slette-request til klient-agenten.");
    }
  }, [canControl, fileOperationBusy, send]);
  const requestMoveEntries = useCallback((paths, destinationEntry) => {
    const selectedPaths = Array.from(paths || []).map((path) => String(path || "").trim()).filter(Boolean);
    const destinationPath = String(destinationEntry?.relative_path || destinationEntry || "").trim();
    if (!canControl || fileOperationBusy || !selectedPaths.length || !destinationPath) return;

    setFileBrowserError("");
    setFileOperationStatus(`Flytter ${selectedPaths.length} element(er)...`);
    setFileOperationBusy(true);

    const ok = send({
      type: "file_move_request",
      paths: selectedPaths,
      destination_path: destinationPath,
    });

    if (!ok) {
      setFileOperationBusy(false);
      setFileOperationStatus("");
      setFileBrowserError("Kunne ikke sende flyt-request til klient-agenten.");
    }
  }, [canControl, fileOperationBusy, send]);

  const requestFullscreen = useCallback(() => {
    const el = containerRef.current;
    if (el?.requestFullscreen) el.requestFullscreen();
  }, []);

  const handleRemoteKeyDown = useCallback((event) => {
    if (!keyboardEnabled || !canControl) return;

    const targetTag = String(event.target?.tagName || "").toLowerCase();
    if (["input", "textarea", "select"].includes(targetTag)) return;

    // Remote keyboard capture owns supported keys while enabled. Unsupported
    // browser/system keys are intentionally swallowed instead of reaching the
    // fixed-function input broker.
    event.preventDefault();
    event.stopPropagation();

    const action = getRemoteKeyboardAction(event, keyboardMode);
    if (!action) return;

    send(action);
  }, [keyboardEnabled, canControl, keyboardMode, send]);

  const remoteScreenPanel = (
    <Stack spacing={1.2} sx={{ minWidth: 0 }}>
      <Paper
        ref={containerRef}
        elevation={0}
        tabIndex={0}
        onKeyDown={handleRemoteKeyDown}
        onClick={focusRemoteDesktop}
        sx={{
          bgcolor: "rgba(2,6,23,0.92)",
          p: { xs: 1, md: 1.35 },
          borderRadius: 2,
          overflow: "auto",
          minHeight: { xs: 360, md: 560 },
          border: "1px solid rgba(148,163,184,0.16)",
          boxShadow: "0 24px 80px rgba(0,0,0,0.28)",
          outline: keyboardEnabled ? "2px solid" : "none",
          outlineColor: keyboardEnabled ? "primary.main" : "transparent",
        }}
      >
        {!frameSrc ? (
          <Box
            sx={{
              width: "100%",
              aspectRatio: effectiveRemoteAspectRatio,
              minHeight: { xs: 260, md: 420 },
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "white",
              bgcolor: "rgba(0,0,0,0.55)",
              borderRadius: 2,
            }}
          >
            <Stack spacing={2} sx={{
              alignItems: "center"
            }}>
              <CircularProgress color="inherit" />
              <Typography>{status}</Typography>
              <Typography variant="body2" sx={{ opacity: 0.75 }}>
                Forventet skærmstørrelse: {effectiveRemoteResolutionText} · stream: {remoteCaptureResolutionText}
              </Typography>
            </Stack>
          </Box>
        ) : (
          <Box sx={{ display: "flex", justifyContent: "center", alignItems: "flex-start", width: "100%" }}>
            <Tooltip title="Venstreklik, højreklik og scroll sendes til klienten">
              <Box
                sx={{
                  width: "100%",
                  maxWidth: effectiveRemoteResolution.width ? `${effectiveRemoteResolution.width}px` : "100%",
                  aspectRatio: effectiveRemoteAspectRatio,
                  bgcolor: "#000",
                  borderRadius: 1,
                  overflow: "hidden",
                }}
              >
                <Box
                  component="img"
                  ref={imgRef}
                  src={frameSrc}
                  alt="Remote desktop"
                  onMouseDown={handleMouseDown}
                  onMouseUp={handleMouseUp}
                  onDoubleClick={handleDoubleClick}
                  onContextMenu={handleContextMenu}
                  onMouseMove={handleMouseMove}
                  onMouseLeave={handleMouseLeave}
                  onWheel={handleWheel}
                  sx={{
                    width: "100%",
                    height: "100%",
                    objectFit: "contain",
                    cursor: canControl ? "crosshair" : "not-allowed",
                    userSelect: "none",
                    touchAction: "none",
                    display: "block",
                  }}
                  draggable={false}
                />
              </Box>
            </Tooltip>
          </Box>
        )}
      </Paper>

      <Stack direction={{ xs: "column", md: "row" }} spacing={1.2} sx={{
        alignItems: { xs: "stretch", md: "center" }
      }}>
        <Typography
          variant="body2"
          sx={{
            color: "text.secondary",
            flex: 1
          }}>
          {status}
          {` · ${effectiveRemoteResolutionText}`}
          {frameAgeText ? ` · ${frameAgeText}` : ""}
        </Typography>
        <Button onClick={startStream} disabled={!connected || !agentConnected} variant="outlined">
          Start stream
        </Button>
        <Button onClick={stopStream} disabled={!connected || !agentConnected} variant="outlined" color="inherit">
          Stop stream
        </Button>
      </Stack>
    </Stack>
  );

  const shoutPanel = (
    <Paper
      elevation={0}
      sx={{
        p: { xs: 1.5, md: 2 },
        borderRadius: 2,
        bgcolor: "rgba(15,23,42,0.74)",
        border: "1px solid rgba(148,163,184,0.16)",
        boxShadow: "0 18px 60px rgba(0,0,0,0.20)",
      }}
    >
      <Stack spacing={1.5}>
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 900 }}>
            Shout out
          </Typography>
          <Typography variant="body2" sx={{
            color: "text.secondary"
          }}>
            Sender en midlertidig besked direkte til klientens skærm.
          </Typography>
        </Box>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
          <TextField
            label="Shout out besked"
            value={shoutText}
            onChange={(e) => setShoutText(e.target.value)}
            size="small"
            fullWidth
            disabled={!canControl}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Enter") {
                e.preventDefault();
                sendShout();
              }
            }}
            slotProps={{
              htmlInput: { maxLength: 120 }
            }}
          />
          <Button disabled={!canControl || !shoutText.trim() || shoutSending} variant="contained" color="warning" onClick={sendShout}>
            {shoutSending ? <CircularProgress size={18} color="inherit" /> : "Send"}
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );

  const clientName = client?.name || client?.client_name || client?.hostname || client?.display_name || `Klient ${clientId || ""}`.trim();
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

  return (
    <Container maxWidth="xl" sx={{ py: { xs: 2, md: 3 }, color: "#f8fafc" }}>
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.2} sx={{
          alignItems: { xs: "stretch", md: "center" }
        }}>
          <Typography variant="h5" sx={{ flex: 1, fontWeight: 800 }}>
            Remote Desktop
          </Typography>

          <Chip label={connected ? "Browser forbundet" : "Browser ikke forbundet"} sx={compactDarkChipSx(connected ? "success" : "neutral")} />
          <Chip label={agentConnected ? "Klient-agent forbundet" : "Venter på klient-agent"} sx={compactDarkChipSx(agentConnected ? "success" : "warning")} />

          <Button onClick={connect} startIcon={<RefreshIcon />} variant="outlined">Genforbind</Button>
          <Button onClick={requestFullscreen} startIcon={<FullscreenIcon />} variant="outlined">Fuld skærm</Button>
          <Button
            disabled={!canControl}
            onClick={() => {
              setKeyboardEnabled((prev) => !prev);
              setTimeout(focusRemoteDesktop, 50);
            }}
            startIcon={<KeyboardIcon />}
            variant={keyboardEnabled ? "contained" : "outlined"}
            color={keyboardEnabled ? "success" : "inherit"}
          >
            {keyboardEnabled ? "Tastatur aktivt" : "Aktivér tastatur"}
          </Button>
          <Tooltip title="Oversæt Mac-genveje til Ubuntu. Printable Option/AltGr-tegn sendes fortsat som Unicode-tekst.">
            <Button
              onClick={() => {
                setKeyboardMode((prev) =>
                  prev === REMOTE_KEYBOARD_MODE_MAC
                    ? REMOTE_KEYBOARD_MODE_STANDARD
                    : REMOTE_KEYBOARD_MODE_MAC
                );
                setTimeout(focusRemoteDesktop, 50);
              }}
              variant={keyboardMode === REMOTE_KEYBOARD_MODE_MAC ? "contained" : "outlined"}
              color={keyboardMode === REMOTE_KEYBOARD_MODE_MAC ? "secondary" : "inherit"}
            >
              {keyboardMode === REMOTE_KEYBOARD_MODE_MAC
                ? "Mac → Ubuntu: Til"
                : "Mac → Ubuntu: Fra"}
            </Button>
          </Tooltip>
        </Stack>

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
              <Typography variant="h6" sx={{ fontWeight: 950, lineHeight: 1.1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={clientName}>
                {clientName}
              </Typography>
            </Box>
            <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", rowGap: 0.75 }}>
              <Chip label={`Organisation: ${organizationName}`} sx={compactDarkChipSx("neutral")} />
              <Chip label={`ID: ${clientId || "Ukendt"}`} sx={compactDarkChipSx("neutral")} />
              <Chip label={`Lokation: ${clientLocation}`} sx={compactDarkChipSx("neutral")} />
            </Stack>
          </Stack>
        </Paper>

        <Paper
          elevation={0}
          sx={{
            p: 0.6,
            borderRadius: 2,
            bgcolor: "rgba(15,23,42,0.58)",
            border: "1px solid rgba(148,163,184,0.14)",
            display: "flex",
            gap: 0.6,
            flexWrap: "wrap",
          }}
        >
          <Button
            variant={activeTab === "desktop" ? "contained" : "text"}
            color={activeTab === "desktop" ? "primary" : "inherit"}
            onClick={() => setActiveTab("desktop")}
          >
            Remote Desktop
          </Button>
          <Button
            variant={activeTab === "files" ? "contained" : "text"}
            color={activeTab === "files" ? "primary" : "inherit"}
            onClick={() => setActiveTab("files")}
          >
            Filer
          </Button>
        </Paper>

        <AppSnackbar
          open={Boolean(actionMessage)}
          message={actionMessage}
          severity="success"
          onClose={() => setActionMessage("")}
        />
        <AppSnackbar
          open={Boolean(error)}
          message={error}
          severity="error"
          onClose={() => setError("")}
        />

        {activeTab === "desktop" ? (
          <Stack spacing={2}>
            {remoteScreenPanel}
            {shoutPanel}
          </Stack>
        ) : (
          <RemoteDesktopFileManager
            canControl={canControl}
            fileInputRef={fileInputRef}
            dragOverUpload={dragOverUpload}
            fileBrowserPath={fileBrowserPath}
            fileBrowserDisplayPath={fileBrowserDisplayPath}
            fileBrowserParentPath={fileBrowserParentPath}
            fileBrowserShortcuts={fileBrowserShortcuts}
            fileBrowserEntries={fileBrowserEntries}
            fileBrowserLoading={fileBrowserLoading}
            fileBrowserShowHidden={fileBrowserShowHidden}
            fileBrowserError={fileBrowserError}
            fileDownloadStatus={fileDownloadStatus}
            fileDownloadingPath={fileDownloadingPath}
            fileOperationBusy={fileOperationBusy}
            fileOperationStatus={fileOperationStatus}
            selectedFilePaths={selectedFilePaths}
            selectedPathSet={selectedPathSet}
            transferFiles={transferFiles}
            transferUploading={transferUploading}
            transferStatus={transferStatus}
            transferError={transferError}
            uploadLimitBytes={UPLOAD_TOTAL_LIMIT_BYTES}
            onClearFileBrowserError={() => setFileBrowserError("")}
            onClearFileDownloadStatus={() => setFileDownloadStatus("")}
            onClearFileOperationStatus={() => setFileOperationStatus("")}
            onClearTransferError={() => setTransferError("")}
            onClearTransferStatus={() => setTransferStatus("")}
            onClearSelected={() => setSelectedFilePaths([])}
            onSetSelectedPaths={(paths) => setSelectedFilePaths(Array.isArray(paths) ? paths : [])}
            onRequestFileList={requestFileList}
            onRequestSelectedDelete={requestSelectedDelete}
            onRequestFileDownload={requestFileDownload}
            onRequestCreateFolder={requestCreateFolder}
            onRequestRenameEntry={requestRenameEntry}
            onRequestDeleteEntry={requestDeleteEntry}
            onRequestMoveEntries={requestMoveEntries}
            onToggleFileSelection={toggleFileSelection}
            onSelectTransferFiles={selectTransferFiles}
            onUploadFilesToClient={beginUploadFilesToClient}
            onClearTransferFiles={clearTransferFiles}
            onRemoveTransferFile={removeTransferFileAt}
            onUploadDrop={handleUploadDrop}
            onUploadDragEnter={handleUploadDragEnter}
            onUploadDragOver={handleUploadDragOver}
            onUploadDragLeave={handleUploadDragLeave}
          />
        )}

      </Stack>
    </Container>
  );
}
