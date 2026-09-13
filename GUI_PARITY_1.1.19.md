# ClientFlow local GUI — deployed 1.1.19 parity gate

## Authoritative legacy references

The visual acceptance source is the GUI actually shipped in the deployed ClientFlow 1.1.19 installer payload, not loose historical source copies.

- `clientflow_gui.py` SHA-256: `027804da4cf3e722ce42a6d7760aa55a1a8f30d901bfc532a1cf63e22d5ba936`
- `status_map.py` SHA-256: `9e6f01fbbe4b23f1458cc2740cea1bc43777499f8d4da3bd83f2a474fb7e74b4`
- Legacy GUI size: 107847 bytes / 2644 lines

## Source-level visual contract

| Contract item | 1.3.20/1221 status |
|---|---|
| Window title `ClientFlow Status` | PASS |
| Background `#f4f6fa` | PASS |
| Green `#218739`, red `#cc3333`, orange `#ffa500`, gray `#888888`, blue `#1E88E5` | PASS |
| Arial-based dynamically scaled typography | PASS |
| Non-resizable, no-scroll panel | PASS |
| Standard width 43%, height 98%, min 420×620, max width 900 | PASS |
| Compact width 56% / max 760 / min scale 0.66 | PASS |
| Large width 34% / max 1100 / max scale 1.22 | PASS |
| Safe bottom/frame margins 36 / 110 / 24 | PASS |
| Section order: Handlinger → Systeminfo → Kioskinfo → Netværksinfo → Kalender | PASS |
| Exactly two equal-width action buttons: Start kiosk / Stop kiosk | PASS |
| Start button legacy green `#4BB543`; Stop button legacy red | PASS |
| Systeminfo: 14 fields in two equal-width halves, legacy order | PASS |
| Kioskinfo: URL, Status, browser status, current display, backend-selected display, display status | PASS |
| Sleep indicator `💤 Skærm slukket — klient online` | PASS |
| Network: 8 legacy rows with copy affordance | PASS |
| Copy glyph `⧉` and `Kopieret!` for 1.5 seconds | PASS |
| Compact mode hides Aktiv MAC, WiFi MAC, LAN MAC | PASS |
| Calendar: exactly 7 rows; Dato / Status / Åbner / Lukker | PASS |
| Calendar `On` green / `Off` red across the row | PASS |
| Value wrapping instead of ellipsis for legacy information fields | PASS |
| 1-second data refresh cadence | PASS |
| Responsive font/spacing recalculation after display-size changes | PASS |
| GTK4 monitor sizing uses logical Wayland coordinates (no HiDPI double scaling) | PASS |

## Physical acceptance still required

`SOURCE-LEVEL GUI PARITY = PASS` does **not** claim pixel-perfect physical rendering yet.

The following must be checked on the target Ubuntu 26.04 GTK4/Wayland client before final visual acceptance:

1. Actual font metrics for Arial/fallback rendering.
2. GTK/Adwaita frame and button chrome against the legacy Tk/ttk appearance.
3. Exact row heights and wrapping at the target display resolution.
4. Window placement. Legacy Tk/X11 could request explicit global `+x+y` coordinates. A normal GTK4 Wayland top-level window cannot authoritatively force the same global placement; the compositor owns placement. The new GUI matches the legacy size/ratio and internal layout, but absolute global position is a physical/platform acceptance item.
5. Screenshot side-by-side comparison at the same target resolution.

Therefore final status is:

- **Visible/source contract: PASS**
- **Physical pixel parity: PENDING target test**
- **Absolute Wayland window-position equivalence: PLATFORM LIMITATION / PENDING acceptance**
