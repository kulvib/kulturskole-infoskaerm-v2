# ClientFlow 1.3.30 / sequence 1231 — staged source identity

Status: staged source candidate; not catalog-promoted.

- Source version: `1.3.30`
- Release sequence: `1231`
- Embedded runtime Python: `3.13.14`
- Minimum Ubuntu LTS: `26.04`
- Architecture: `amd64`
- Promoted catalog remains immutable at `1.3.29 / 1230`.
- Catalog 1.3.29 remains `fresh_install` only with `update_allowed=false`.
- No in-place update capability is claimed by this source identity.

The 1.3.30/1231 identity exists so post-1.3.29 physical-acceptance fixes and realtime/cost hardening cannot masquerade as the immutable promoted 1.3.29 bytes.
