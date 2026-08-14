const $ = (id) => document.getElementById(id);

let currentUser = null;
let clients = [];
let selectedClient = null;
let pollTimer = null;
let heartbeatTimer = null;
let viewerSession = null;
let hls = null;
let loadedGeneration = null;
let latestCredential = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const type = response.headers.get('content-type') || '';
  const body = type.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === 'object' ? (body.detail || body.error || JSON.stringify(body)) : body;
    const error = new Error(detail || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return body;
}

function toast(message) {
  const node = $('toast');
  node.textContent = message;
  node.classList.remove('hidden');
  clearTimeout(node._timer);
  node._timer = setTimeout(() => node.classList.add('hidden'), 3200);
}

function setLoggedIn(value) {
  $('loginView').classList.toggle('hidden', value);
  $('appView').classList.toggle('hidden', !value);
  $('logoutButton').classList.toggle('hidden', !value);
}

async function bootstrap() {
  try {
    currentUser = await api('/api/auth/me');
    setLoggedIn(true);
    await refreshClients();
  } catch {
    setLoggedIn(false);
  }
}

async function refreshClients() {
  clients = await api('/api/clients');
  const list = $('clientList');
  list.innerHTML = '';
  for (const client of clients) {
    const button = document.createElement('button');
    button.className = `client-item ${selectedClient?.id === client.id ? 'active' : ''}`;
    button.innerHTML = `<strong>${escapeHtml(client.name)}</strong><small>${escapeHtml(client.livestream_state || 'stopped')}</small>`;
    button.addEventListener('click', () => selectClient(client));
    list.appendChild(button);
  }
  if (selectedClient) {
    const updated = clients.find((item) => item.id === selectedClient.id);
    if (updated) selectedClient = updated;
  }
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char]));
}

function clearViewerHeartbeat() {
  clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

function startPolling() {
  clearInterval(pollTimer);
  if (!selectedClient || document.visibilityState !== 'visible') return;
  pollTimer = setInterval(refreshLivestream, 2000);
}

function startViewerHeartbeat(seconds) {
  clearViewerHeartbeat();
  const intervalMs = Math.max(1000, Number(seconds || 10) * 1000);
  heartbeatTimer = setInterval(sendViewerHeartbeat, intervalMs);
}

async function enterViewer() {
  if (!selectedClient || !currentUser || document.visibilityState !== 'visible') return;
  if (viewerSession?.clientId === selectedClient.id) return;

  const clientId = selectedClient.id;
  const result = await api(`/api/clients/${clientId}/livestream/viewers`, { method: 'POST' });
  if (!selectedClient || selectedClient.id !== clientId || document.visibilityState !== 'visible') {
    navigator.sendBeacon(`/api/clients/${clientId}/livestream/viewers/${result.viewer_id}/leave`);
    return;
  }

  viewerSession = {
    clientId,
    viewerId: result.viewer_id,
    heartbeatSeconds: result.heartbeat_seconds || 10,
  };
  startViewerHeartbeat(viewerSession.heartbeatSeconds);
}

async function sendViewerHeartbeat() {
  const session = viewerSession;
  if (!session || !selectedClient || selectedClient.id !== session.clientId || document.visibilityState !== 'visible') return;
  try {
    await api(
      `/api/clients/${session.clientId}/livestream/viewers/${session.viewerId}/heartbeat`,
      { method: 'POST' },
    );
  } catch (error) {
    if (error.status === 404 || error.status === 409) {
      viewerSession = null;
      clearViewerHeartbeat();
      await enterViewer().catch(() => {});
    }
  }
}

async function leaveViewer({ beacon = false } = {}) {
  const session = viewerSession;
  viewerSession = null;
  clearViewerHeartbeat();
  if (!session) return;

  const path = `/api/clients/${session.clientId}/livestream/viewers/${session.viewerId}/leave`;
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon(path);
    return;
  }
  await api(path, { method: 'POST' }).catch(() => {});
}

async function selectClient(client) {
  if (selectedClient?.id !== client.id) {
    await leaveViewer();
    selectedClient = client;
    loadedGeneration = null;
    destroyPlayer();
  }

  $('emptyState').classList.add('hidden');
  $('clientView').classList.remove('hidden');
  $('clientName').textContent = `${client.name} · #${client.id}`;
  await refreshClients();

  try {
    await enterViewer();
  } catch (error) {
    toast(`Livestream kunne ikke åbnes: ${error.message}`);
  }
  await refreshLivestream();
  startPolling();
}

async function refreshLivestream() {
  if (!selectedClient) return;
  try {
    const status = await api(`/api/clients/${selectedClient.id}/livestream`);
    renderLivestream(status);
  } catch (error) {
    $('debugStatus').textContent = error.message;
  }
}

function renderLivestream(status) {
  const generation = status.generation;
  const state = generation?.state || 'stopped';
  const badge = $('stateBadge');
  badge.textContent = state;
  badge.className = `badge ${state}`;
  $('agentStatus').textContent = status.agent
    ? `Agent: ${status.agent.observed_state} · v${status.agent.agent_version}`
    : 'Agent: ikke set';
  $('mediaAge').textContent = status.media_age_seconds == null
    ? 'Media: —'
    : `Media: ${Math.round(status.media_age_seconds)}s`;
  $('viewerStatus').textContent = `Seere: ${status.viewers?.active ?? 0}`;
  $('debugStatus').textContent = JSON.stringify(status, null, 2);

  if (generation && status.playlist_ready && ['starting', 'running', 'stopping'].includes(state)) {
    if (loadedGeneration !== generation.id) attachPlayer(generation.id);
    $('videoMessage').classList.add('hidden');
  } else {
    if (state === 'stopped' || state === 'failed') destroyPlayer();
    $('videoMessage').textContent = state === 'stopped'
      ? (viewerSession ? 'Starter livestream automatisk…' : 'Livestream er stoppet, fordi ingen ser den.')
      : state === 'failed'
        ? `Streamen fejlede${generation?.error_code ? `: ${generation.error_code}` : '.'}`
        : state === 'stopping'
          ? 'Stopper livestream…'
          : 'Venter på HLS-segmenter…';
    $('videoMessage').classList.remove('hidden');
  }
}

function attachPlayer(generationId) {
  destroyPlayer();
  loadedGeneration = generationId;
  const video = $('video');
  const src = `/api/clients/${selectedClient.id}/livestream/hls/index.m3u8`;
  if (window.Hls && Hls.isSupported()) {
    hls = new Hls({
      liveSyncDurationCount: 2,
      liveMaxLatencyDurationCount: 5,
      maxLiveSyncPlaybackRate: 1.25,
      enableWorker: true,
    });
    hls.loadSource(src);
    hls.attachMedia(video);
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (!data.fatal) return;
      destroyPlayer();
      loadedGeneration = null;
      setTimeout(refreshLivestream, 1500);
    });
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    video.src = src;
  } else {
    $('videoMessage').textContent = 'Browseren understøtter ikke HLS.';
    $('videoMessage').classList.remove('hidden');
  }
}

function destroyPlayer() {
  if (hls) {
    hls.destroy();
    hls = null;
  }
  const video = $('video');
  video.pause();
  video.removeAttribute('src');
  video.load();
  loadedGeneration = null;
}

$('loginForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('loginError').textContent = '';
  try {
    currentUser = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email: $('email').value, password: $('password').value }),
    });
    $('password').value = '';
    setLoggedIn(true);
    await refreshClients();
  } catch (error) {
    $('loginError').textContent = error.message;
  }
});

$('logoutButton').addEventListener('click', async () => {
  clearInterval(pollTimer);
  await leaveViewer();
  destroyPlayer();
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  selectedClient = null;
  currentUser = null;
  setLoggedIn(false);
});

$('newClientButton').addEventListener('click', () => $('clientDialog').showModal());
$('clientCancel').addEventListener('click', () => $('clientDialog').close());
$('clientForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  try {
    const client = await api('/api/clients', {
      method: 'POST',
      body: JSON.stringify({ name: $('clientInput').value, id: $('clientIdInput').value ? Number($('clientIdInput').value) : null }),
    });
    $('clientInput').value = '';
    $('clientIdInput').value = '';
    $('clientDialog').close();
    await refreshClients();
    await selectClient(client);
  } catch (error) {
    toast(error.message);
  }
});

$('credentialButton').addEventListener('click', async () => {
  if (!selectedClient) return;
  if (!confirm('Det eksisterende Livestream credential bliver tilbagekaldt. Fortsæt?')) return;
  try {
    latestCredential = await api(`/api/clients/${selectedClient.id}/livestream/credential`, { method: 'POST' });
    $('credentialJson').textContent = JSON.stringify(latestCredential, null, 2);
    $('credentialDialog').showModal();
  } catch (error) {
    toast(error.message);
  }
});

$('downloadCredential').addEventListener('click', () => {
  if (!latestCredential) return;
  const blob = new Blob([JSON.stringify(latestCredential, null, 2) + '\n'], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'livestream.json';
  link.click();
  URL.revokeObjectURL(url);
});
$('closeCredential').addEventListener('click', () => $('credentialDialog').close());

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') {
    clearInterval(pollTimer);
    leaveViewer({ beacon: true });
    destroyPlayer();
    return;
  }

  if (selectedClient && currentUser) {
    enterViewer()
      .then(refreshLivestream)
      .then(startPolling)
      .catch((error) => toast(`Livestream kunne ikke genoptages: ${error.message}`));
  }
});

window.addEventListener('pagehide', () => {
  leaveViewer({ beacon: true });
});

bootstrap();
