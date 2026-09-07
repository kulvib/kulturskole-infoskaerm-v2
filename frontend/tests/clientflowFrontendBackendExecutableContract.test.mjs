import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { createServer } from "vite";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(HERE, "..");
const contract = JSON.parse(
  fs.readFileSync(path.join(HERE, "contracts", "clientflowFrontendBackendContract.json"), "utf8"),
);

function deploymentFixture() {
  return {
    id: "deployment-123",
    client_id: 42,
    target_release_id: "clientflow-9.8.7-seq-6543",
    target_version: "9.8.7",
    target_release_sequence: 6543,
    bundle_sha256: "a".repeat(64),
    bundle_size: 80123456,
    release_approval_reference: "contract/approved",
    release_candidate_sha256: "b".repeat(64),
    source_commit: "c".repeat(40),
    allow_downgrade: false,
    requested_at: "2026-08-23T19:00:00Z",
    state: "staged",
    state_updated_at: "2026-08-23T19:00:01Z",
  };
}

function enrollmentFixture() {
  return {
    id: 7,
    code: "CF-ABCD-EFGH-IJKL",
    code_preview: "IJKL",
    created_at: "2026-08-23T19:00:00Z",
    expires_at: "2026-08-24T07:00:00Z",
    used_at: null,
    revoked_at: null,
    used_by_client_id: null,
    organization_id: null,
    note: "contract",
    is_used: false,
    is_expired: false,
    is_revoked: false,
    release_id: "clientflow-9.8.7-seq-6543",
    version: "9.8.7",
    release_sequence: 6543,
    bundle_sha256: "a".repeat(64),
    bundle_size: 80123456,
    release_approval_reference: "contract/approved",
    release_candidate_sha256: "b".repeat(64),
    source_commit: "c".repeat(40),
    fresh_install_authorization: "cf-fresh-v1.payload.signature",
    artifact_url: "/api/enrollment/fresh-install-artifact",
  };
}

function localManagementFixture(overrides = {}) {
  return {
    action: null,
    request_id: null,
    desired_hostname: null,
    desired_client_name: null,
    status: "ready",
    message: "Ingen lokal klienthandling i gang",
    requested_at: null,
    started_at: null,
    finished_at: null,
    error: null,
    ...overrides,
  };
}

function osUpdateFixture() {
  return {
    ok: true,
    command_id: "system-command-os-update-1",
    pending_os_update: true,
    ubuntu_update_status: "requested",
    ubuntu_update_step: "os_update_requested",
    ubuntu_update_message: "Ubuntu-opdatering afventer System-agent",
    ubuntu_update_error: null,
    ubuntu_update_started_at: null,
    ubuntu_update_updated_at: "2026-08-30T14:00:00Z",
    ubuntu_update_finished_at: null,
    ubuntu_update_progress: null,
    ubuntu_update_package_count: null,
    ubuntu_update_reboot_required: null,
  };
}

const responseByOperation = {
  getClients: [{ id: 42, status: "approved", presence: { is_online: true } }],
  getClient: { id: 42, status: "approved", presence: { is_online: true } },
  getClientPresence: {
    is_online: true,
    status: { domain: "status", is_online: true },
    display: { domain: "display", is_online: true },
    system: { domain: "system", is_online: true },
  },
  getChromeStatus: { client_id: 42, state: "normal", pending_reboot: false, pending_shutdown: false },
  getClientLocalManagement: localManagementFixture(),
  requestCfadminPasswordChange: localManagementFixture({ action: "cfadmin_password", request_id: "system-command-password-1", status: "pending" }),
  requestLocalHostnameChange: localManagementFixture({ action: "hostname", request_id: "system-command-hostname-1", desired_hostname: "viborg2-client", desired_client_name: "Viborg2 Client", status: "pending", name: "Viborg2 Client" }),
  updateClientKiosk: { id: 42, status: "approved", kiosk_url: "https://infoskaerm.example.test/client/42" },
  clientActionReboot: { ok: true, command_id: "system-command-1", action: "reboot" },
  clientActionStopBrowser: { ok: true, pending_chrome_action: "stop" },
  requestOsUpdate: osUpdateFixture(),
  approveClient: { id: 42, status: "approved", presence: { is_online: false } },
  getClientflowReleases: {
    catalog_sequence: 6543,
    latest_stable: "9.8.7",
    default_install_version: "9.8.7",
    retention_policy: {},
    releases: [{ version: "9.8.7", status: "stable", update_allowed: true }],
  },
  getClientflowDeployments: [deploymentFixture()],
  getActiveClientflowDeployment: deploymentFixture(),
  requestClientflowDeployment: deploymentFixture(),
  cancelClientflowDeployment: { ...deploymentFixture(), state: "cancelled" },
  createEnrollmentToken: enrollmentFixture(),
  getEnrollmentTokens: [enrollmentFixture()],
  revokeEnrollmentToken: { ...enrollmentFixture(), revoked_at: "2026-08-23T19:05:00Z", is_revoked: true },
};

const invoke = {
  getClients: (api) => api.getClients(),
  getClient: (api) => api.getClient(42),
  getClientPresence: (api) => api.getClientPresence(42),
  getChromeStatus: (api) => api.getChromeStatus(42),
  getClientLocalManagement: (api) => api.getClientLocalManagement(42),
  requestCfadminPasswordChange: (api) => api.requestCfadminPasswordChange(42, "Contract-Passphrase-42!"),
  requestLocalHostnameChange: (api) => api.requestLocalHostnameChange(42, "Viborg2 Client"),
  updateClientKiosk: (api) => api.updateClient(42, { kiosk_url: "https://infoskaerm.example.test/client/42" }),
  clientActionReboot: (api) => api.clientAction(42, "reboot"),
  clientActionStopBrowser: (api) => api.clientAction(42, "stop"),
  requestOsUpdate: (api) => api.requestOsUpdate(42),
  approveClient: (api) => api.approveClient(42, 7),
  getClientflowReleases: (api) => api.getClientflowReleases(),
  getClientflowDeployments: (api) => api.getClientflowDeployments(42),
  getActiveClientflowDeployment: (api) => api.getActiveClientflowDeployment(42),
  requestClientflowDeployment: (api) => api.requestClientflowDeployment(42, {
    targetVersion: "9.8.7",
    confirmDowngrade: true,
    reason: "contract",
  }),
  cancelClientflowDeployment: (api) => api.cancelClientflowDeployment("deployment-123", "contract"),
  createEnrollmentToken: (api) => api.createEnrollmentToken({ expires_in_hours: 12, note: "contract" }),
  getEnrollmentTokens: (api) => api.getEnrollmentTokens({ include_history: true }),
  revokeEnrollmentToken: (api) => api.revokeEnrollmentToken(7),
};

function pathAndQuery(rawUrl) {
  const parsed = new URL(String(rawUrl), "https://display.planiq.dk");
  return `${parsed.pathname}${parsed.search}`;
}

function parsedBody(call) {
  if (call.init?.body == null) return null;
  return JSON.parse(String(call.init.body));
}

test("ClientFlow frontend API functions execute the shared backend contract", async () => {
  process.env.VITE_API_URL = "";
  process.env.VITE_WS_API_URL = "";

  const calls = [];
  let currentOperation = null;

  globalThis.localStorage = {
    getItem() { return null; },
    setItem() {},
    removeItem() {},
  };
  globalThis.window = {
    location: { origin: "https://display.planiq.dk", href: "https://display.planiq.dk/" },
    open() {},
  };
  globalThis.fetch = async (input, init = {}) => {
    calls.push({ input: String(input), init: { ...init } });
    const operation = contract.operations.find((entry) => entry.name === currentOperation);
    const status = Number(operation?.success_status || 200);
    return new Response(JSON.stringify(responseByOperation[currentOperation]), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  };

  const server = await createServer({
    root: FRONTEND_ROOT,
    logLevel: "silent",
    appType: "custom",
    server: { middlewareMode: true },
  });

  try {
    const api = await server.ssrLoadModule("/src/api/api.js");

    for (const operation of contract.operations) {
      assert.equal(typeof invoke[operation.name], "function", `Missing executable frontend invocation for ${operation.name}`);
      currentOperation = operation.name;
      calls.length = 0;

      const result = await invoke[operation.name](api);
      assert.equal(calls.length, 1, `${operation.name} must issue exactly one HTTP request`);
      const call = calls[0];
      const actualMethod = String(call.init?.method || "GET").toUpperCase();
      assert.equal(actualMethod, operation.method, `${operation.name} HTTP method drift`);
      assert.equal(pathAndQuery(call.input), operation.example_path, `${operation.name} HTTP path drift`);

      const requiredRequestProperties = operation.request_properties || [];
      if (requiredRequestProperties.length) {
        const body = parsedBody(call);
        assert.ok(body && typeof body === "object", `${operation.name} must send a JSON body`);
        for (const key of requiredRequestProperties) {
          assert.ok(Object.hasOwn(body, key), `${operation.name} request body is missing ${key}`);
        }
      }

      if (operation.response_properties?.length) {
        assert.ok(result && typeof result === "object" && !Array.isArray(result), `${operation.name} must return an object`);
        for (const key of operation.response_properties) {
          assert.ok(Object.hasOwn(result, key), `${operation.name} response is missing ${key}`);
        }
      }

      if (operation.response_item_properties?.length) {
        assert.ok(Array.isArray(result) && result.length > 0, `${operation.name} must return a non-empty list fixture`);
        for (const key of operation.response_item_properties) {
          assert.ok(Object.hasOwn(result[0], key), `${operation.name} list item is missing ${key}`);
        }
      }
    }

    currentOperation = "clientActionReboot";
    calls.length = 0;
    await invoke.clientActionReboot(api);
    assert.deepEqual(parsedBody(calls[0]), { action: "reboot", source: "actionbutton" });

    currentOperation = "clientActionStopBrowser";
    calls.length = 0;
    await invoke.clientActionStopBrowser(api);
    assert.deepEqual(parsedBody(calls[0]), { action: "stop", source: "actionbutton" });

    currentOperation = "updateClientKiosk";
    calls.length = 0;
    await invoke.updateClientKiosk(api);
    assert.deepEqual(parsedBody(calls[0]), { kiosk_url: "https://infoskaerm.example.test/client/42" });

    currentOperation = "requestCfadminPasswordChange";
    calls.length = 0;
    await invoke.requestCfadminPasswordChange(api);
    assert.deepEqual(parsedBody(calls[0]), { password: "Contract-Passphrase-42!" });

    currentOperation = "requestLocalHostnameChange";
    calls.length = 0;
    await invoke.requestLocalHostnameChange(api);
    assert.deepEqual(parsedBody(calls[0]), { name: "Viborg2 Client" });

    for (const [action, expectedEndpoint, expectedAction] of [
      ["start", "/api/clients/42/chrome-command", "start"],
      ["sleep", "/api/clients/42/chrome-command", "sleep"],
      ["wakeup", "/api/clients/42/chrome-command", "wakeup"],
      ["reset_browser", "/api/clients/42/chrome-command", "reset_browser"],
      ["restart", "/api/clients/42/system-command", "reboot"],
      ["shutdown", "/api/clients/42/system-command", "shutdown"],
    ]) {
      currentOperation = action === "shutdown" || action === "restart" ? "clientActionReboot" : "clientActionStopBrowser";
      calls.length = 0;
      await api.clientAction(42, action);
      assert.equal(pathAndQuery(calls[0].input), expectedEndpoint);
      assert.deepEqual(parsedBody(calls[0]), { action: expectedAction, source: "actionbutton" });
    }

    currentOperation = "requestClientflowDeployment";
    calls.length = 0;
    await assert.rejects(
      () => api.requestClientflowDeployment(42, { targetVersion: "latest" }),
      /konkret katalogversion/,
    );
    assert.equal(calls.length, 0, "Frontend must reject implicit latest before any backend request");
  } finally {
    await server.close();
  }
});
