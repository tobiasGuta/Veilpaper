# Veilpaper beta: read-only GDM action evidence

**Implemented, not an approval grant.** This is an unprivileged inspection only.
It neither installs/restores GDM resources nor authenticates an administrator.

## CLI examples

```bash
python3 veilpaper.py login approval-review install \
  "$HOME/.cache/veilpaper/login-candidates/prepared-EXAMPLE/candidate.gresource" \
  --sha256 EXACT_64_CHARACTER_LOWERCASE_CANDIDATE_SHA256

python3 veilpaper.py login approval-review restore \
  --active-sha256 EXACT_64_CHARACTER_LOWERCASE_ACTIVE_GDM_SHA256
```

The required digest values above are placeholders, not usable hashes.

## Stable output contract (schema v1)

The command emits a JSON evidence snapshot. It always states
`read_only: true`, `authorization: "NOT_GRANTED"` and
`privileged_helper_available: false`, with an explicit action, expected digest,
observed active/backup/candidate digest and installed RPM digest, a
customization classification, reasons, and a next-gate explanation.

Exit 0 / `STRUCTURAL_REVIEW_ONLY` means only that a proposed first-time
installation had internally consistent *read-only* evidence during inspection.
It is **never permission to write**. Exit 1 / `BLOCKED` means the review
could not qualify its inputs; **all production restore requests are blocked**.

Install review requires a regular single-linked candidate with the exact
expected SHA-256 and independent resource/CSS verification against an
RPM-matching, unmodified active theme. It refuses any pre-existing backup
or manager state rather than overwriting it, and blocks foreign or unknown
customizations, stale digests, missing RPM evidence and review races.

Restore review requires the exact expected active digest, examines existing
theme/RPM/backup consistency, but stays `BLOCKED` even when these match:
the production installer cannot yet establish ownership of pre-existing
customization/backup state or guarantee recovery.

## Security boundary and next steps

No output token or approval can be replayed to bypass the missing privileged
helper. A future helper must independently re-open and verify current state
at the moment of execution, authenticate the administrator, preserve existing
customizations and backups, and prove recovery in qualified guest tests.
The GUI's GDM Apply/Restore remains disabled. Never run disposable-VM-only
writer tooling on the physical Fedora host.

See [interactive Workstation graphical qualification](WORKSTATION_VISUAL_ACCEPTANCE.md)
for the remaining visual acceptance gate.
