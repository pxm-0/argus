# Argus M1 Mutation-Gate Cutover

## Purpose

M1 replaces direct writes to legacy configuration JSON with one Argus mutation
writer. During the rollback window, every accepted mutation must be
representable in both the legacy JSON representation and the canonical SQLite
representation, have a versioned reverse transform, and create a hash-chained
audit intent/outcome record.

This is a control-plane cutover. It does not migrate workloads, alter routes,
start tunnels, or expose a service.

## Direct-write inventory

The following paths currently mutate legacy configuration and must be routed
through the writer or explicitly denied during the rollback window:

| Surface | Current mutation | Required M1 disposition |
| --- | --- | --- |
| `oreo-privacy-set` | `privacy.json` | Writer-backed privacy transform (implemented) |
| `oreo-access-apply` | `access.json` | Writer-backed access transform (implemented) |
| Control API privacy endpoint | `privacy.json` | Calls the same writer (implemented) |
| Control API access endpoint | `access.json` | Calls the same writer (implemented) |
| `oreo-workload-add` / register endpoint | workload, privacy, and access registries | Deny until a complete dual-schema registration transform exists |
| Cloudflare effective-state helpers | `access.json` | Deny until an explicit dual-schema transform exists |

Generated dashboard files, private evidence, monitoring output, and backup
artifacts are not entity mutations and remain outside this writer.

## Cutover sequence

1. Freeze the direct mutation surfaces listed above.
2. Build transforms for privacy and access that validate policy and represent
   the change in both schemas. Privacy and policy-approved access are narrowly
   enabled; registration and Cloudflare-effective updates remain frozen.
3. Write a durable audit intent before changing either representation.
4. Commit the legacy JSON journal record and SQLite transaction through the
   single writer.
5. Record the audit outcome only after both representations match.
6. Route the CLI and control API through that writer.
7. Fail closed for registration and Cloudflare-effective mutations until their
   reverse transforms exist.
8. Create a shadow-store parity checkpoint, activate the rollback window, and
   verify a nonempty audit checkpoint off-host.

## Required acceptance evidence

- direct legacy writers are unreachable from mutation entry points;
- each accepted operation has a forward and reverse transform;
- crash tests cover intent, JSON journal, SQLite transaction, and outcome
  boundaries;
- the active SQLite state has semantic parity with the retained JSON snapshot;
- an off-host PC copy verifies the hash-chain checkpoint;
- failed policy, freshness, observation, reconciliation, or audit checks deny
  the mutation without changing either store.
