# Argus M1 Crash Injection

The legacy JSON writer exposes test-only fault boundaries after durable
PREPARED journal creation, JSON file sync, atomic replacement, and COMMITTED
journal creation. The test suite injects an interruption at every boundary,
then invokes recovery and verifies that the mutation is either durably
committed exactly once or aborted without a partial state.

Production callers do not supply a fault hook. This mechanism is solely for
the M1 crash-recovery evidence suite and does not introduce a runtime control
surface.
