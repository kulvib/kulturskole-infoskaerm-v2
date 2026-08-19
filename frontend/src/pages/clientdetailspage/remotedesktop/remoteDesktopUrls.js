function normalizeApiOrigin(apiOrigin) {
  return String(apiOrigin || "").replace(/\/$/, "");
}

export function buildRemoteDesktopBrowserDownloadUrl(apiOrigin, clientId, transferId) {
  return `${normalizeApiOrigin(apiOrigin)}/api/remote-desktop/clients/${encodeURIComponent(clientId)}/files/browser-download/${encodeURIComponent(transferId)}`;
}

export function buildRemoteDesktopUploadMultipleUrl(apiOrigin, clientId) {
  return `${normalizeApiOrigin(apiOrigin)}/api/remote-desktop/clients/${encodeURIComponent(clientId)}/files/upload-multiple`;
}
