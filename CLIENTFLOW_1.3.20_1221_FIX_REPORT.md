# Superseded — do not use as release authority

The first physical-harvest fix package promoted the source identity to
`1.3.20` / sequence `1221` before the full repository CI was green.

That ordering was incorrect.  CI hotfix 1 restores the fix branch to the
currently approved `1.3.19` / `1220` identity.  No 1.3.20/1221 release is being
claimed by this branch at this stage.

`CLIENTFLOW_1220_CI_HOTFIX1_REPORT.md` records the previous CI closure.
The current release-readiness fix is documented in
`CLIENTFLOW_1220_DISPLAY_LIFECYCLE_HOTFIX2_REPORT.md`.
The 1.3.20/1221 identity will be introduced by a separate controlled change
only after this lifecycle hotfix has its own green canonical GitHub push CI.
