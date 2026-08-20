# Applying the 51N change package

Target repository: `kulvib/kulturskole-infoskaerm-v2`

Target branch: `agent/render-v2-canonical-51n`

Verified base before packaging:
`9413f5cd47da97051353418edd4e83db2c0954a4`

This ZIP contains complete replacement contents for five existing files and
seven new files. It contains no deletion request.

If applying from a local checkout, extract the ZIP over the repository root and
then inspect only the paths listed in `51N_CHANGE_MANIFEST.txt` before staging.
Do not stage unrelated files.

After the files are present on the feature branch, run the repository's normal
CI unchanged. Do not merge to `main` until CI and the resulting diff have been
reviewed.

The package metadata files `APPLY_51N.md`, `51N_CHANGE_MANIFEST.txt` and
`51N_SHA256SUMS.txt` are handoff metadata. They do not need to be committed to
the repository unless explicitly desired.
