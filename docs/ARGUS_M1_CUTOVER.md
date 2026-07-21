# Argus M1 Store Cutover

The JSON-to-SQLite transition is a fail-closed, operator-coordinated state
machine. The caller pauses writes, imports the complete JSON snapshot into the
SQLite shadow store, and supplies the digest of the replayed JSON journal.

1. Prepare verifies semantic parity and durably records an immutable JSON
   rollback checkpoint.
2. The caller performs its final paused-write replay.
3. Activate accepts only the identical snapshot and journal digest, verifies
   parity again, then durably marks SQLite active.
4. Rollback is allowed only while the SQLite contents still exactly match
   the retained snapshot; otherwise it refuses to overwrite newer state.

This library control does not itself admit mutations or write legacy runtime
files. Production wiring must continue to use the single-writer adapter and
must reject mutations that cannot be represented by both stores during the
rollback window.
