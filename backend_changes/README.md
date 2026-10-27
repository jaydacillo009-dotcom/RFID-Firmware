# Accept student IDs and item tags on first use

The station collects both UIDs locally, then posts them at final Scan
confirmation. The CLI also accepts legacy preview requests locally.
Neither student nor item registration is required before scanning.

The deployed API creates missing students and items automatically, using their
UIDs as initial display names, inside the same transaction as the loan record.
Existing names/status flags are preserved and do not block recording. Failed
transactions roll back new ID rows. This maintains the database foreign keys
without manual enrollment or a migration.

The API still maintains Receive/Return loan rules: an item cannot have two
open loans, and a return must match its current borrower. The same request ID
returns its saved result on retry. Scanner device authentication still applies.

## Deployed source

The latest complete function is `backend_changes/rfid-api/index.ts` in this
workspace. It has been tested and deployed to Supabase project
`edelmgnzwcngnozaxrsx`. It replaces student/item registration checks while
retaining the existing signed routes and process-state API.

The neighboring backend repository already has the student-only patch, but its
folder is read-only to this agent. The newest item-acceptance change was
therefore deployed from the reviewed source in this workspace. To synchronize
that backend checkout yourself before a future deployment, run from RFID-Ino:

```sh
patch --dry-run -p1 -d ../RFID-Device-BACKEND < backend_changes/accept_item_uid.patch
patch -p1 -d ../RFID-Device-BACKEND < backend_changes/accept_item_uid.patch
```

The earlier `accept_student_uid.patch` is kept for history/review. Do not apply
it again to source that already contains the student change. No firmware change
is needed for automatic item creation. If a transaction was rejected, press
Scan to retry it; a definite rejection can also be cancelled to start again.

## Checks

```sh
node tests/test_backend_patch.mjs backend_changes/rfid-api/index.ts
```

Requires Node 22.13+; runs the real API methods with an in-memory SQL transaction
adapter. Covers missing and inactive student/item UIDs, preserved display names,
transaction rollback, existing loan rules, and idempotent retries. Tests do not
create any real student, item, or loan records.
