function shellQuote(value) {
  return `'${String(value ?? "").replaceAll("'", "'\\''")}'`;
}

export function buildFreshInstallDownloadCommand(created) {
  if (
    !created?.code ||
    !created?.release_id ||
    !created?.bundle_sha256 ||
    !created?.fresh_install_authorization
  ) {
    return "";
  }

  const artifactUrl = created.artifact_url || "/api/enrollment/fresh-install-artifact";
  return [
    "set -euo pipefail",
    "",
    "BACKEND_URL='https://api.display.planiq.dk'",
    `ENROLLMENT_CODE=${shellQuote(created.code)}`,
    `FRESH_INSTALL_AUTHORIZATION=${shellQuote(created.fresh_install_authorization)}`,
    `RELEASE_ID=${shellQuote(created.release_id)}`,
    `APPROVED_BUNDLE_SHA256=${shellQuote(created.bundle_sha256)}`,
    `ARTIFACT_PATH=${shellQuote(artifactUrl)}`,
    'BUNDLE="./${RELEASE_ID}.tar"',
    "",
    "export BACKEND_URL ENROLLMENT_CODE FRESH_INSTALL_AUTHORIZATION RELEASE_ID APPROVED_BUNDLE_SHA256 ARTIFACT_PATH BUNDLE",
    "/usr/bin/python3 -I - <<'PY'",
    "import json",
    "import os",
    "import shutil",
    "import urllib.request",
    "",
    "body = json.dumps({",
    '    "enrollment_code": os.environ["ENROLLMENT_CODE"],',
    '    "authorization": os.environ["FRESH_INSTALL_AUTHORIZATION"],',
    '    "expected_release_id": os.environ["RELEASE_ID"],',
    '    "expected_bundle_sha256": os.environ["APPROVED_BUNDLE_SHA256"],',
    "}).encode('utf-8')",
    "request = urllib.request.Request(",
    '    os.environ["BACKEND_URL"].rstrip("/") + os.environ["ARTIFACT_PATH"],',
    "    data=body,",
    '    headers={"Content-Type": "application/json"},',
    '    method="POST",',
    ")",
    'with urllib.request.urlopen(request, timeout=120) as response, open(os.environ["BUNDLE"], "xb") as output:',
    "    shutil.copyfileobj(response, output)",
    "PY",
    "",
    `printf '%s  %s\\n' "$APPROVED_BUNDLE_SHA256" "$BUNDLE" | /usr/bin/sha256sum --check --strict -`,
    "",
    "printf '%s\\n' 'Approved bundle downloaded and SHA-256 verified.'",
    "printf '%s\\n' 'Continue with CLIENTFLOW_RELEASE_PROCEDURE.md section 5 using this exact bundle.'",
  ].join("\n");
}
