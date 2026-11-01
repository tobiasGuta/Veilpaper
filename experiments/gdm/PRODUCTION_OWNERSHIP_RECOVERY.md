# Veilpaper production ownership and recovery — offline contract v1

**Status:** offline model implemented; production privilege boundary **NOT IMPLEMENTED**.
This is a pure fixture classifier, not a filesystem inspector, installer,
real-host transaction verifier, authorization grant or recovery command.
[Model source](ownership_recovery_contract.py) |
[Offline tests](../../tests/test_ownership_recovery_contract.py)

## Why recovery cannot simply be copied from the disposable VM

Successful Fedora 44 guest tests proved backup, journal, checksum and SIGKILL
recovery in an isolated marked VM. Its root-owned test markers and confirmation
phrase do not establish ownership of an existing customized real-world theme.

The developer laptop already has a modified GDM resource and an RPM-original
backup. A matching RPM backup must not be reinterpreted as proof that any
newly written production manager owns that modification. Existing data stays
unchanged. No implicit adoption or migration is permitted.

## Input (entirely synthetic, read-only fixture evidence)

The `classify(snapshot)` model accepts exactly these top-level fields:

- `rpm_sha256`, `active_sha256`: exact lowercase SHA-256 strings
- `active_metadata_verified`: Boolean fixture claim, **not proof**
- `legacy_backup_present`, `legacy_manager_state_present`: Booleans
- `transaction_state_present`: Boolean
- `transaction_backup_sha256`: null or exact lowercase SHA-256
- `journal`: null or strict schema-v2-like record

The journal uses the disposable VM field names `version`, `phase`, `base`,
`candidate`, `uid`, `gid`, `mode`, `selinux_hex`, `resource`, `mtime_ns`.
Unknown keys, impossible phase/active combinations, invalid SHA-256, malformed
fields and unsupported metadata are blocked. Matching all the values does
**not** authenticate who created that journal.

## Outcome and preservation policy

| Observation | Classification | Preservation policy |
| --- | --- | --- |
| Stock RPM active, no legacy or transaction records | `FIRST_INSTALL_REVIEW_REQUIRED` | Separate install review only |
| Existing custom active theme | `PRESERVE_FOREIGN_CUSTOMIZATION` | No overwrite or implicit adoption |
| Legacy backup or manager state | `PRESERVE_LEGACY_CUSTOMIZATION` | Preserve both, even on stock RPM |
| Orphan backup without journal | `PRESERVE_ORPHANED_BACKUP` | Preserve unknown backup |
| Journal without original backup | `PRESERVE_MISSING_BACKUP` | No recovery attempt |
| Invalid journal or mismatched digest/phase | `QUARANTINE_*` | Do not overwrite, finalize or delete |
| Install intent, install swap, installed | `INSTALL_INTENT_REVIEW` / `INSTALL_SWAP_REVIEW` / `INSTALLED_REVIEW` | Review only |
| Restore intent, restore swap, restored | `RESTORE_INTENT_REVIEW` / `RESTORE_SWAP_REVIEW` / `RESTORED_RETAIN_EVIDENCE` | Review only, retain evidence |

Every outcome **always** contains `authorization=NOT_GRANTED`,
`write_enabled=false`, `recovery_enabled=false`,
`delete_backup=false`, `delete_journal=false`, and
`requires_independent_ownership_proof=true`.

No matching journal is accepted as an authenticated record or a recovery
permission. Even a correct snapshot is only point-in-time advisory evidence.

## Prerequisites for a separate production privileged helper

1. Independently establish the identity and ownership of a specific new
   Veilpaper transaction and its durable original backup, instead of trusting
   a JSON claim, a matching hash alone, or an existing legacy manager state.
2. Re-open and revalidate live hashes, RPM, path identities, permissions,
   metadata, backups and transaction phase **inside the helper at execution**,
   with fail-closed no-follow/no-replace protections and an exclusive lock.
3. Require real exact-action administrator authentication; no read-only review
   can serve as a replayable grant.
4. Preserve exact original uid/gid, mode, mtime_ns and SELinux/xattrs; durable
   backup, journal/fsync ordering and crash recovery must be separately tested.
5. Block missing backups, changed active resources, unexpected metadata,
   unrecognized phases or interrupted finalization rather than guessing.
6. Do not delete backup/journal on restore until a distinct evidence-retention
   policy is reviewed and proven safe.
7. Demonstrate actual sign-in, lock/unlock and visible wallpaper in a disposable
   interactive Fedora Workstation VM. Offscreen QEMU black output is still
   unqualified; power-loss recovery and emergency console rescue remain open.

The GTK GUI stays unprivileged; login Apply/Restore remain disabled.
Neither this model nor any related tests touch the user's actual GDM theme.
