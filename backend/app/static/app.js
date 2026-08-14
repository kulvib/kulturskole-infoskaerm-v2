const $ = (id) => document.getElementById(id);

let currentUser = null;
let clients = [];
let selectedClient = null;
let pollTimer = null;
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
    throw new Error(detail || `HTTP ${response.status}`);
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

async function selectClient(client) {
  selectedClient = client;
  loadedGeneration = null;
  destroyPlayer();
  $('emptyState').classList.add('hidden');
  $('clientView').classList.remove('hidden');
  $('clientName').textContent = `${client.name} · #${client.id}`;
  await refreshClients();
  await refreshLivestream();
  clearInterval(pollTimer);
  pollTimer = setInterval(refreshLivestream, 2000);
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
  $('debugStatus').textContent = JSON.stringify(status, null, 2);

  $('startButton').disabled = ['starting', 'running', 'stopping'].includes(state);
  $('restartButton').disabled = state === 'stopping';
  $('stopButton').disabled = state === 'stopped';

  if (generation && status.playlist_ready && ['starting', 'running', 'stopping'].includes(state)) {
    if (loadedGeneration !== generation.id) attachPlayer(generation.id);
    $('videoMessage').classList.add('hidden');
  } else {
    if (state === 'stopped' || state === 'failed') destroyPlayer();
    $('videoMessage').textContent = state === 'stopped'
      ? 'Streamen er stoppet.'
      : state === 'failed'
        ? `Streamen fejlede${generation?.error_code ? `: ${generation.error_code}` : '.'}`
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

async function action(name) {
  if (!selectedClient) return;
  try {
    await api(`/api/clients/${selectedClient.id}/livestream/${name}`, { method: 'POST' });
    toast(`${name} sendt`);
    await refreshLivestream();
    await refreshClients();
  } catch (error) {
    toast(error.message);
  }
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
  destroyPlayer();
  await api('/api/auth/logout', { method: 'POST' }).catch(() => {});
  selectedClient = null;
  currentUser = null;
  setLoggedIn(false);
});

$('startButton').addEventListener('click', () => action('start'));
$('restartButton').addEventListener('click', () => action('restart'));
$('stopButton').addEventListener('click', () => action('stop'));

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

bootstrap();
