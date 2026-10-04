import assert from "node:assert/strict";
import test from "node:test";

if (!globalThis.WebSocket) {
  globalThis.WebSocket = { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 };
}

const { createHttpRelaySocket, createWebSocketWithHttpsFallback } = await import(
  "../src/api/httpRelaySocket.js"
);

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

test("HTTPS relay serializes JSON sends and closes cleanly", async () => {
  const sent = [];
  let closed = 0;
  let polls = 0;
  let releaseSecondPoll;
  const secondPollGate = new Promise((resolve) => { releaseSecondPoll = resolve; });
  const socket = createHttpRelaySocket({
    relayId: "relay-1",
    sendPayload: async (payload) => {
      await tick();
      sent.push(payload);
    },
    pollMessages: async () => {
      polls += 1;
      if (polls === 1) return { messages: [JSON.stringify({ type: "hello" })], closed: false };
      await secondPollGate;
      return { messages: [], closed: true };
    },
    closeRelay: async () => { closed += 1; },
  });

  const messages = [];
  socket.onmessage = (event) => messages.push(JSON.parse(event.data));
  await tick();
  assert.equal(socket.readyState, WebSocket.OPEN);
  socket.send(JSON.stringify({ sequence: 1 }));
  socket.send(JSON.stringify({ sequence: 2 }));
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.deepEqual(sent, [{ sequence: 1 }, { sequence: 2 }]);
  assert.deepEqual(messages, [{ type: "hello" }]);
  releaseSecondPoll();
  await tick();
  assert.equal(socket.readyState, WebSocket.CLOSED);
  assert.equal(closed, 1);
});

test("transport fails over from WSS to HTTPS without changing message interface", async () => {
  const wss = {
    readyState: WebSocket.CONNECTING,
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    send() {},
    close() {},
  };
  let fallbackOpened = 0;
  const fallback = {
    readyState: WebSocket.CONNECTING,
    onopen: null,
    onmessage: null,
    onclose: null,
    onerror: null,
    sent: [],
    send(raw) { this.sent.push(raw); },
    close() {},
  };
  const wrapper = createWebSocketWithHttpsFallback({
    openWebSocket: () => wss,
    openHttpsRelay: async () => {
      fallbackOpened += 1;
      return fallback;
    },
  });

  let opens = 0;
  const received = [];
  wrapper.onopen = () => { opens += 1; };
  wrapper.onmessage = (event) => received.push(event.data);

  wss.onclose?.({ code: 1006, reason: "upgrade_blocked", wasClean: false });
  await tick();
  assert.equal(fallbackOpened, 1);
  assert.equal(wrapper.transport, "https_long_poll");

  fallback.readyState = WebSocket.OPEN;
  fallback.onopen?.();
  assert.equal(wrapper.readyState, WebSocket.OPEN);
  assert.equal(opens, 1);
  wrapper.send(JSON.stringify({ type: "input", data: "x" }));
  assert.equal(fallback.sent.length, 1);
  fallback.onmessage?.({ data: JSON.stringify({ type: "output", data: "ok" }) });
  assert.equal(received.length, 1);
});


test("blocked WSS upgrade is transparent when HTTPS fallback succeeds", async () => {
  const wss = {
    readyState: WebSocket.CONNECTING, onopen: null, onmessage: null, onclose: null, onerror: null,
    send() {}, close() {},
  };
  const fallback = {
    readyState: WebSocket.CONNECTING, onopen: null, onmessage: null, onclose: null, onerror: null,
    send() {}, close() {},
  };
  const wrapper = createWebSocketWithHttpsFallback({
    openWebSocket: () => wss,
    openHttpsRelay: async () => fallback,
  });
  let visibleErrors = 0;
  wrapper.onerror = () => { visibleErrors += 1; };

  wss.onerror?.(new Error("upgrade blocked"));
  wss.onclose?.({ code: 1006, reason: "upgrade blocked", wasClean: false });
  await tick();
  fallback.readyState = WebSocket.OPEN;
  fallback.onopen?.();

  assert.equal(wrapper.transport, "https_long_poll");
  assert.equal(wrapper.readyState, WebSocket.OPEN);
  assert.equal(visibleErrors, 0);
});
