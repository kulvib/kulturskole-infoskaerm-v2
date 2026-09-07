export function shouldAutoOpenTerminalPty({ mode, clientConnected, hasAdminStepUp }) {
  if (!clientConnected) return false;
  if (mode !== "admin") return true;
  return Boolean(hasAdminStepUp);
}
