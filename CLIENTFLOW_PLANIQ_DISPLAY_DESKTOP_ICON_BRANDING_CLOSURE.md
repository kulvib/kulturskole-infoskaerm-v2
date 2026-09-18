# ClientFlow PlanIQ Display desktop-icon branding closure

## Scope

This is an isolated pre-source-freeze UX package after the physical
`CF-1222-LAUNCHER-01` launcher fix. It does not allocate a new release identity,
approve or publish a bundle, or promote the runtime catalog.

Canonical input main:

- commit: `ed97072a3eafabd85f3ebaa7f24cf5f368cd4f70`
- canonical push CI: `#701` / run `35337096131` -> `success`
- source identity before this package: `1.3.21 / 1222`
- runtime catalog: `1.3.21 / 1222`

## Repo-owned brand authority

The repository already contains the square transparent PlanIQ Display mark at:

`frontend/public/brand/planiq-display/planiq-display-mark.png`

That existing file remains the single image authority. The USB builder packages
those exact bytes directly into `payload/planiq-display-mark.png`; this change
does not add or redraw a second logo asset.

## Desktop behavior

The V2 bootstrap persists the mark as:

`/usr/local/lib/clientflow-bootstrap/planiq-display-mark.png`

Generated desktop entries now use that exact absolute path in `Icon=` instead of
the generic `utilities-terminal` icon. This applies to both:

- `01 Klient klargøring`
- `02 Aktiver ClientFlow`

The mark is root-owned/read-only together with the persistent bootstrap and is
removed by the existing exact bootstrap cleanup after healthy canonical
activation. No broader icon-theme or system-wide branding mutation is required.

## USB integrity

The deterministic USB package now contains the repo-owned mark as a fourth
payload file. Both `PAYLOAD_SHA256SUMS.txt` and `USB_SHA256SUMS.txt` bind the
exact logo bytes. The USB start script retains its exact-file-set fail-closed
gate and installs the mark read-only before invoking phase 1.

## Regression gates

Tests prove that:

- generated `.desktop` entries reference the persistent PlanIQ Display mark;
- the old generic `utilities-terminal` icon is no longer emitted;
- the exact existing repo asset is the byte source used by the USB builder;
- the logo is covered by the payload checksum manifest;
- USB exact-file-set expectations include the mark;
- completed bootstrap cleanup removes the mark with the other exact bootstrap files.

## Release boundary

This package intentionally leaves `client/VERSION`, `release_sequence` and the
runtime catalog unchanged. After this package is merged and canonical push CI is
green, the next separate change allocates the new source/build identity
`1.3.22 / sequence 1223`, while the catalog remains on the last physically
published approved release until immutable 1.3.22/1223 publication is complete.

Livestream, Terminal and Remote Desktop implementation domains are untouched.
