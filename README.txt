ClientFlow PR #86 CI fix
Target branch: fix/legacy119-runtime-functional-parity
Base PR head observed in CI: 8edb231d7edf91a86fd9a7f3d72e68dcbefcbc74

Scope:
1. Prevent default-False kiosk-lockdown reconciliation from manufacturing a command before canonical observed state exists. Explicit desired=True and explicit pending disable still converge.
2. Update Display runtime integration test for fail-closed Chrome early-protection: Chrome starts at about:blank and the protected navigation boundary receives kiosk_url.
3. Replace obsolete lockdown HTTP-409 readiness oracle with superadmin-allowed/non-superadmin-denied contract.
4. Keep kiosk-lockdown ownership operations out of non-root CI fixture while still testing exact hide/restore.
5. Sandbox Apport and both Firefox policy targets in popup baseline test.

Local evidence in this environment:
- scripts/tests: 184 passed
- directly affected non-DB tests: 3 passed
- Python compileall for all five changed files: PASS
- canonical backend/DB tests require the repo CI dependency environment; GitHub CI log confirms sqlmodel is installed there.
