import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = process.cwd();
const read = (p) => fs.readFileSync(path.join(root, p), "utf8");

test("maintenance gate is public-status driven, no-store and fail closed", () => {
  const main = read("src/main.jsx");
  const gate = read("src/auth/MaintenanceGate.jsx");
  const api = read("src/auth/maintenanceApi.js");
  assert.match(main, /<MaintenanceGate>/);
  assert.match(api, /\/api\/maintenance\/status/);
  assert.match(api, /cache: "no-store"/);
  assert.match(gate, /Driftsstatus kunne ikke bekræftes/);
  assert.match(gate, /POLL_MS = 15_000/);
  assert.match(gate, /ClientFlow-drift fortsætter/);
  assert.match(gate, /maintenance_admin/);
});

test("maintenance administration is strict superadmin-only and reauthenticates every mutation", () => {
  const admin = read("src/pages/adminpages/AdminPage.jsx");
  const maintenance = read("src/pages/adminpages/MaintenanceAdministration.jsx");
  assert.match(admin, /key: "maintenance"/);
  assert.match(admin, /viewerAllowed: false/);
  assert.match(admin, /isViewer && section\.viewerAllowed !== false/);
  assert.match(maintenance, /password,/);
  assert.match(maintenance, /updateMaintenanceStatus/);
  assert.match(maintenance, /menneskelig brugeradgang/i);
  assert.match(maintenance, /CustomEvent\("planiq:maintenance"\)/);
});
