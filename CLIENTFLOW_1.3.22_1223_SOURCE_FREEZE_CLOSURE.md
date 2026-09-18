# ClientFlow 1.3.22 / sequence 1223 — source-freeze closure

## Scope

This is the source-freeze gate for the release that carries the physical
`CF-1222-LAUNCHER-01` repair and PlanIQ Display desktop-icon branding.
It allocates source/build identity 1.3.22/1223 while deliberately leaving the
runtime catalog at the already published 1.3.21/1222 selector.

Canonical pre-freeze main:

- commit: `edb740b5a32055918e36ad0ec28232b4b1ae6ab7`
- source identity before freeze: `1.3.21 / 1222`
- runtime catalog: `1.3.21 / 1222`

## Frozen candidate identity

- `client/VERSION = 1.3.22`
- `release_sequence = 1223`
- candidate release id: `clientflow-1.3.22-seq-1223`
- Ubuntu minimum: `26.04`
- architecture: `amd64`
- runtime Python: `3.13.14`

The exact post-merge Git commit is intentionally not self-embedded. The final
40-character source-freeze SHA must be recorded after canonical GitHub CI
succeeds.

## Catalog boundary

This freeze does not publish or promote the candidate. The runtime catalog
remains byte-for-byte on:

- catalog sequence `1222`;
- latest/default version `1.3.21`;
- selected release `clientflow-1.3.21-seq-1222`.

Regression contracts require the source sequence to lead the catalog by
exactly one and require the catalog selector to remain 1.3.21/1222 until the
new immutable bundle exists and has been independently verified.

## Physical failure closure included

The frozen candidate contains the source repair for the physical failure found
on Viborg2:

- desktop files were executable, valid and GNOME-trusted;
- physical journal proved `/usr/local/bin/clientflow-open-factory-prepare`
  stopped with `rc: unbound variable`;
- the unsafe outer `RUN="...$rc..."` assignment has been removed;
- `shlex.quote()` now protects the title and complete inner command;
- Ptyxis is explicitly supported before the generic terminal fallback;
- regression tests execute the generated wrapper rather than relying only on
  `bash -n`.

## Desktop branding included

The candidate also carries the already merged PlanIQ Display desktop icon
closure. Both installation launchers use the existing repo-owned mark, copied
into the verified bootstrap payload and covered by both USB checksum manifests.
No duplicate or redrawn brand asset is introduced.

## Frozen implementation domains

This source-freeze does not modify Livestream, Terminal, or Remote Desktop
implementation domains.

## Next canonical gates

After merge and green canonical push CI:

1. record the exact source-freeze SHA;
2. lock/verify sequence-1223 runtime inputs;
3. produce two independent release builds from the same source/runtime inputs;
4. require byte-identical outputs and Ubuntu 26.04 executable-candidate PASS;
5. manually approve the exact candidate;
6. immutably publish and independently re-read the approved bytes;
7. separately promote catalog 1223 / 1.3.22;
8. regenerate the canonical preparation USB;
9. restart the physical Ubuntu 26.04 fresh-install acceptance from phase 0.
