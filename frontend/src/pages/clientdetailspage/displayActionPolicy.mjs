export function getBrowserProcessActionDisabledInfo(key, chromeIsRunning, browserRequested) {
  if (key === "start" && chromeIsRunning === true) {
    return { disabled: true, reason: "Kiosk browser kører allerede" };
  }

  // A stopped process is not enough to disable Stop: the runtime can still have
  // browser_requested=true and be retrying after a crash or waiting for session.
  if (key === "stop" && browserRequested === false) {
    return { disabled: true, reason: "Kiosk browser er allerede stoppet" };
  }

  return null;
}
