import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import test from "node:test";

const root = new URL("../", import.meta.url);
const sourceRoot = new URL("../src/", import.meta.url);
const componentPath = new URL("../src/components/AppSnackbar.jsx", import.meta.url);
const mainPath = new URL("../src/main.jsx", import.meta.url);

function walk(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

test("Display-snackbarens fælles visuelle og tidsmæssige kontrakt er låst", () => {
  const source = readFileSync(componentPath, "utf8");

  assert.match(source, /anchorOrigin=\{\{ vertical: "bottom", horizontal: "center" \}\}/);
  assert.match(source, /variant="filled"/);
  assert.match(source, /SNACKBAR_BACKGROUND_OPACITY = 0\.8/);
  assert.match(source, /success: 5000/);
  assert.match(source, /info: 6000/);
  assert.match(source, /warning: 8000/);
  assert.match(source, /error: 8000/);
  assert.match(source, /reason === "clickaway"/);
  assert.match(source, /backgroundColor: alpha\(/);
  assert.match(source, /"&&": \{/);
  assert.match(source, /backgroundImage: "none"/);
  assert.match(source, /data-planiq-snackbar-opacity=\{SNACKBAR_BACKGROUND_OPACITY\}/);
  assert.doesNotMatch(source, /\bopacity\s*:/);
});


test("alle lokale instanser samles i én fælles snackbar-host", () => {
  const source = readFileSync(componentPath, "utf8");
  const mainSource = readFileSync(mainPath, "utf8");

  assert.match(source, /export function AppSnackbarProvider/);
  assert.match(source, /const AppSnackbarContext = React\.createContext\(null\)/);
  assert.match(source, /previousSnackbar\.onCloseRef\.current\?\.\(null, "replaced"\)/);
  assert.match(source, /sequenceRef\.current \+= 1/);
  assert.match(source, /instanceKey: `\$\{nextSnackbar\.sourceId\}-\$\{sequenceRef\.current\}`/);
  assert.match(source, /key=\{activeSnackbar\?\.instanceKey \?\? "empty"\}/);
  assert.equal((source.match(/<Snackbar\b/g) || []).length, 1);
  assert.match(mainSource, /<AppSnackbarProvider>/);
  assert.match(mainSource, /<\/AppSnackbarProvider>/);
});

test("ingen side implementerer Snackbar uden om AppSnackbar", () => {
  const files = walk(sourceRoot.pathname).filter((path) => /\.(jsx?|tsx?)$/.test(path));
  const directSnackbarUsers = [];
  const appSnackbarUsers = [];

  for (const path of files) {
    const source = readFileSync(path, "utf8");
    const displayPath = relative(root.pathname, path);
    if (displayPath !== "src/components/AppSnackbar.jsx" && /<Snackbar\b/.test(source)) {
      directSnackbarUsers.push(displayPath);
    }
    if (/<AppSnackbar\b/.test(source)) appSnackbarUsers.push(displayPath);
  }

  assert.deepEqual(directSnackbarUsers, []);
  assert.ok(appSnackbarUsers.length >= 12, `Forventede mindst 12 AppSnackbar-brugere, fandt ${appSnackbarUsers.length}`);
});

test("midlertidige handlingsbeskeder må ikke omgå den fælles snackbar", () => {
  const files = walk(sourceRoot.pathname).filter((path) => /\.(jsx?|tsx?)$/.test(path));
  const dismissibleInlineAlerts = [];

  for (const path of files) {
    const source = readFileSync(path, "utf8");
    const displayPath = relative(root.pathname, path);
    if (displayPath === "src/components/AppSnackbar.jsx") continue;

    if (/<(?:Mui)?Alert\b[^>]*\bonClose=/.test(source)) {
      dismissibleInlineAlerts.push(displayPath);
    }
  }

  assert.deepEqual(
    dismissibleInlineAlerts,
    [],
    "Dismissible procesbeskeder skal bruge AppSnackbar; inline Alert er kun til vedvarende dokumentflow.",
  );

  const remoteDesktopSource = readFileSync(
    new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktop.jsx", import.meta.url),
    "utf8",
  );
  const fileManagerSource = readFileSync(
    new URL("../src/pages/clientdetailspage/remotedesktop/RemoteDesktopFileManager.jsx", import.meta.url),
    "utf8",
  );
  const organizationSource = readFileSync(
    new URL("../src/pages/adminpages/OrganizationAdministration.jsx", import.meta.url),
    "utf8",
  );
  const auditSource = readFileSync(
    new URL("../src/pages/adminpages/AuditLog.jsx", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(remoteDesktopSource, /STATUS_AUTO_HIDE_MS|setTimedMessage|setTemporaryStatus/);
  assert.match(remoteDesktopSource, /open=\{Boolean\(error\)\}[\s\S]*severity="error"/);
  assert.match(remoteDesktopSource, /open=\{Boolean\(actionMessage\)\}[\s\S]*severity="success"/);

  for (const stateName of [
    "transferError",
    "transferStatus",
    "fileDownloadStatus",
    "fileOperationStatus",
    "fileBrowserError",
  ]) {
    assert.match(fileManagerSource, new RegExp(`open=\\{Boolean\\(${stateName}\\)\\}`));
    assert.doesNotMatch(fileManagerSource, new RegExp(`<Alert[^>]*>[^<]*\\{${stateName}\\}`));
  }

  assert.match(organizationSource, /open=\{Boolean\(error\)\}[\s\S]*severity="error"/);
  assert.doesNotMatch(organizationSource, /\{error && <Alert/);
  assert.match(auditSource, /open=\{Boolean\(cleanupMessage\)\}[\s\S]*severity=\{cleanupSeverity\}/);
  assert.doesNotMatch(auditSource, /cleanupMessage && \([\s\S]*<Alert/);
});

