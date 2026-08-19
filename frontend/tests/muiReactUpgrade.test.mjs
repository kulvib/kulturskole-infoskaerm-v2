import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  Button,
  Grid,
  MenuItem,
  MenuList,
  TextField,
  ThemeProvider,
  createTheme,
} from "@mui/material";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import { DragDropContext, Droppable, Draggable } from "@hello-pangea/dnd";

const theme = createTheme();

function render(element) {
  return renderToStaticMarkup(
    React.createElement(ThemeProvider, { theme }, element),
  );
}

test("MUI 9 MenuItem renderer under MenuList context", () => {
  const html = render(
    React.createElement(
      MenuList,
      null,
      React.createElement(MenuItem, { selected: true }, "Administration"),
    ),
  );

  assert.match(html, /Administration/);
  assert.match(html, /MuiMenuItem-root/);
});

test("MUI 9 Grid, TextField slots og Button loading renderer", () => {
  const html = render(
    React.createElement(
      Grid,
      { container: true, spacing: 2 },
      React.createElement(
        Grid,
        { size: { xs: 12, md: 6 } },
        React.createElement(TextField, {
          label: "Navn",
          value: "PlanIQ",
          slotProps: { htmlInput: { "data-contract": "slot-props" } },
          onChange: () => {},
        }),
      ),
      React.createElement(
        Grid,
        { size: { xs: 12, md: 6 } },
        React.createElement(Button, { loading: true }, "Gem"),
      ),
    ),
  );

  assert.match(html, /data-contract="slot-props"/);
  assert.match(html, /MuiGrid-root/);
  assert.match(html, /MuiButton-loading/);
});

test("MUI X Date Pickers 9 kan initialiseres med date-fns 4", () => {
  const html = render(
    React.createElement(
      LocalizationProvider,
      { dateAdapter: AdapterDateFns },
      React.createElement(DatePicker, {
        label: "Dato",
        value: null,
        onChange: () => {},
      }),
    ),
  );

  assert.match(html, /Dato/);
  assert.match(html, /MuiPickersInputBase-root/);
});

test("@hello-pangea/dnd eksporterer den bevarede drag-and-drop API", () => {
  for (const [name, component] of Object.entries({ DragDropContext, Droppable, Draggable })) {
    assert.ok(component, `${name} mangler`);
    assert.ok(["function", "object"].includes(typeof component), `${name} har uventet type`);
  }
});
