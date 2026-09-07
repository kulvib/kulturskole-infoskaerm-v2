import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import React from "react";
import ReactDOM from "react-dom";
import { createMemoryRouter } from "react-router-dom";
import { version as muiVersion } from "@mui/material";

const packageJson = JSON.parse(
  readFileSync(new URL("../package.json", import.meta.url), "utf8"),
);
const lockfile = JSON.parse(
  readFileSync(new URL("../package-lock.json", import.meta.url), "utf8"),
);

const EXPECTED = Object.freeze({
  react: "19.2.7",
  "react-dom": "19.2.7",
  "react-router-dom": "7.18.2",
  "@mui/material": "9.2.0",
  "@mui/icons-material": "9.2.0",
  "@mui/x-date-pickers": "9.9.0",
  "@hello-pangea/dnd": "18.0.1",
  "date-fns": "4.4.0",
});

test("React Router runtime kan initialiseres", () => {
  const router = createMemoryRouter([{ path: "/", element: null }]);
  assert.equal(router.state.location.pathname, "/");
});

test("React 19, React Router 7 og MUI 9 runtimeversioner er låst", () => {
  assert.equal(React.version, EXPECTED.react);
  assert.equal(ReactDOM.version, EXPECTED["react-dom"]);
  assert.equal(muiVersion, EXPECTED["@mui/material"]);

  for (const [name, version] of Object.entries(EXPECTED)) {
    assert.equal(packageJson.dependencies[name], version, `${name} er ikke låst i package.json`);
    assert.equal(lockfile.packages[`node_modules/${name}`]?.version, version, `${name} er ikke låst i package-lock.json`);
  }
});

test("kendte frontend security-remediations er låst i package-lock", () => {
  const expected = {
    "brace-expansion": "1.1.18",
    "js-yaml": "4.3.1",
    postcss: "8.5.23",
    "react-router": "7.18.2",
  };

  for (const [name, version] of Object.entries(expected)) {
    assert.equal(
      lockfile.packages[`node_modules/${name}`]?.version,
      version,
      `${name} security-baseline er ikke låst i package-lock.json`,
    );
  }

  assert.equal(lockfile.packages["node_modules/@remix-run/router"], undefined);
});

test("den udfasede react-beautiful-dnd dependency kan ikke genindføres", () => {
  assert.equal(packageJson.dependencies["react-beautiful-dnd"], undefined);
  assert.equal(lockfile.packages["node_modules/react-beautiful-dnd"], undefined);
});
