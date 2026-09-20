Branch: fix/clientflow-1225-physical-acceptance-blockers
Source of truth: kulturskole-infoskaerm-v2-main(20260920-132657).zip
Scope: canonical fixes for confirmed 1.3.24 / seq 1225 physical acceptance blockers.
No files are to be deleted.
Local validation:
- scripts/tests: 264 passed
- backend/tests/test_clientflow_runtime_quiesce.py: 6 passed
- Python syntax compile/parse of changed product/test files: PASS
Backend identity test is included for CI; local container lacks sqlmodel, so full backend suite is GitHub CI gate.
