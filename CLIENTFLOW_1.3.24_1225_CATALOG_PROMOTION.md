# ClientFlow 1.3.24 / sequence 1225 — runtime catalog promotion

## Authority chain

This change is the separate runtime-selection promotion required by the canonical
release procedure. It changes no ClientFlow runtime implementation bytes.

Exact promoted release:

- release id: `clientflow-1.3.24-seq-1225`
- source commit: `929d3eb74334bd8d9177d2792f33f92ac338b5cb`
- canonical push CI: `#779` / run `35511136741` / success
- runtime-input transport: `runtime-inputs-1225-transport`
- runtime-input transport SHA-256: `233e2e36323bcb7c15bf3d44eeb03c46a00edf84746a50598cde18d565976619`
- release build run: `35511471702`
- candidate SHA-256: `57d7c3629a70dd2c2a353470707f3eef1dc65cdf5a8305b093e151311a0b9baf`
- payload SHA-256: `c7ab9c1569c96583848bfa832b9c2a9eadb6d007e4d26333de783d20c10efc46`
- installer SHA-256: `b158e2bcc786b60485730a0a61b1bd6d238cf89387b816384c54f635512f42c0`
- approval run: `35511931903`
- approval reference: `clientflow-1.3.24-seq-1225/manual-approval/candidate-57d7c3629a70dd2c2a353470707f3eef1dc65cdf5a8305b093e151311a0b9baf`
- approved bundle SHA-256: `032d49c9c3db7f88bcb31dac8aeefa24db45684a95344fd38ee64a2572b327ae`
- approved bundle size: `223119360`
- approved transport tag: `clientflow-1.3.24-1225-approved-transport`
- immutable store path: `/var/data/clientflow-release-artifacts/store/clientflow-1.3.24-seq-1225.tar`

## Completed gates before promotion

1. The exact 1.3.24/1225 source commit passed canonical push CI.
2. Sequence-1225 runtime-input transport was published as transport-only and
   pinned to the current repo platform lock.
3. Canonical release-build run `35511471702` produced two byte-identical
   independent 1.3.24/1225 candidates.
4. The Ubuntu 26.04 executable-candidate gate passed.
5. Approval run `35511931903` manually approved the exact reproducible candidate
   with the immutable approval reference above.
6. The approved bundle was transported through GitHub prerelease
   `clientflow-1.3.24-1225-approved-transport`, explicitly marked transport-only.
7. The transport asset re-read at exactly `223119360` bytes and SHA-256
   `032d49c9c3db7f88bcb31dac8aeefa24db45684a95344fd38ee64a2572b327ae`.
8. The exact approved bytes were published by `scripts/publish_clientflow_release.py`
   into the canonical Render immutable artifact-store path above.
9. The stored file was independently re-read as a regular 223119360-byte file
   and matched the approved SHA-256 exactly.
10. The stored manifest was independently re-read and proved `deployable: true`,
    release id/version/sequence, source commit and approval reference; the
    transport and store manifest bytes were identical.
11. The runtime catalog remained 1.3.23/1224 throughout build, approval,
    transport, publication and independent immutable-store verification.

## Catalog policy after promotion

- `catalog_sequence = 1225`
- `latest_stable = 1.3.24`
- `default_install_version = 1.3.24`
- the single selectable release is `clientflow-1.3.24-seq-1225`
- `min_current_version = 1.3.11` remains unchanged because 1.3.11 is the
  canonical safe in-place update baseline enforced by backend policy
- rollback remains disabled and the controlled reboot remains required
- retention remains one installable release in catalog metadata

The catalog deliberately does not duplicate bundle hashes, approval references,
candidate hashes or source commit as selector fields. Those values remain
authoritative in the immutable published artifact and this promotion record.

## Included release closures

The promoted release contains the canonical repairs proven after the physical
1.3.23/1224 Ubuntu 26.04 acceptance failure:

- the temporary customer-activation sudoers capability is compatible with
  Ubuntu 26.04 `sudo-rs` while remaining exact-path and no-arguments-only;
- factory/shipping network cleanup removes persistent Netplan network subtrees
  and fails closed if Netplan can regenerate a shipping profile;
- controlled reboot uses systemd 259's documented inhibitor-control spelling,
  `--check-inhibitors=no`.

The existing two-phase `01 Klient klargøring` -> reboot -> `02 Aktiver ClientFlow`
-> pending GUI -> backend approval -> automatic activation lifecycle remains the
canonical customer flow.

## Scope boundary

This promotion changes runtime selection only. It does not modify ClientFlow
runtime implementation, source/build identity, release build bytes, installer
bytes, approved bundle bytes, approval metadata or the immutable artifact store.

## Next gate

After full GitHub CI, merge and deployment of this promotion, verify that the
running backend reports 1.3.24/1225 as the only stable/default fresh-install
selection while the immutable store still re-reads the exact approved bundle
SHA-256. Then regenerate and verify the canonical ClientFlow preparation USB from
promoted main and restart clean Ubuntu Desktop 26.04 physical fresh-install
acceptance from phase 0: `01 Klient klargøring` -> reboot -> `02 Aktiver ClientFlow`
-> pending GUI -> backend approval -> automatic canonical activation -> healthy
active runtime.
