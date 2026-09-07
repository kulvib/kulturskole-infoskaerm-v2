function shellQuote(value) {
  return `'${String(value ?? "").replaceAll("'", "'\\''")}'`;
}

export function buildFreshInstallDownloadCommand(created) {
  if (
    !created?.code ||
    !created?.release_id ||
    !created?.bundle_sha256 ||
    !Number.isSafeInteger(Number(created?.bundle_size)) ||
    Number(created?.bundle_size) <= 0 ||
    !created?.fresh_install_authorization
  ) {
    return "";
  }

  const artifactUrl = created.artifact_url || "/api/enrollment/fresh-install-artifact";
  return [
    "# Non-secret ClientFlow fresh-install handoff.",
    "# Paste this block first. It deliberately contains no enrollment capability.",
    "clientflow_fresh_install_download() {",
    "  BACKEND_URL='https://api.display.planiq.dk'",
    `  RELEASE_ID=${shellQuote(created.release_id)}`,
    `  APPROVED_BUNDLE_SHA256=${shellQuote(created.bundle_sha256)}`,
    `  APPROVED_BUNDLE_SIZE=${Number(created.bundle_size)}`,
    `  ARTIFACT_PATH=${shellQuote(artifactUrl)}`,
    '  BUNDLE="./${RELEASE_ID}.tar"',
    "",
    "  printf '%s' 'Client name: ' >&2",
    "  IFS= read -r CLIENTFLOW_CLIENT_NAME || return 1",
    '  test -n "$CLIENTFLOW_CLIENT_NAME" || { echo "Client name mangler" >&2; return 1; }',
    "  printf '%s' 'Locality (optional): ' >&2",
    "  IFS= read -r CLIENTFLOW_LOCALITY || return 1",
    "  printf '%s' 'Temporary bootstrap NetworkManager UUID (optional): ' >&2",
    "  IFS= read -r CLIENTFLOW_BOOTSTRAP_NETWORK_UUID || return 1",
    "",
    "  printf '%s' 'Enrollment code: ' >&2",
    "  IFS= read -r -s ENROLLMENT_CODE || return 1",
    "  printf '\\n%s' 'Fresh-install authorization: ' >&2",
    "  IFS= read -r -s FRESH_INSTALL_AUTHORIZATION || return 1",
    "  printf '\\n' >&2",
    '  test -n "$ENROLLMENT_CODE" || { echo "Enrollment code mangler" >&2; return 1; }',
    '  test -n "$FRESH_INSTALL_AUTHORIZATION" || { echo "Fresh-install authorization mangler" >&2; return 1; }',
    "",
    "  export BACKEND_URL ENROLLMENT_CODE FRESH_INSTALL_AUTHORIZATION RELEASE_ID APPROVED_BUNDLE_SHA256 APPROVED_BUNDLE_SIZE ARTIFACT_PATH BUNDLE CLIENTFLOW_CLIENT_NAME CLIENTFLOW_LOCALITY CLIENTFLOW_BOOTSTRAP_NETWORK_UUID",
    "  /usr/bin/python3 -I - <<'PY' || return 1",
    "import hashlib",
    "import json",
    "import os",
    "import tempfile",
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
    'bundle = os.path.abspath(os.environ["BUNDLE"])',
    'directory = os.path.dirname(bundle) or "."',
    'fd, temporary = tempfile.mkstemp(prefix=".clientflow-approved.", dir=directory)',
    "try:",
    '    digest = hashlib.sha256()',
    '    size = 0',
    '    with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=120) as response:',
    '        while chunk := response.read(1024 * 1024):',
    '            output.write(chunk)',
    '            digest.update(chunk)',
    '            size += len(chunk)',
    "        output.flush()",
    "        os.fsync(output.fileno())",
    '    if size != int(os.environ["APPROVED_BUNDLE_SIZE"]):',
    '        raise RuntimeError(f"Approved bundle size mismatch: {size}")',
    '    if digest.hexdigest() != os.environ["APPROVED_BUNDLE_SHA256"]:',
    '        raise RuntimeError("Approved bundle SHA-256 mismatch")',
    "    os.link(temporary, bundle)",
    "finally:",
    "    try:",
    "        os.unlink(temporary)",
    "    except FileNotFoundError:",
    "        pass",
    "PY",
    "",
    `  printf '%s  %s\\n' "$APPROVED_BUNDLE_SHA256" "$BUNDLE" | /usr/bin/sha256sum --check --strict - || return 1`,
    "",
    "  printf '%s\\n' 'Approved bundle downloaded and SHA-256 verified.'",
    "  printf '%s\\n' 'Continue with CLIENTFLOW_RELEASE_PROCEDURE.md section 5 using this exact bundle.'",
    "  unset -f clientflow_fresh_install_download",
    "}",
    "",
    "printf '%s\\n' 'Handoff loaded. Run: clientflow_fresh_install_download'",
    "printf '%s\\n' 'Enter client name/locality/network marker first; paste enrollment capabilities only at the hidden prompts.'",
  ].join("\n");
}
