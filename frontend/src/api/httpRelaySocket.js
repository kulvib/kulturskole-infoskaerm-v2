/**
 * WebSocket-shaped adapter over ordinary HTTPS long-polling.
 *
 * This is a fallback only. WSS remains the fast path, but municipal networks
 * that reject WebSocket upgrades retain the same component message handlers.
 */
export function createHttpRelaySocket({ relayId, sendPayload, pollMessages, closeRelay }) {
  let stopped = false;
  let sendChain = Promise.resolve();

  const socket = {
    relayId,
    readyState: WebSocket.CONNECTING,
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    send(raw) {
      if (socket.readyState !== WebSocket.OPEN || stopped) {
        throw new Error("HTTPS relay er ikke åben");
      }
      let payload;
      try {
        payload = JSON.parse(String(raw));
      } catch {
        throw new Error("HTTPS relay kræver JSON-meddelelser");
      }
      sendChain = sendChain
        .then(() => sendPayload(payload))
        .catch((error) => {
          socket.onerror?.(error);
          void stop(1011, error?.message || "HTTPS relay sendefejl");
        });
    },
    close(code = 1000, reason = "") {
      void stop(code, reason || "client_closed");
    },
  };

  async function stop(code = 1000, reason = "") {
    if (stopped) return;
    stopped = true;
    socket.readyState = WebSocket.CLOSING;
    try {
      await closeRelay();
    } catch {
      // Relay may already have expired server-side.
    }
    socket.readyState = WebSocket.CLOSED;
    socket.onclose?.({ code, reason, wasClean: code === 1000 });
  }

  async function pollLoop() {
    socket.readyState = WebSocket.OPEN;
    socket.onopen?.();
    while (!stopped) {
      try {
        const result = await pollMessages();
        const messages = Array.isArray(result?.messages) ? result.messages : [];
        for (const raw of messages) {
          let parsed = null;
          try { parsed = JSON.parse(String(raw)); } catch {}
          if (parsed?.type === "relay_closed") {
            await stop(Number(parsed.code || 1000), String(parsed.reason || "relay_closed"));
            return;
          }
          socket.onmessage?.({ data: String(raw) });
        }
        if (result?.closed) {
          await stop(1000, "relay_closed");
          return;
        }
      } catch (error) {
        if (stopped) return;
        socket.onerror?.(error);
        await stop(1011, error?.message || "HTTPS relay poll-fejl");
        return;
      }
    }
  }

  queueMicrotask(() => { void pollLoop(); });
  return socket;
}

export function createWebSocketWithHttpsFallback({ openWebSocket, openHttpsRelay }) {
  let active = null;
  let stopped = false;
  let fallbackStarted = false;

  const wrapper = {
    readyState: WebSocket.CONNECTING,
    transport: "wss",
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    send(raw) {
      if (!active || wrapper.readyState !== WebSocket.OPEN) throw new Error("Transporten er ikke åben");
      active.send(raw);
    },
    close(code = 1000, reason = "") {
      stopped = true;
      try { active?.close(code, reason); } catch {}
      wrapper.readyState = WebSocket.CLOSING;
    },
  };

  const bind = (socket, transport) => {
    active = socket;
    wrapper.transport = transport;
    socket.onopen = () => {
      wrapper.readyState = WebSocket.OPEN;
      wrapper.onopen?.({ transport });
    };
    socket.onmessage = (event) => {
      if (socket === active) wrapper.onmessage?.(event);
    };
    socket.onerror = (event) => {
      if (stopped || socket !== active) return;
      if (transport === "wss" && !fallbackStarted) {
        // A blocked WebSocket upgrade is an expected municipal-network
        // condition, not a user-visible product error. Move directly to the
        // ordinary HTTPS/443 transport and surface an error only if that also
        // fails.
        fallbackStarted = true;
        wrapper.readyState = WebSocket.CONNECTING;
        void startFallback();
        return;
      }
      wrapper.onerror?.(event);
    };
    socket.onclose = (event) => {
      if (stopped) {
        wrapper.readyState = WebSocket.CLOSED;
        wrapper.onclose?.(event);
        return;
      }
      if (socket !== active) return;
      if (transport === "wss") {
        if (!fallbackStarted) {
          fallbackStarted = true;
          wrapper.readyState = WebSocket.CONNECTING;
          void startFallback();
        }
        // If onerror already started fallback, ignore the stale WSS close.
        return;
      }
      wrapper.readyState = WebSocket.CLOSED;
      wrapper.onclose?.(event);
    };
  };

  const startFallback = async () => {
    try {
      const socket = await openHttpsRelay();
      if (stopped) {
        socket.close?.(1000, "component_closed");
        return;
      }
      bind(socket, "https_long_poll");
    } catch (error) {
      wrapper.onerror?.(error);
      wrapper.readyState = WebSocket.CLOSED;
      wrapper.onclose?.({ code: 1011, reason: error?.message || "HTTPS fallback fejlede", wasClean: false });
    }
  };

  try {
    bind(openWebSocket(), "wss");
  } catch (error) {
    fallbackStarted = true;
    wrapper.onerror?.(error);
    void startFallback();
  }
  return wrapper;
}
