# ClientFlow local GUI — deployed 1.1.19 visual parity gate

## Authoritative legacy references

The visual acceptance source is the GUI actually shipped in the deployed
ClientFlow 1.1.19 installer payload.

- `clientflow_gui.py` SHA-256: `027804da4cf3e722ce42a6d7760aa55a1a8f30d901bfc532a1cf63e22d5ba936`
- `status_map.py` SHA-256: `9e6f01fbbe4b23f1458cc2740cea1bc43777499f8d4da3bd83f2a474fb7e74b4`
- legacy GUI size: 107847 bytes / 2644 lines

## Visual/style contract

| Contract item | Status |
|---|---|
| Window title `ClientFlow Status` | PASS |
| Background `#f4f6fa` | PASS |
| Legacy green/red/orange/gray/blue status palette | PASS |
| Arial-based responsive typography | PASS |
| Non-resizable, no-scroll panel | PASS |
| Standard width 43%, height 98%, max width 900 | PASS |
| Compact/large responsive rules | PASS |
| Section order: Handlinger → Systeminfo → Kioskinfo → Netværksinfo → Kalender | PASS |
| Legacy primary Start/Stop buttons remain equal-width | PASS |
| Start legacy green / Stop legacy red | PASS |
| Systeminfo legacy two-column visual grammar | PASS |
| Kioskinfo legacy label/value visual grammar | PASS |
| Network legacy row/copy visual grammar | PASS |
| Copy glyph `⧉` + `Kopieret!` 1.5 s | PASS |
| Seven-row calendar: Dato / Status / Åbner / Lukker | PASS |
| Calendar On green / Off red | PASS |
| Legacy status/message vocabulary ported to V2 runtime state | PASS source-level |
| Logical Wayland monitor coordinates; no HiDPI double scaling | PASS |

## Required V2 extension retained

The visible action layout now follows the deployed 1.1.19 primary geometry: only
the equal-width `Start kiosk` / `Stop kiosk` controls are exposed. V2 does not
expose an administrator-switch action in the appliance GUI. The one retained V2
field extension is rendered inside the legacy visual grammar:

1. `Auto refresh` — canonical Display configuration field.

The same GUI source is also used in `pending_manual_activation`. That lifecycle
mode changes only displayed state and control sensitivity; it does not add a
new panel, button row or alternative graphical layout.

## Physical acceptance still required

Source-level parity cannot prove pixel identity between Tk/ttk and GTK4/Adwaita.
The final target-client gate remains:

1. same target resolution;
2. side-by-side screenshots;
3. font metrics/fallback rendering;
4. row heights/wrapping;
5. GTK decoration/button rendering;
6. compositor-controlled global window position.

GTK4 removed generic toplevel move APIs and Wayland places top-level windows via
the compositor, so absolute legacy `+x+y` placement cannot be truthfully claimed
from application source alone.

Current status:

- legacy visual/style source contract: PASS
- V2 operational extension retained without extra action row: PASS
- physical pixel parity: PENDING target test
- absolute global Wayland position equivalence: platform/compositor controlled
