import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from "@mui/material";
import FullscreenIcon from "@mui/icons-material/Fullscreen";
import GridViewIcon from "@mui/icons-material/GridView";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { Link } from "react-router-dom";
import { apiUrl, authHeaders, authenticatedFetch, getControlRoomClients } from "../../api";
import { compactDarkChipSx } from "../../utils/chipStyles";

const VIEWER_HEARTBEAT_MS = 25_000;
const PAGE_HIDDEN_WARM_GRACE_MS = 30_000;
const HEALTH_STARTUP_POLL_MS = 2_000;

function isRequestTimeout(error) {
  return error?.name === "TimeoutError" || /signal.*timed out|timeout/i.test(String(error?.message || ""));
}

function formatLatency(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return "måler …";
  return `${value.toFixed(1).replace(".", ",")} sek.`;
}

function makeViewerId(clientId) {
  const suffix = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `livestream-wall-${clientId}-${suffix}`.slice(0, 120);
}

async function sendViewerLeave(clientId, viewerId, source = "livestream_wall_leave") {
  if (!clientId || !viewerId) return;
  try {
    await fetch(`${apiUrl}/api/livestream-v2/hls/${encodeURIComponent(clientId)}/viewer-leave`, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: {
        ...authHeaders(),
        "Content-Type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({ viewer_id: viewerId, source }),
    });
  } catch {
    // Best effort: backend lease remains the crash/reload recovery path.
  }
}

function LivestreamTile({ client, pageMediaActive }) {
  const rootRef = useRef(null);
  const previewRef = useRef(null);
  const videoRef = useRef(null);
  const hlsRef = useRef(null);
  const heartbeatTimerRef = useRef(null);
  const healthTimerRef = useRef(null);
  const viewerIdRef = useRef(makeViewerId(client.id));
  const mediaCapabilityRef = useRef("");
  const activeRef = useRef(false);

  const [intersecting, setIntersecting] = useState(false);
  const [state, setState] = useState("idle");
  const [message, setMessage] = useState("");
  const [activeViewers, setActiveViewers] = useState(null);
  const [latencySeconds, setLatencySeconds] = useState(null);

  const clientOnline = client?.presence?.is_online === true;
  const shouldRun = Boolean(pageMediaActive && intersecting && clientOnline);

  const updateLatency = useCallback(() => {
    const video = videoRef.current;
    let measured = Number(hlsRef.current?.latency);
    if ((!Number.isFinite(measured) || measured < 0) && video?.seekable?.length) {
      try {
        measured = Math.max(0, Number(video.seekable.end(video.seekable.length - 1)) - Number(video.currentTime));
      } catch {
        measured = Number.NaN;
      }
    }
    if (Number.isFinite(measured) && measured >= 0) setLatencySeconds(measured);
  }, []);

  const handleFullscreen = useCallback(async () => {
    const element = previewRef.current;
    if (!element) return;
    try {
      if (document.fullscreenElement === element) {
        await document.exitFullscreen?.();
      } else if (element.requestFullscreen) {
        await element.requestFullscreen();
      } else if (element.webkitRequestFullscreen) {
        element.webkitRequestFullscreen();
      }
    } catch {
      setMessage("Browseren kunne ikke åbne preview i fuld skærm.");
    }
  }, []);

  const destroyPlayer = useCallback(() => {
    if (hlsRef.current) {
      try { hlsRef.current.destroy(); } catch {}
      hlsRef.current = null;
    }
    setLatencySeconds(null);
    const video = videoRef.current;
    if (video) {
      try {
        video.pause();
        video.removeAttribute("src");
        video.load();
      } catch {}
    }
  }, []);

  const stopLocalWork = useCallback((leave = true) => {
    if (heartbeatTimerRef.current) {
      window.clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
    if (healthTimerRef.current) {
      window.clearTimeout(healthTimerRef.current);
      healthTimerRef.current = null;
    }
    destroyPlayer();
    if (leave && activeRef.current) {
      activeRef.current = false;
      void sendViewerLeave(client.id, viewerIdRef.current, "livestream_wall_inactive");
    }
  }, [client.id, destroyPlayer]);

  useEffect(() => {
    const node = rootRef.current;
    if (!node || typeof IntersectionObserver === "undefined") {
      setIntersecting(true);
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => setIntersecting(entries.some((entry) => entry.isIntersecting && entry.intersectionRatio > 0)),
      { root: null, rootMargin: "240px 0px", threshold: 0.01 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!shouldRun) {
      stopLocalWork(true);
      setState(clientOnline ? "paused" : "offline");
      setMessage(clientOnline ? "Preview er sat på pause uden for visningen." : "Klienten er offline.");
      return undefined;
    }

    let cancelled = false;
    activeRef.current = true;
    setState("starting");
    setMessage("Starter preview …");

    const startPlayer = async () => {
      if (cancelled || hlsRef.current) return;
      const video = videoRef.current;
      if (!video) return;
      try {
        const { default: Hls } = await import("hls.js");
        if (cancelled) return;
        const hlsUrl = `${apiUrl}/hls/${client.id}/index.m3u8?_wall=${Date.now()}`;
        if (Hls.isSupported()) {
          const hls = new Hls({
            enableWorker: true,
            lowLatencyMode: false,
            liveSyncDuration: 4,
            liveMaxLatencyDuration: 14,
            maxBufferLength: 6,
            maxMaxBufferLength: 12,
            backBufferLength: 8,
            xhrSetup: (xhr) => {
              const token = mediaCapabilityRef.current;
              if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
            },
          });
          hlsRef.current = hls;
          hls.attachMedia(video);
          hls.on(Hls.Events.MEDIA_ATTACHED, () => hls.loadSource(hlsUrl));
          hls.on(Hls.Events.MANIFEST_PARSED, () => {
            if (cancelled) return;
            setState("live");
            setMessage("");
            video.play().catch(() => {});
          });
          hls.on(Hls.Events.FRAG_CHANGED, () => {
            if (!cancelled) updateLatency();
          });
          hls.on(Hls.Events.LEVEL_UPDATED, () => {
            if (!cancelled) updateLatency();
          });
          hls.on(Hls.Events.ERROR, (_event, data) => {
            if (!data?.fatal || cancelled) return;
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
              try { hls.recoverMediaError(); } catch {}
              return;
            }
            setState("starting");
            setMessage("Venter på friske segmenter …");
          });
          return;
        }

        if (video.canPlayType("application/vnd.apple.mpegurl")) {
          video.crossOrigin = "use-credentials";
          video.src = hlsUrl;
          video.muted = true;
          video.autoplay = true;
          video.playsInline = true;
          setState("live");
          setMessage("");
          video.play().catch(() => {});
          return;
        }

        setState("error");
        setMessage("Browseren understøtter ikke HLS-preview.");
      } catch {
        if (!cancelled) {
          setState("error");
          setMessage("Kunne ikke indlæse HLS-preview.");
        }
      }
    };

    const checkHealthUntilReady = async () => {
      if (cancelled || !mediaCapabilityRef.current) return;
      try {
        const resp = await fetch(`${apiUrl}/api/hls-cap/${client.id}/health`, {
          credentials: "omit",
          headers: { Authorization: `Bearer ${mediaCapabilityRef.current}` },
          signal: AbortSignal.timeout(6000),
        });
        if (resp.ok) {
          const health = await resp.json();
          if (health?.has_segments && !health?.is_stale) {
            await startPlayer();
            return;
          }
        }
      } catch {}
      if (!cancelled) {
        healthTimerRef.current = window.setTimeout(checkHealthUntilReady, HEALTH_STARTUP_POLL_MS);
      }
    };

    const heartbeat = async () => {
      if (cancelled) return;
      try {
        const resp = await authenticatedFetch(`${apiUrl}/api/livestream-v2/hls/${encodeURIComponent(client.id)}/viewer-heartbeat`, {
          method: "POST",
          credentials: "include",
          headers: {
            ...authHeaders(),
            "Content-Type": "application/json",
            accept: "application/json",
          },
          body: JSON.stringify({
            viewer_id: viewerIdRef.current,
            source: "superadmin_livestream_wall",
          }),
          signal: AbortSignal.timeout(8000),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const payload = await resp.json();
        if (payload?.media_capability) {
          mediaCapabilityRef.current = String(payload.media_capability);
        }
        if (Number.isFinite(Number(payload?.active_viewers))) {
          setActiveViewers(Number(payload.active_viewers));
        }
        if (!hlsRef.current && !healthTimerRef.current) {
          void checkHealthUntilReady();
        }
      } catch (error) {
        if (!cancelled) {
          if (isRequestTimeout(error)) {
            setState((current) => (current === "live" ? current : "starting"));
            setMessage("Livestream-kontakt er forsinket — prøver igen automatisk …");
          } else {
            setState("error");
            setMessage(error?.message || "Kunne ikke registrere livestream-viewer.");
          }
        }
      }
    };

    void heartbeat();
    heartbeatTimerRef.current = window.setInterval(heartbeat, VIEWER_HEARTBEAT_MS);

    return () => {
      cancelled = true;
      stopLocalWork(true);
    };
  }, [client.id, clientOnline, shouldRun, stopLocalWork, updateLatency]);

  useEffect(() => () => stopLocalWork(true), [stopLocalWork]);

  const tone = state === "live" ? "success" : state === "error" ? "error" : state === "offline" ? "neutral" : "info";

  return (
    <Paper
      ref={rootRef}
      elevation={0}
      sx={{
        overflow: "hidden",
        borderRadius: 2.5,
        background: "rgba(15,23,42,0.78)",
        border: "1px solid rgba(148,163,184,0.16)",
      }}
    >
      <Box
        ref={previewRef}
        sx={{
          position: "relative",
          aspectRatio: "16 / 9",
          background: "#020617",
          "&:fullscreen": { width: "100vw", height: "100vh", aspectRatio: "auto" },
        }}
      >
        <video
          ref={videoRef}
          muted
          autoPlay
          playsInline
          onTimeUpdate={updateLatency}
          style={{ width: "100%", height: "100%", display: "block", objectFit: "contain" }}
        />
        <Tooltip title="Vis i fuld skærm">
          <IconButton
            aria-label={`Vis ${client.name || "livestream"} i fuld skærm`}
            onClick={() => void handleFullscreen()}
            size="small"
            sx={{
              position: "absolute",
              top: 8,
              right: 8,
              zIndex: 3,
              color: "white",
              background: "rgba(2,6,23,0.62)",
              "&:hover": { background: "rgba(2,6,23,0.82)" },
            }}
          >
            <FullscreenIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        {state !== "live" && (
          <Stack
            spacing={1}
            sx={{
              position: "absolute",
              inset: 0,
              alignItems: "center",
              justifyContent: "center",
              p: 2,
              textAlign: "center",
              background: "rgba(2,6,23,0.58)",
            }}
          >
            {state === "starting" && <CircularProgress size={28} />}
            <Typography variant="body2" sx={{ color: "rgba(226,232,240,0.9)" }}>
              {message || "Venter på livestream …"}
            </Typography>
          </Stack>
        )}
      </Box>

      <Stack spacing={1} sx={{ p: 1.4 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between" }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 900 }} noWrap>{client.name}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap>
              {client.locality || "Ingen lokalitet"}
            </Typography>
          </Box>
          <Chip
            size="small"
            label={state === "live" ? "Live" : state === "offline" ? "Offline" : state === "error" ? "Fejl" : "Klargør"}
            sx={compactDarkChipSx(tone)}
          />
        </Stack>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between" }}>
          <Typography variant="caption" color="text.secondary">
            {[
              activeViewers == null ? "" : `${activeViewers} aktiv${activeViewers === 1 ? "" : "e"} seer${activeViewers === 1 ? "" : "e"}`,
              `Forsinkelse: ${formatLatency(latencySeconds)}`,
            ].filter(Boolean).join(" · ")}
          </Typography>
          <Button
            component={Link}
            to={`/clients/${client.id}`}
            size="small"
            endIcon={<OpenInNewIcon fontSize="small" />}
            sx={{ textTransform: "none" }}
          >
            Control Room
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

export default function LivestreamOverview() {
  const [clients, setClients] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [pageMediaActive, setPageMediaActive] = useState(document.visibilityState !== "hidden");
  const hiddenTimerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const data = await getControlRoomClients();
      setClients(Array.isArray(data) ? data.filter((client) => String(client.status || "").toLowerCase() === "approved") : []);
      setError("");
    } catch (err) {
      setError(err?.message || "Kunne ikke hente klienter.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void load();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    const applyVisibility = () => {
      if (document.visibilityState !== "hidden") {
        if (hiddenTimerRef.current) {
          window.clearTimeout(hiddenTimerRef.current);
          hiddenTimerRef.current = null;
        }
        setPageMediaActive(true);
        return;
      }
      if (!hiddenTimerRef.current) {
        hiddenTimerRef.current = window.setTimeout(() => {
          hiddenTimerRef.current = null;
          if (document.visibilityState === "hidden") setPageMediaActive(false);
        }, PAGE_HIDDEN_WARM_GRACE_MS);
      }
    };
    document.addEventListener("visibilitychange", applyVisibility);
    return () => {
      document.removeEventListener("visibilitychange", applyVisibility);
      if (hiddenTimerRef.current) window.clearTimeout(hiddenTimerRef.current);
    };
  }, []);

  const sortedClients = useMemo(
    () => [...clients].sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), "da-DK")),
    [clients],
  );

  return (
    <Stack spacing={2}>
      <Paper
        elevation={0}
        sx={{
          p: 2,
          borderRadius: 2.5,
          background: "rgba(15,23,42,0.72)",
          border: "1px solid rgba(148,163,184,0.16)",
        }}
      >
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ justifyContent: "space-between", alignItems: { md: "center" } }}>
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <GridViewIcon />
            <Box>
              <Typography variant="h6" sx={{ fontWeight: 950 }}>Livestream oversigt</Typography>
              <Typography variant="body2" color="text.secondary">
                Synlige previews aktiveres efter behov. Flere brugere kan se samme klient samtidig uden ekstra klient-producer.
              </Typography>
            </Box>
          </Stack>
          <Button onClick={() => void load()} disabled={loading} variant="outlined" sx={{ textTransform: "none" }}>
            Opdater
          </Button>
        </Stack>
      </Paper>

      {error && <Alert severity="error">{error}</Alert>}
      {loading && sortedClients.length === 0 ? (
        <Stack sx={{ minHeight: 240, alignItems: "center", justifyContent: "center" }}><CircularProgress /></Stack>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "repeat(2, minmax(0, 1fr))", xl: "repeat(3, minmax(0, 1fr))" },
            gap: 1.5,
          }}
        >
          {sortedClients.map((client) => (
            <LivestreamTile key={client.id} client={client} pageMediaActive={pageMediaActive} />
          ))}
        </Box>
      )}
    </Stack>
  );
}
